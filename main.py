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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

# Force UTF-8 on Windows consoles so Chinese error messages don't crash with GBK.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

from external_data import clean_qcc_payload, enrich as enrich_external_data
from scraper import ScraperError, clean_job_page, fetch_job_page, find_business_detail_url_for_page
from scraper.job_scraper import default_profile_dir

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DEFAULT_CDP_PORT = 9222
ProgressCallback = Callable[[dict[str, Any]], None]


def emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    message: str,
    percent: int,
    *,
    detail: str | None = None,
    slug: str | None = None,
) -> None:
    if not progress_callback:
        return
    event: dict[str, Any] = {
        "stage": stage,
        "message": message,
        "percent": max(0, min(100, int(percent))),
    }
    if detail:
        event["detail"] = detail
    if slug:
        event["slug"] = slug
    progress_callback(event)


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


def cleanup_known_artifacts(base_dir: Path) -> None:
    """Remove prior generated artifacts that are no longer part of the contract."""
    base = base_dir.resolve()
    data_root = DATA_DIR.resolve()
    if not (base == data_root or data_root in base.parents):
        raise ValueError(f"Refusing to clean outside data dir: {base}")
    for name in (
        "raw_page_meta.json",
        "raw_page.json",
        "cleaned_page_content.json",
        "cleaned.json",
        "summary.json",
        "qcc_raw.json",
    ):
        target = base_dir / name
        if target.exists():
            target.unlink()
    for name in ("company_detail", "company_detail_2", "screenshot", "company_qcc"):
        target = base_dir / name
        if target.exists() and target.is_dir():
            shutil.rmtree(target)


def cleanup_result_artifacts(base_dir: Path) -> None:
    """Remove current result artifacts before refreshing LLM analysis."""
    base = base_dir.resolve()
    data_root = DATA_DIR.resolve()
    if not (base == data_root or data_root in base.parents):
        raise ValueError(f"Refusing to clean outside data dir: {base}")
    for name in ("analysis.json", "job_cleaned.json", "company.json", "raw_page.html"):
        target = base_dir / name
        if target.exists():
            target.unlink()


def business_info_to_chinese(info: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "company_name": "公司名称",
        "unified_social_credit_code": "统一社会信用代码",
        "legal_representative": "法定代表人",
        "established_date": "成立日期",
        "company_type": "企业类型",
        "business_status": "经营状态",
        "registered_capital": "注册资金",
        "company_detail_url": "公司详情页",
    }
    return {label: info[key] for key, label in mapping.items() if info.get(key)}


def sync_page_content_business_info(cleaned: dict[str, Any]) -> None:
    page_content = cleaned.setdefault("page_content", {})
    business_info = cleaned.get("business_info") or {}
    page_content["工商信息"] = business_info_to_chinese(business_info)


def final_page_content(cleaned: dict[str, Any]) -> dict[str, Any]:
    page_content = cleaned.get("page_content") or {}
    fields = (
        "职位名称",
        "薪资",
        "职位工作地点",
        "要求年限",
        "学历要求",
        "职位描述",
        "工商信息",
        "工作地址",
    )
    return {field: page_content.get(field) for field in fields}


def load_company_cleaned(base_dir: Path) -> dict[str, Any] | None:
    """Resolve `company.json` to the cleaned company data (with industry_data merged in).

    Returns None when there's no company reference or the cache file is missing.
    """
    ref_path = base_dir / "company.json"
    if not ref_path.exists():
        return None
    try:
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if ref.get("status") != "ok":
        return None
    cache_rel = ref.get("cache_path")
    if not cache_rel:
        return None
    cache_path = DATA_DIR / cache_rel
    if not cache_path.exists():
        print(f"[分析] 公司缓存缺失: {cache_path}")
        return None
    try:
        cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    block = cache_payload.get("qcc_block") or {}
    cleaned = dict(block.get("cleaned") or {})
    industry_data = block.get("industry_data")
    if industry_data:
        cleaned["industry_data"] = industry_data
    return cleaned or None


