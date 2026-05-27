"""Chrome DevTools Protocol (CDP) based scraper.

Drives a long-running Chrome process that we (or the user) launched with
``--remote-debugging-port=9222`` and a persistent ``--user-data-dir``.

Why CDP instead of Playwright or opencli:

- Chrome launched with ``--remote-debugging-port`` does NOT show the yellow
  "X is debugging this browser" banner that ``chrome.debugger.attach``
  triggers. The page's ``debugger;`` traps therefore cannot detect us.
- The persistent profile dir keeps cookies / localStorage across runs, so
  the user only needs to log in once.
- We never close user-managed tabs; we only open new tabs via the CDP
  REST API and read them through Runtime.evaluate on a WebSocket.

Lifecycle:

    First run:
      - probe http://127.0.0.1:9222/json/version → not alive
      - launch detached Chrome with persistent profile + target URL
      - poll for CDP readiness
      - if landed on login → wait (poll) for user to finish login
      - after login completes, navigate the tab to the original URL
      - extract title / text / html via Runtime.evaluate

    Subsequent runs:
      - probe → alive (Chrome still running from last time, or relaunched)
      - find a matching tab or open a new one
      - extract
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

DEFAULT_CDP_HOST = "127.0.0.1"
DEFAULT_CDP_PORT = 9222
LOGIN_REDIRECT_MARKERS: tuple[str, ...] = (
    "/login",
    "/signin",
    "/sign-in",
    "/user/login",
    "/web/user",
    "/security-check",
    "/captcha",
    "/verify",
)


class CdpError(RuntimeError):
    """Raised on any CDP-level failure (HTTP, WebSocket, JS exception)."""


@dataclass
class CdpResult:
    final_url: str
    title: str
    text: str
    html: str
    target_id: str


# ---------------------------------------------------------------------------
# Chrome process discovery & launch
# ---------------------------------------------------------------------------

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_cdp_alive(
    port: int = DEFAULT_CDP_PORT,
    *,
    host: str = DEFAULT_CDP_HOST,
    timeout: float = 2.0,
) -> bool:
    """Return True if Chrome with CDP is reachable on ``host:port``."""
    if not is_port_open(host, port, timeout=timeout):
        return False
    try:
        with urlopen(f"http://{host}:{port}/json/version", timeout=timeout) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def find_chrome_executable() -> str | None:
    """Locate a Chrome (or Edge) executable on the current system."""
    env_path = os.environ.get("CHROME_PATH")
    candidates: list[str] = []
    if env_path:
        candidates.append(env_path)
    if sys.platform == "win32":
        candidates.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ])
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        candidates.append("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    else:
        candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ])
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def launch_chrome_with_cdp(
    profile_dir: Path,
    *,
    port: int = DEFAULT_CDP_PORT,
    initial_url: str = "about:blank",
) -> subprocess.Popen:
    """Launch a detached Chrome with remote debugging enabled."""
    exe = find_chrome_executable()
    if not exe:
        raise CdpError(
            "未找到 Chrome 可执行文件。请安装 Google Chrome 或 Microsoft Edge，"
            "或设置环境变量 CHROME_PATH 指向 chrome.exe 路径。"
        )
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        # Newer Chrome rejects WebSocket connects from `http://127.0.0.1:9222`
        # unless we explicitly allow the origin. `*` is fine here because the
        # CDP port is bound to localhost only.
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        initial_url,
    ]
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(args, creationflags=flags, close_fds=True)
    return subprocess.Popen(
        args,
        start_new_session=True,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_cdp(port: int = DEFAULT_CDP_PORT, *, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_cdp_alive(port):
            return True
        time.sleep(0.5)
    return False


def _kill_pids(pids: list[int]) -> None:
    """Best-effort kill of the given PIDs on Windows / POSIX."""
    if not pids:
        return
    if sys.platform == "win32":
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            except Exception:  # noqa: BLE001
                pass
    else:
        import signal as _signal
        for pid in pids:
            try:
                os.kill(pid, _signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass


def _find_scoped_chrome_pids(port: int, profile_dir: Path) -> list[int]:
    """Return PIDs of Chrome processes that own the CDP port + profile.

    We match on the command line containing BOTH ``--remote-debugging-port=<port>``
    and ``--user-data-dir=<profile_dir>`` so we never touch the user's
    everyday Chrome.
    """
    if sys.platform != "win32":
        try:
            output = subprocess.run(
                ["ps", "-eo", "pid,command"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:  # noqa: BLE001
            return []
        pids: list[int] = []
        port_token = f"--remote-debugging-port={port}"
        profile_token = f"--user-data-dir={profile_dir}"
        for line in output.splitlines():
            if port_token in line and profile_token in line:
                head = line.strip().split(None, 1)[0]
                if head.isdigit():
                    pids.append(int(head))
        return pids

    try:
        output = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='chrome.exe' or name='msedge.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:list",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:  # noqa: BLE001
        return []

    pids: list[int] = []
    current: dict[str, str] = {}
    port_token = f"--remote-debugging-port={port}"
    profile_str = str(profile_dir)
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            if current:
                cmd = current.get("CommandLine", "")
                pid_str = current.get("ProcessId", "")
                if (
                    port_token in cmd
                    and profile_str in cmd
                    and pid_str.isdigit()
                ):
                    pids.append(int(pid_str))
                current = {}
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            current[key.strip()] = value
    if current:
        cmd = current.get("CommandLine", "")
        pid_str = current.get("ProcessId", "")
        if port_token in cmd and profile_str in cmd and pid_str.isdigit():
            pids.append(int(pid_str))
    return pids


def shutdown_scoped_chrome(port: int, profile_dir: Path) -> int:
    """Kill the scoped Chrome (only our debug instance). Returns count killed."""
    pids = _find_scoped_chrome_pids(port, profile_dir)
    _kill_pids(pids)
    return len(pids)


def ensure_cdp(
    profile_dir: Path,
    *,
    port: int = DEFAULT_CDP_PORT,
    initial_url: str = "about:blank",
    launch_timeout: float = 30.0,
    relaunch_if_origin_mismatch: bool = True,
) -> bool:
    """Ensure CDP is reachable; launch Chrome if not. Returns True iff launched.

    When ``relaunch_if_origin_mismatch`` is True, a pre-existing scoped Chrome
    that was launched WITHOUT ``--remote-allow-origins=*`` will be killed and
    relaunched with the correct flag. This is necessary on Chrome 128+ where
    the new origin lockdown rejects all CDP WebSocket connects otherwise.
    """
    if is_cdp_alive(port):
        if relaunch_if_origin_mismatch and not _origin_allowed(port, profile_dir):
            print(
                "[CDP] 现有 Chrome 实例未启用 --remote-allow-origins=*，"
                "需重启该实例以允许 WebSocket 连接。"
            )
            killed = shutdown_scoped_chrome(port, profile_dir)
            print(f"[CDP] 已结束 {killed} 个旧实例，正在以正确参数重启…")
            launch_chrome_with_cdp(profile_dir, port=port, initial_url=initial_url)
            if not wait_for_cdp(port, timeout=launch_timeout):
                raise CdpError(f"重启 Chrome 后 CDP 仍未响应（端口 {port}）。")
            print(f"[CDP] Chrome 已就绪 (port={port})")
            return True
        return False
    print(f"[CDP] 端口 {port} 未启动，正在以持久化 profile 启动 Chrome…")
    launch_chrome_with_cdp(profile_dir, port=port, initial_url=initial_url)
    if not wait_for_cdp(port, timeout=launch_timeout):
        raise CdpError(f"启动 Chrome 后 CDP 仍未响应（端口 {port}，超时 {launch_timeout}s）。")
    print(f"[CDP] Chrome 已就绪 (port={port}, profile={profile_dir})")
    return True


def _origin_allowed(port: int, profile_dir: Path) -> bool:
    """Heuristic: do a no-op WebSocket handshake to detect 403 origin rejection."""
    try:
        tabs = list_tabs(port)
    except Exception:  # noqa: BLE001
        return False
    page = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
    if not page:
        # No page tab to test against — assume OK; will surface on real use.
        return True
    try:
        import websocket  # type: ignore

        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=3, origin="")
        ws.close()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# CDP REST endpoints
# ---------------------------------------------------------------------------

def list_tabs(port: int = DEFAULT_CDP_PORT) -> list[dict[str, Any]]:
    with urlopen(f"http://{DEFAULT_CDP_HOST}:{port}/json/list", timeout=5) as resp:
        return json.loads(resp.read())


def open_tab(url: str, port: int = DEFAULT_CDP_PORT) -> dict[str, Any]:
    req = Request(
        f"http://{DEFAULT_CDP_HOST}:{port}/json/new?{quote(url, safe='')}",
        method="PUT",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def activate_tab(target_id: str, port: int = DEFAULT_CDP_PORT) -> None:
    try:
        req = Request(
            f"http://{DEFAULT_CDP_HOST}:{port}/json/activate/{target_id}",
            method="PUT",
        )
        with urlopen(req, timeout=5):
            pass
    except Exception:  # noqa: BLE001 - activation is best-effort
        pass


def find_matching_tab(url: str, *, port: int = DEFAULT_CDP_PORT) -> dict[str, Any] | None:
    """Return the first ``type=page`` tab whose URL matches the target."""
    parsed = urlparse(url)
    candidates = [tab for tab in list_tabs(port) if tab.get("type") == "page"]
    for tab in candidates:
        tab_url = tab.get("url") or ""
        if tab_url == url or url in tab_url:
            return tab
    for tab in candidates:
        tab_url = tab.get("url") or ""
        tab_parsed = urlparse(tab_url)
        if (
            tab_parsed.netloc == parsed.netloc
            and parsed.path
            and parsed.path.rstrip("/") in tab_parsed.path
        ):
            return tab
    return None


def looks_like_login_redirect(url: str) -> bool:
    lower = (url or "").lower()
    return any(marker in lower for marker in LOGIN_REDIRECT_MARKERS)


# ---------------------------------------------------------------------------
# WebSocket Runtime / Page commands
# ---------------------------------------------------------------------------

def _cdp_call(ws_url: str, method: str, params: dict[str, Any] | None = None,
              *, timeout: float = 30.0) -> dict[str, Any]:
    """Send a single CDP command on a fresh WebSocket and return the result.

    Note on ``Origin``: modern Chrome rejects WebSocket handshakes whose
    Origin starts with ``http://127.0.0.1`` unless the browser was launched
    with ``--remote-allow-origins=*``. websocket-client's default Origin is
    derived from the WS URL, so we override it with an empty string — Chrome
    accepts a missing Origin and treats it as a non-browser client.
    """
    import websocket  # lazy: keeps the rest of the package importable w/o it

    ws = websocket.create_connection(ws_url, timeout=timeout, origin="")
    try:
        request = {"id": 1, "method": method, "params": params or {}}
        ws.send(json.dumps(request))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue
            reply = json.loads(raw)
            if reply.get("id") != 1:
                # Skip stray events (page loaded, console messages, etc.)
                continue
            if "error" in reply:
                raise CdpError(f"CDP {method} 错误: {reply['error']}")
            return reply.get("result", {}) or {}
        raise CdpError(f"CDP {method} 超时")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _ws_url_for(target_id: str, port: int) -> str:
    tabs = list_tabs(port)
    match = next((t for t in tabs if t.get("id") == target_id), None)
    if not match:
        raise CdpError(f"目标 tab 不存在：{target_id}")
    ws_url = match.get("webSocketDebuggerUrl")
    if not ws_url:
        raise CdpError(f"目标 tab 没有 WebSocket URL：{target_id}")
    return ws_url


def navigate_tab(target_id: str, url: str, *, port: int = DEFAULT_CDP_PORT) -> None:
    """Navigate an existing tab to a new URL via Page.navigate."""
    ws_url = _ws_url_for(target_id, port)
    _cdp_call(ws_url, "Page.navigate", {"url": url}, timeout=30)


def capture_screenshot(target_id: str, output_path: str | Path,
                       *, port: int = DEFAULT_CDP_PORT) -> None:
    """Save a PNG of the tab to ``output_path`` via Page.captureScreenshot."""
    ws_url = _ws_url_for(target_id, port)
    result = _cdp_call(
        ws_url,
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": True},
        timeout=30,
    )
    data = result.get("data")
    if not data:
        raise CdpError("captureScreenshot 未返回数据")
    Path(output_path).write_bytes(base64.b64decode(data))


def evaluate_in_tab(target_id: str, expression: str,
                    *, port: int = DEFAULT_CDP_PORT, timeout: float = 30.0) -> Any:
    """Run JS in the tab via Runtime.evaluate (returnByValue, awaitPromise)."""
    ws_url = _ws_url_for(target_id, port)
    result = _cdp_call(
        ws_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        timeout=timeout,
    )
    if result.get("exceptionDetails"):
        raise CdpError(f"页面 JS 异常: {result['exceptionDetails']}")
    return result.get("result", {}).get("value")


# ---------------------------------------------------------------------------
# High-level workflows
# ---------------------------------------------------------------------------

def wait_for_url_settle(
    target_id: str,
    *,
    port: int = DEFAULT_CDP_PORT,
    timeout: float = 30.0,
    stable_seconds: float = 2.0,
) -> str:
    """Poll the tab URL until it stops changing for ``stable_seconds``."""
    deadline = time.time() + timeout
    last_url = ""
    last_change = time.time()
    while time.time() < deadline:
        match = next((t for t in list_tabs(port) if t.get("id") == target_id), None)
        if not match:
            return last_url
        current = match.get("url") or ""
        if current != last_url:
            last_url = current
            last_change = time.time()
        elif current and current != "about:blank" and time.time() - last_change >= stable_seconds:
            return current
        time.sleep(0.5)
    return last_url


def wait_for_login_completion(
    target_id: str,
    *,
    port: int = DEFAULT_CDP_PORT,
    timeout: float = 600.0,
    stable_polls: int = 3,
    poll_interval: float = 1.5,
) -> str:
    """Block until the bound tab URL leaves login/security-check markers."""
    print(
        "[CDP] 当前页面停在登录/安全校验。请在自动打开的 Chrome 窗口里完成登录，"
        "脚本会自动检测完成后继续。"
    )
    deadline = time.time() + timeout
    stable = 0
    last_url = ""
    while time.time() < deadline:
        match = next((t for t in list_tabs(port) if t.get("id") == target_id), None)
        if not match:
            return last_url
        current = match.get("url") or ""
        is_login = looks_like_login_redirect(current) or current in {"", "about:blank"}
        if not is_login:
            stable += 1
            if current != last_url:
                print(f"[CDP] 检测到非登录页：{current}  ({stable}/{stable_polls})")
            if stable >= stable_polls:
                return current
        else:
            stable = 0
        last_url = current
        time.sleep(poll_interval)
    raise CdpError(f"等待登录超时（{timeout}s）。最终 URL: {last_url}")


_PAGE_EXTRACT_JS = """
(() => {
  const clean = (s) => (s || '').replace(/\\n{3,}/g, '\\n\\n').trim();
  const text = document.body ? document.body.innerText : '';
  return {
    title: document.title,
    url: location.href,
    text: clean(text),
    html: document.documentElement ? document.documentElement.outerHTML : '',
  };
})()
"""


def extract_page_content(
    target_id: str,
    *,
    port: int = DEFAULT_CDP_PORT,
    text_max_chars: int = 50_000,
    html_max_chars: int = 400_000,
) -> CdpResult:
    """Pull title / text / html out of a tab and trim to safe sizes."""
    payload = evaluate_in_tab(target_id, _PAGE_EXTRACT_JS, port=port)
    if not isinstance(payload, dict):
        raise CdpError("Runtime.evaluate 未返回字典")
    text = (payload.get("text") or "")[:text_max_chars]
    html = (payload.get("html") or "")[:html_max_chars]
    return CdpResult(
        final_url=payload.get("url") or "",
        title=payload.get("title") or "",
        text=text,
        html=html,
        target_id=target_id,
    )


_BOSS_BUSINESS_LINK_JS = """
(() => {
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  const isBusinessText = (s) => /工商|信用|资质|企业信息|公司信息|查看全部/.test(s || '');
  const preferred = anchors.find((a) => {
    const href = a.getAttribute('href') || '';
    const text = (a.innerText || a.textContent || '').trim();
    const ka = a.getAttribute('ka') || '';
    return href.includes('/gongsi/') && (isBusinessText(text) || /cominfo|business|company/i.test(ka));
  });
  const fallback = anchors.find((a) => {
    const href = a.getAttribute('href') || '';
    return href.includes('/gongsi/') && !href.includes('/gongsi/job/');
  });
  const link = preferred || fallback;
  return link ? new URL(link.getAttribute('href'), location.href).href : '';
})()
"""


def find_boss_business_detail_url(
    target_id: str,
    *,
    port: int = DEFAULT_CDP_PORT,
) -> str | None:
    """Find the BOSS company/business detail URL currently visible in a tab."""
    value = evaluate_in_tab(target_id, _BOSS_BUSINESS_LINK_JS, port=port)
    return value if isinstance(value, str) and value.startswith("http") else None


def fetch_via_cdp(
    url: str,
    *,
    profile_dir: Path,
    port: int = DEFAULT_CDP_PORT,
    reuse_existing_tab: bool = True,
    open_url_if_missing: bool = True,
    settle_seconds: float = 2.0,
    settle_timeout: float = 30.0,
    login_wait_timeout: float = 600.0,
) -> tuple[CdpResult, dict[str, Any]]:
    """Auto-launch Chrome (if needed), open / reuse the tab, extract content.

    Handles the login bounce automatically: if the settled URL still looks
    like a login page, we wait for the user to finish login, then renavigate
    to the original URL before extracting.
    """
    launched = ensure_cdp(profile_dir, port=port, initial_url=url, launch_timeout=30.0)
    meta: dict[str, Any] = {"launched_chrome": launched, "port": port,
                            "profile_dir": str(profile_dir)}
    if launched:
        # Give the new Chrome a beat to render its first tab.
        time.sleep(2.0)

    existing = find_matching_tab(url, port=port) if reuse_existing_tab else None
    if existing:
        target_id = existing["id"]
        meta["tab_source"] = "reused"
    elif open_url_if_missing:
        if launched and list_tabs(port):
            # When Chrome was just launched with initial_url, the first tab
            # is already loading our URL — use it instead of opening another.
            first_page = next(
                (t for t in list_tabs(port) if t.get("type") == "page"),
                None,
            )
            target_id = first_page["id"] if first_page else open_tab(url, port=port)["id"]
            meta["tab_source"] = "initial_launch_tab" if first_page else "opened"
        else:
            target_id = open_tab(url, port=port)["id"]
            meta["tab_source"] = "opened"
    else:
        raise CdpError(f"目标 URL 没有匹配 tab：{url}")

    activate_tab(target_id, port=port)
    settled_url = wait_for_url_settle(
        target_id, port=port, timeout=settle_timeout, stable_seconds=settle_seconds,
    )

    if looks_like_login_redirect(settled_url) or not settled_url or settled_url == "about:blank":
        meta["login_required"] = True
        settled_url = wait_for_login_completion(
            target_id, port=port, timeout=login_wait_timeout,
        )
        # After login the site often lands on a different page (e.g. /web/geek/jobs);
        # navigate back to the original URL so extraction sees the job detail.
        if url not in settled_url:
            navigate_tab(target_id, url, port=port)
            settled_url = wait_for_url_settle(
                target_id, port=port, timeout=settle_timeout, stable_seconds=settle_seconds,
            )
            meta["renavigated_to"] = url

    meta["settled_url"] = settled_url
    meta["login_redirect"] = looks_like_login_redirect(settled_url)
    if meta["login_redirect"]:
        raise CdpError(f"页面仍停留在登录/安全校验：{settled_url}")

    # Tiny extra wait so client-rendered detail blocks (job-detail, etc.)
    # finish painting before we read innerText.
    time.sleep(1.0)
    result = extract_page_content(target_id, port=port)
    return result, meta
