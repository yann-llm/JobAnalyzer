"""Job posting scrape + company enrichment orchestrator.

Usage::

    python main.py https://example.com/job/123

Pipeline:
    1. Auto-launch Chrome (visible) with --remote-debugging-port=9222 and a
       persistent profile dir. If Chrome is already running on 9222, reuse it.
    2. Open the URL in that Chrome via CDP. If the site bounces to login,
       wait for the user to finish login in the visible window, then resume.
    3. Pull title / text / html through CDP Runtime.evaluate.
    4. Enrich the cleaned payload with QCC company data when configured.
    5. Persist raw / cleaned / summary artifacts under
       ``data/<url_slug>/`` and print a brief summary.

First-time login persists in ``.chrome-debug-profile/`` next to this file;
subsequent runs are silent as long as cookies are valid.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Force UTF-8 on Windows consoles so Chinese error messages don't crash with GBK.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

from external_data import enrich as enrich_external_data
from scraper import ScraperError, clean_job_page, fetch_job_page, find_business_detail_url_for_page
from scraper.job_scraper import default_profile_dir

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DEFAULT_CDP_PORT = 9222


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def slugify_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "page"
    path = parsed.path or ""
    raw = f"{host}{path}".strip("/")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)[:80] or "page"
    return slug.strip("_") or "page"


def run_dir(url: str) -> Path:
    return DATA_DIR / slugify_url(url)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def enrich_business_info_from_company_page(
    cleaned: dict[str, Any],
    *,
    base_dir: Path,
    profile_dir: Path,
    port: int,
    prefer_existing_tab: bool,
    login_wait_timeout: int,
) -> dict[str, Any]:
    """Fetch the BOSS company page when the job page hides the credit code."""
    business_info = cleaned.setdefault("business_info", {})
    if business_info.get("unified_social_credit_code"):
        return cleaned

    company_url = (business_info.get("company_detail_url") or "").strip()
    if not company_url:
        return cleaned

    seen_urls: set[str] = set()
    next_url: str | None = company_url
    for attempt in range(1, 3):
        if not next_url or next_url in seen_urls or business_info.get("unified_social_credit_code"):
            break
        seen_urls.add(next_url)
        print(f"[抓取] 公司工商详情页: {next_url}")
        try:
            company_page = fetch_job_page(
                next_url,
                profile_dir=profile_dir,
                port=port,
                screenshot_dir=None,
                prefer_existing_tab=prefer_existing_tab,
                login_wait_timeout=login_wait_timeout,
            )
        except ScraperError as exc:
            business_info["company_detail_fetch_error"] = str(exc)
            print(f"[提示] 公司详情页抓取失败（继续使用职位页工商信息）：{exc}")
            return cleaned

        company_cleaned = clean_job_page(company_page)
        company_info = company_cleaned.get("business_info") or {}
        for key, value in company_info.items():
            if value and not business_info.get(key):
                business_info[key] = value
        business_info["company_detail_url"] = company_page.final_url or next_url
        business_info["company_detail_fetched_at"] = company_page.fetched_at

        suffix = "" if attempt == 1 else f"_{attempt}"
        company_dir = base_dir / f"company_detail{suffix}"
        if company_page.html:
            write_text(company_dir / "raw_page.html", company_page.html)
        write_json(
            company_dir / "raw_page_meta.json",
            {**company_page.to_dict(), "html": f"(see raw_page.html, {len(company_page.html or '')} chars)"},
        )
        write_json(company_dir / "cleaned.json", company_cleaned)

        live_detail_url = find_business_detail_url_for_page(company_page, port=port)
        next_url = live_detail_url if live_detail_url and live_detail_url not in seen_urls else None

    return cleaned


def analyze_url(
    url: str,
    *,
    profile_dir: str | Path | None = None,
    port: int = DEFAULT_CDP_PORT,
    keep_screenshot: bool = True,
    prefer_existing_tab: bool = True,
    login_wait_timeout: int = 600,
) -> dict[str, Any]:
    """Run scrape -> clean -> external company enrichment and persist artifacts."""
    generated_at = now_utc()
    base_dir = run_dir(url)
    base_dir.mkdir(parents=True, exist_ok=True)
    profile_path = Path(profile_dir) if profile_dir else default_profile_dir()

    print(f"[抓取] {url}")
    print(f"[抓取] Chrome profile: {profile_path}  port: {port}")
    try:
        page = fetch_job_page(
            url,
            profile_dir=profile_path,
            port=port,
            screenshot_dir=(base_dir / "screenshot") if keep_screenshot else None,
            prefer_existing_tab=prefer_existing_tab,
            login_wait_timeout=login_wait_timeout,
        )
    except ScraperError as exc:
        message = f"抓取失败：{exc}"
        print(f"[中断] {message}")
        summary = {
            "url": url,
            "generated_at": isoformat(generated_at),
            "output_dir": str(base_dir),
            "stage": "scrape",
            "status": "scrape_error",
            "message": str(exc),
        }
        write_json(base_dir / "summary.json", summary)
        return {"summary": summary, "cleaned": None}

    print(
        f"[完成] 抓取  tab_source={page.meta.get('tab_source')}  "
        f"title={page.title!r}  body={page.meta.get('extracted_chars')} 字  "
        f"launched_chrome={page.meta.get('launched_chrome')}"
    )

    cleaned = clean_job_page(page)
    cleaned = enrich_business_info_from_company_page(
        cleaned,
        base_dir=base_dir,
        profile_dir=profile_path,
        port=port,
        prefer_existing_tab=prefer_existing_tab,
        login_wait_timeout=login_wait_timeout,
    )
    print("[整合] 清洗完成，准备整合外部公司数据...")
    cleaned = enrich_external_data(cleaned)
    if page.html:
        write_text(base_dir / "raw_page.html", page.html)
    write_json(
        base_dir / "raw_page_meta.json",
        {**page.to_dict(), "html": f"(see raw_page.html, {len(page.html or '')} chars)"},
    )
    write_json(base_dir / "cleaned.json", cleaned)
    qcc = (cleaned.get("external") or {}).get("qcc")
    if qcc:
        write_json(base_dir / "qcc_raw.json", qcc)

    body_len = len((cleaned.get("body_text") or "").strip())
    if body_len < 80:
        message = (
            f"抓取到的正文内容过短（{body_len} 字）。"
            f"请检查 Chrome 是否已加载完整的目标页面。"
        )
        print(f"[中断] {message}")
        summary = {
            "url": url,
            "generated_at": isoformat(generated_at),
            "output_dir": str(base_dir),
            "stage": "scrape",
            "status": "empty_body",
            "final_url": page.final_url,
            "body_chars": body_len,
            "message": message,
        }
        write_json(base_dir / "summary.json", summary)
        return {"summary": summary, "cleaned": cleaned}

    qcc = qcc or {}

    summary = {
        "url": url,
        "generated_at": isoformat(generated_at),
        "output_dir": str(base_dir),
        "stage": "scrape_and_company_enrich",
        "status": "success",
        "final_url": page.final_url,
        "body_chars": body_len,
        "company_enrichment": {
            "status": qcc.get("status", "not_configured"),
            "search_key": qcc.get("search_key"),
            "anchor": qcc.get("anchor"),
            "error": qcc.get("error"),
        },
    }
    write_json(base_dir / "summary.json", summary)
    return {
        "summary": summary,
        "cleaned": cleaned,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape a job posting URL and enrich company data via QCC.")
    parser.add_argument("url", help="The job posting URL to analyze.")
    parser.add_argument(
        "--profile-dir",
        metavar="PATH",
        help="Persistent Chrome profile directory (default: <project>/.chrome-debug-profile).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_CDP_PORT,
        help=f"Chrome remote debugging port (default: {DEFAULT_CDP_PORT}).",
    )
    parser.add_argument(
        "--no-existing-tab",
        action="store_true",
        help="Always open a new tab instead of reusing one already on the URL.",
    )
    parser.add_argument("--no-screenshot", action="store_true", help="Skip the full-page screenshot.")
    parser.add_argument(
        "--login-wait",
        type=int,
        default=600,
        help="Max seconds to wait for the user to finish login on first run (default: 600).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    result = analyze_url(
        args.url,
        profile_dir=args.profile_dir,
        port=args.port,
        keep_screenshot=not args.no_screenshot,
        prefer_existing_tab=not args.no_existing_tab,
        login_wait_timeout=args.login_wait,
    )

    print("\n=== 抓取与公司信息请求完成 ===")
    summary = result["summary"]
    print(f"输出目录: {summary['output_dir']}")
    if summary.get("status") in {"scrape_error", "empty_body"}:
        print(f"中断阶段: {summary['status']}")
        print(summary.get("message", ""))
        return 1

    company = summary.get("company_enrichment") or {}
    print(f"页面正文: {summary.get('body_chars')} 字")
    print(f"公司信息请求: {company.get('status')}")
    if company.get("search_key"):
        print(f"查询 key: {company['search_key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
