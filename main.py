"""Job posting scrape + company enrichment + LLM analysis orchestrator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 on Windows consoles so Chinese error messages don't crash with GBK.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

from external_data import enrich as enrich_external_data
from pipeline.company_data import company_failure_result, company_ready_for_analysis, valid_uscc
from pipeline.company_scrape import enrich_business_info_from_company_page
from pipeline.job_data import (
    DEFAULT_CDP_PORT,
    ProgressCallback,
    cleanup_known_artifacts,
    cleanup_result_artifacts,
    emit_progress,
    final_page_content,
    isoformat,
    now_utc,
    run_dir,
    sync_page_content_business_info,
    write_json,
    write_text,
)
from pipeline.llm_runner import run_analyzers
from scraper import ScraperError, clean_job_page, fetch_job_page
from scraper.job_scraper import default_profile_dir


def analyze_url(
    url: str,
    *,
    profile_dir: str | Path | None = None,
    port: int = DEFAULT_CDP_PORT,
    keep_screenshot: bool = True,
    prefer_existing_tab: bool = True,
    login_wait_timeout: int = 600,
    run_analysis: bool = True,
    progress_callback: ProgressCallback | None = None,
    refresh_analysis: bool = False,
) -> dict[str, Any]:
    """Run scrape -> company page scrape -> company query -> LLM analysis."""
    generated_at = now_utc()
    base_dir = run_dir(url)
    base_dir.mkdir(parents=True, exist_ok=True)
    profile_path = Path(profile_dir) if profile_dir else default_profile_dir()
    cleanup_known_artifacts(base_dir)
    if refresh_analysis:
        cleanup_result_artifacts(base_dir)

    print(f"[抓取] {url}")
    print(f"[抓取] Chrome profile: {profile_path}  port: {port}")
    emit_progress(progress_callback, "launching_chrome", "启动浏览器", 5)
    try:
        page = fetch_job_page(
            url,
            profile_dir=profile_path,
            port=port,
            screenshot_dir=(base_dir / "screenshot") if keep_screenshot else None,
            prefer_existing_tab=prefer_existing_tab,
            login_wait_timeout=login_wait_timeout,
            progress_callback=progress_callback,
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
        return {"summary": summary, "cleaned": None}

    print(
        f"[完成] 抓取  tab_source={page.meta.get('tab_source')}  "
        f"title={page.title!r}  body={page.meta.get('extracted_chars')} 字  "
        f"launched_chrome={page.meta.get('launched_chrome')}"
    )
    emit_progress(progress_callback, "scraping_job", "清洗职位页面正文", 35)

    if page.html:
        write_text(base_dir / "raw_page.html", page.html)

    cleaned = clean_job_page(page)
    cleaned = enrich_business_info_from_company_page(
        cleaned,
        base_dir=base_dir,
        profile_dir=profile_path,
        port=port,
        prefer_existing_tab=prefer_existing_tab,
        login_wait_timeout=login_wait_timeout,
        progress_callback=progress_callback,
    )
    sync_page_content_business_info(cleaned)
    business_info = cleaned.get("business_info") or {}
    body_len = len((cleaned.get("body_text") or "").strip())
    if not valid_uscc(business_info.get("unified_social_credit_code")):
        qcc = {
            "status": "uscc_unresolved",
            "error": business_info.get("company_detail_fetch_error"),
            "note": business_info.get("company_detail_fetch_error") or "公司详情页未抓取到有效统一社会信用代码",
        }
        return company_failure_result(
            url,
            generated_at,
            base_dir,
            page,
            cleaned,
            qcc,
            body_len,
            progress_callback,
        )

    emit_progress(progress_callback, "scraping_company", "公司 USCC 获取成功", 50, detail="success")
    company_uscc = valid_uscc(business_info.get("unified_social_credit_code"))
    print(f"[调试] 公司 USCC={company_uscc}")
    print(f"[调试] 公司名称={business_info.get('company_name') or business_info.get('company_header_name') or ''}")
    print(f"[调试] USCC 来源={business_info.get('unified_social_credit_code_source') or 'job_or_company_page'}")
    if business_info.get("uscc_lookup"):
        print(f"[调试] Tavily 查询={business_info['uscc_lookup']}")

    print("[整合] 公司 USCC 已获取，准备查询外部公司数据...")
    emit_progress(progress_callback, "qcc_enrich", "企查查公司信息查询", 55)
    cleaned = enrich_external_data(cleaned)
    sync_page_content_business_info(cleaned)
    qcc = ((cleaned.get("external") or {}).get("qcc") or {})

    if not company_ready_for_analysis(qcc):
        return company_failure_result(
            url,
            generated_at,
            base_dir,
            page,
            cleaned,
            qcc,
            body_len,
            progress_callback,
        )

    write_json(base_dir / "job_cleaned.json", final_page_content(cleaned))
    anchor = qcc.get("anchor") or {}
    uscc = (anchor.get("统一社会信用代码") or "").strip()
    write_json(base_dir / "company.json", {
        "uscc": uscc,
        "company_name": anchor.get("企业名称", ""),
        "cache_path": f"_company_cache/{uscc}.json" if uscc else None,
        "status": "ok",
        "cache_hit": qcc.get("cache_hit", False),
    })

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
        return {"summary": summary, "cleaned": cleaned}

    analysis_bundle = None
    if run_analysis:
        job_cleaned = final_page_content(cleaned)
        analysis_bundle = run_analyzers(url, base_dir, job_cleaned, progress_callback=progress_callback)
        if analysis_bundle is None:
            message = "LLM 分析未生成结果，无法展示报告。请检查 analyzers 导入、LLM 配置或运行日志。"
            emit_progress(progress_callback, "error", message, 100, detail="analysis_failed")
            summary = {
                "url": url,
                "generated_at": isoformat(generated_at),
                "output_dir": str(base_dir),
                "stage": "analysis",
                "status": "analysis_error",
                "final_url": page.final_url,
                "body_chars": body_len,
                "message": message,
                "company_enrichment": {
                    "status": qcc.get("status", "not_configured"),
                    "search_key": qcc.get("search_key"),
                    "anchor": qcc.get("anchor"),
                    "error": qcc.get("error"),
                },
                "analysis": {
                    "status": "error",
                    "candidate_profile_used": False,
                },
            }
            return {
                "summary": summary,
                "cleaned": cleaned,
                "analysis": None,
            }

    summary = {
        "url": url,
        "generated_at": isoformat(generated_at),
        "output_dir": str(base_dir),
        "stage": "scrape_company_enrich_analysis" if analysis_bundle else "scrape_and_company_enrich",
        "status": "success",
        "final_url": page.final_url,
        "body_chars": body_len,
        "company_enrichment": {
            "status": qcc.get("status", "not_configured"),
            "search_key": qcc.get("search_key"),
            "anchor": qcc.get("anchor"),
            "error": qcc.get("error"),
        },
        "analysis": {
            "status": "ok" if analysis_bundle else "skipped",
            "candidate_profile_used": bool(analysis_bundle and analysis_bundle.get("candidate_profile_used")),
        },
    }
    emit_progress(progress_callback, "done", "分析完成", 100, slug=base_dir.name)
    return {
        "summary": summary,
        "cleaned": cleaned,
        "analysis": analysis_bundle,
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
    parser.add_argument("--screenshot", action="store_true", help="Save a full-page screenshot.")
    parser.add_argument(
        "--login-wait",
        type=int,
        default=600,
        help="Max seconds to wait for the user to finish login on first run (default: 600).",
    )
    parser.add_argument(
        "--no-analysis",
        action="store_true",
        help="Skip the LLM analysis stage (only scrape + QCC enrich).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    result = analyze_url(
        args.url,
        profile_dir=args.profile_dir,
        port=args.port,
        keep_screenshot=args.screenshot,
        prefer_existing_tab=not args.no_existing_tab,
        login_wait_timeout=args.login_wait,
        run_analysis=not args.no_analysis,
    )

    print("\n=== 抓取与公司信息请求完成 ===")
    summary = result["summary"]
    print(f"输出目录: {summary['output_dir']}")
    if summary.get("status") in {"scrape_error", "empty_body", "company_info_error"}:
        print(f"中断阶段: {summary['status']}")
        print(summary.get("message", ""))
        return 1
    company = summary.get("company_enrichment") or {}
    print(f"页面正文: {summary.get('body_chars')} 字")
    print(f"公司信息请求: {company.get('status')}")
    if company.get("search_key"):
        print(f"查询 key: {company['search_key']}")

    analysis = result.get("analysis")
    if analysis:
        final = analysis.get("final") or {}
        final_analysis = final.get("analysis") or {}
        score = (final_analysis.get("综合评分") or {}).get("分数") if isinstance(final_analysis.get("综合评分"), dict) else None
        action = final_analysis.get("建议动作")
        print(
            f"分析完成: {len(analysis.get('modules') or {})} 个子模块"
            + (f" · 综合评分 {score}" if score is not None else "")
            + (f" · 建议 {action}" if action else "")
        )
    elif summary.get("analysis", {}).get("status") == "skipped":
        print("分析已跳过（--no-analysis）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
