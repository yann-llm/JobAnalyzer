"""Job posting scraper (CDP-backed).

Uses Chrome's remote debugging port via a persistent profile directory:

- First run launches Chrome (visible) with ``--remote-debugging-port=9222``
  and ``--user-data-dir=<project>/.chrome-debug-profile/``. If the target
  URL bounces to login, the script waits for the user to finish login in
  the visible window, then continues automatically.
- Subsequent runs reuse the same profile (cookies persist) and either
  attach to a still-running Chrome or relaunch it silently. No user action
  needed once the cookies are valid.

Chrome started with ``--remote-debugging-port`` does NOT display the yellow
"X is debugging this browser" banner, so anti-debug pages like Zhipin's
``debugger;`` trap can't detect us — the page stays on screen instead of
being kicked to ``about:blank``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import cdp_scraper as cdp

DEFAULT_PROFILE_DIRNAME = ".chrome-debug-profile"


class ScraperError(RuntimeError):
    """Raised when the scraper cannot deliver a usable page."""


@dataclass
class JobPageContent:
    """Result returned by ``fetch_job_page``."""

    url: str
    final_url: str
    title: str
    html: str
    text: str
    fetched_at: str
    screenshot_path: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_profile_dir() -> Path:
    """Project-local persistent Chrome profile directory."""
    project_root = Path(__file__).resolve().parent.parent
    return project_root / DEFAULT_PROFILE_DIRNAME


def fetch_job_page(
    url: str,
    *,
    profile_dir: str | Path | None = None,
    port: int = cdp.DEFAULT_CDP_PORT,
    screenshot_dir: str | Path | None = None,
    prefer_existing_tab: bool = True,
    settle_seconds: float = 2.0,
    settle_timeout: float = 30.0,
    login_wait_timeout: float = 600.0,
) -> JobPageContent:
    """Scrape ``url`` through CDP, auto-launching Chrome if needed."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profile = Path(profile_dir) if profile_dir else default_profile_dir()

    try:
        result, cdp_meta = cdp.fetch_via_cdp(
            url,
            profile_dir=profile,
            port=port,
            reuse_existing_tab=prefer_existing_tab,
            settle_seconds=settle_seconds,
            settle_timeout=settle_timeout,
            login_wait_timeout=login_wait_timeout,
        )
    except cdp.CdpError as exc:
        raise ScraperError(str(exc)) from exc

    screenshot_path: str | None = None
    if screenshot_dir is not None:
        try:
            target_dir = Path(screenshot_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            shot = target_dir / f"job_{stamp}.png"
            cdp.capture_screenshot(result.target_id, shot, port=port)
            screenshot_path = str(shot)
        except cdp.CdpError as exc:
            print(f"[scraper] 截图失败（忽略）：{exc}")

    return JobPageContent(
        url=url,
        final_url=result.final_url,
        title=result.title,
        html=result.html,
        text=result.text,
        fetched_at=fetched_at,
        screenshot_path=screenshot_path,
        meta={
            "scraper": "cdp",
            **cdp_meta,
            "target_id": result.target_id,
            "extracted_chars": len(result.text or ""),
            "html_chars": len(result.html or ""),
        },
    )


def find_business_detail_url_for_page(page: JobPageContent, *, port: int = cdp.DEFAULT_CDP_PORT) -> str | None:
    """Return a BOSS business-detail link from the live tab, if one is present."""
    target_id = page.meta.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        return None
    try:
        return cdp.find_boss_business_detail_url(target_id, port=port)
    except cdp.CdpError:
        return None