def load_candidate_profile() -> dict[str, Any] | None:
    """Load candidate profile from project root, returning None when missing/invalid."""
    profile_path = PROJECT_DIR / "candidate_profile.json"
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[分析] candidate_profile.json 解析失败: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    # Skip the example/schema-comment file gracefully.
    return data


def inject_salary_benchmark(
    job_value_module: dict[str, Any] | None,
    job_cleaned: dict[str, Any],
) -> None:
    """Replace LLM-generated 现金月薪 KPI with Hudson 2025 benchmark lookup.

    Mutates ``job_value_module["analysis"]["维度评分"]["薪酬福利"]["kpis"]`` in
    place. Best-effort: any error logs and skips silently.
    """
    if not job_value_module or job_value_module.get("status") == "error":
        return
    try:
        from external_data.salary_benchmark import (
            format_kpi,
            lookup_salary,
            parse_posted_salary,
        )

        analysis = job_value_module.get("analysis") or {}
        pay_dim = (analysis.get("维度评分") or {}).get("薪酬福利")
        if not isinstance(pay_dim, dict):
            return
        kpis = pay_dim.get("kpis")
        if not isinstance(kpis, list):
            return

        title = job_cleaned.get("职位名称") or ""
        salary = job_cleaned.get("薪资") or ""
        bench = lookup_salary(title)
        lo, hi = parse_posted_salary(salary)
        if lo is None and hi is None:
            return  # No parseable salary -> keep LLM output

        new_kpi = format_kpi(bench, lo, hi)
        new_kpi["source"] = "Hudson 2025" if bench else "JD原文"

        # Replace the KPI whose label looks like a salary metric.
        for i, k in enumerate(kpis):
            label = (k.get("label") or "") if isinstance(k, dict) else ""
            if any(t in label for t in ("月薪", "薪资", "现金", "年包", "包")):
                kpis[i] = new_kpi
                print(f"  [分析] 注入薪酬基准: {new_kpi['val']} | {new_kpi['sub']}")
                return
        # No matching KPI found - prepend so it shows first.
        kpis.insert(0, new_kpi)
        print(f"  [分析] 追加薪酬基准 KPI: {new_kpi['val']} | {new_kpi['sub']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [分析] 薪酬基准注入失败（已跳过）: {type(exc).__name__}: {exc}")


def run_analyzers(
    url: str,
    base_dir: Path,
    job_cleaned: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any] | None:
    """Run all 4 analyzers (job_value/company_risk/industry_outlook/final) and persist.

    Returns the analysis bundle, or None when analyzers cannot be imported / run.
    Failures in individual analyzers are recorded in-place and don't abort the run.
    """
    try:
        from analyzers import ANALYZER_REGISTRY, run_analyzer
        from analyzers.final_evaluation_agent import analyze_final_evaluation
    except ImportError as exc:
        print(f"[分析] 分析器模块加载失败，跳过: {exc}")
        return None

    company_cleaned = load_company_cleaned(base_dir)
    candidate_profile = load_candidate_profile()

    print(
        f"[分析] 启动 LLM 分析（公司数据: "
        f"{'有' if company_cleaned else '无'}, 候选人画像: "
        f"{'有' if candidate_profile else '无'}）"
    )

    # Sub-module analyses run sequentially; each one calls chat_json once.
    module_analyses: dict[str, Any] = {}
    analyzer_progress = {
        "job_value": ("职位综合价值", 70),
        "company_risk": ("公司风险", 80),
        "industry_outlook": ("行业前景", 88),
    }
    for name, analyzer_fn in ANALYZER_REGISTRY.items():
        print(f"  [分析] 运行 {name}...")
        label, percent = analyzer_progress.get(name, (name, 75))
        emit_progress(
            progress_callback,
            "analyzing",
            f"LLM 分析：{label}",
            percent,
            detail=name,
        )
        try:
            module_analyses[name] = run_analyzer(
                analyzer_fn,
                job_cleaned,
                qcc_cleaned=company_cleaned,
                candidate_profile=candidate_profile,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [分析] {name} 失败: {type(exc).__name__}: {exc}")
            module_analyses[name] = {
                "module": name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    # Inject Hudson salary benchmark KPI into job_value.维度评分.薪酬福利.kpis.
    inject_salary_benchmark(module_analyses.get("job_value"), job_cleaned)

    # Final evaluation aggregates the sub-module analyses.
    print("  [分析] 运行 final_evaluation...")
    emit_progress(
        progress_callback,
        "analyzing",
        "LLM 分析：综合评估",
        95,
        detail="final_evaluation",
    )
    try:
        final = analyze_final_evaluation(url, module_analyses, candidate_profile)
    except Exception as exc:  # noqa: BLE001
        print(f"  [分析] final_evaluation 失败: {type(exc).__name__}: {exc}")
        final = {
            "module": "final_evaluation",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    bundle = {
        "url": url,
        "generated_at": isoformat(now_utc()),
        "candidate_profile_used": bool(candidate_profile),
        "modules": module_analyses,
        "final": final,
    }
    write_json(base_dir / "analysis.json", bundle)
    return bundle


def enrich_business_info_from_company_page(
    cleaned: dict[str, Any],
    *,
    base_dir: Path,
    profile_dir: Path,
    port: int,
    prefer_existing_tab: bool,
    login_wait_timeout: int,
    progress_callback: ProgressCallback | None = None,
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
        emit_progress(progress_callback, "scraping_company", "抓取公司详情页", 42)
        try:
            company_page = fetch_job_page(
                next_url,
                profile_dir=profile_dir,
                port=port,
                screenshot_dir=None,
                prefer_existing_tab=prefer_existing_tab,
                login_wait_timeout=login_wait_timeout,
                progress_callback=progress_callback,
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
    run_analysis: bool = True,
    progress_callback: ProgressCallback | None = None,
    refresh_analysis: bool = False,
) -> dict[str, Any]:
    """Run scrape -> clean -> external company enrichment and persist artifacts."""
    generated_at = now_utc()
    base_dir = run_dir(url)
    base_dir.mkdir(parents=True, exist_ok=True)
    profile_path = Path(profile_dir) if profile_dir else default_profile_dir()
    cleanup_known_artifacts(base_dir)
    if refresh_analysis:
        cleanup_result_artifacts(base_dir)

    print(f"[抓取] {url}")
    print(f"[抓取] Chrome profile: {profile_path}  port: {port}")
    emit_progress(progress_callback, "launching_chrome", "启动 Chrome 调试实例", 5)
    try:
        emit_progress(progress_callback, "scraping_job", "抓取职位页面正文", 20)
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
    print("[整合] 清洗完成，准备整合外部公司数据...")
    emit_progress(progress_callback, "qcc_enrich", "企查查公司信息整合", 55)
    cleaned = enrich_external_data(cleaned)
    sync_page_content_business_info(cleaned)
    qcc = (cleaned.get("external") or {}).get("qcc")

    # Write job_cleaned.json (pure job posting fields).
    write_json(base_dir / "job_cleaned.json", final_page_content(cleaned))

    # Write company.json (reference pointer to company cache).
    if qcc and qcc.get("status") == "ok":
        anchor = qcc.get("anchor") or {}
        uscc = (anchor.get("统一社会信用代码") or "").strip()
        company_ref: dict[str, Any] = {
            "uscc": uscc,
            "company_name": anchor.get("企业名称", ""),
            "cache_path": f"_company_cache/{uscc}.json" if uscc else None,
            "status": "ok",
            "cache_hit": qcc.get("cache_hit", False),
        }
        write_json(base_dir / "company.json", company_ref)
    elif qcc:
        write_json(base_dir / "company.json", {
            "status": qcc.get("status", "unknown"),
            "error": qcc.get("error"),
            "note": "公司数据未成功获取，无缓存可引用",
        })

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
        return {"summary": summary, "cleaned": cleaned}

    qcc = qcc or {}

    analysis_bundle = None
    if run_analysis:
        job_cleaned = final_page_content(cleaned)
        analysis_bundle = run_analyzers(url, base_dir, job_cleaned, progress_callback=progress_callback)

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
    if summary.get("status") in {"scrape_error", "empty_body"}:
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
