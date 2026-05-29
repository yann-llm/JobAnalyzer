"""Company page scraping used to enrich job-site business fields."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from pipeline.company_data import valid_uscc
from pipeline.job_data import ProgressCallback, emit_progress
from scraper import ScraperError, clean_job_page, fetch_job_page, find_business_detail_url_for_page
from external_data.uscc_lookup import lookup_uscc_by_company_name


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
    if valid_uscc(business_info.get("unified_social_credit_code")):
        return cleaned
    if business_info.get("unified_social_credit_code"):
        business_info["company_detail_fetch_error"] = "职位页统一社会信用代码无效"
        business_info.pop("unified_social_credit_code", None)

    company_url = (business_info.get("company_detail_url") or "").strip()
    if not company_url:
        business_info["company_detail_fetch_error"] = "职位页未提供公司详情页，无法抓取统一社会信用代码"
    else:
        seen_urls: set[str] = set()
        next_url: str | None = company_url
        for _attempt in range(1, 3):
            if not next_url or next_url in seen_urls or business_info.get("unified_social_credit_code"):
                break
            seen_urls.add(next_url)
            print(f"[抓取] 公司工商详情页: {next_url}")
            emit_progress(progress_callback, "scraping_company", "抓取公司详情页", 42, detail="start")
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
                print(f"[失败] 公司详情页抓取失败：{exc}")
                break

            company_cleaned = clean_job_page(company_page)
            company_info = company_cleaned.get("business_info") or {}
            for key, value in company_info.items():
                if value and not business_info.get(key):
                    business_info[key] = value
            business_info["company_detail_url"] = company_page.final_url or next_url
            business_info["company_detail_fetched_at"] = company_page.fetched_at

            live_detail_url = find_business_detail_url_for_page(company_page, port=port)
            next_url = live_detail_url if live_detail_url and live_detail_url not in seen_urls else None

    if not valid_uscc(business_info.get("unified_social_credit_code")):
        company_name = _company_name_for_lookup(cleaned)
        if company_name:
            print(f"[查询] 公司详情页未抓到 USCC，尝试 Tavily 查询: {company_name}")
            emit_progress(progress_callback, "scraping_company", "通过公司名称查询统一社会信用代码", 47, detail="tavily_uscc_lookup")
            lookup = lookup_uscc_by_company_name(company_name)
            business_info["uscc_lookup"] = {
                key: value
                for key, value in lookup.items()
                if key not in {"raw_results"}
            }
            if lookup.get("status") == "ok" and valid_uscc(lookup.get("uscc")):
                resolved_company_name = (lookup.get("resolved_company_name") or lookup.get("company_name") or company_name).strip()
                business_info["company_name"] = resolved_company_name
                business_info["unified_social_credit_code"] = valid_uscc(lookup.get("uscc"))
                business_info["unified_social_credit_code_source"] = "tavily"
                business_info["company_detail_fetch_error"] = None
                print(
                    f"  [完成] Tavily 查询到 经营主体={resolved_company_name} "
                    f"USCC={business_info['unified_social_credit_code']}"
                )
                return cleaned
            print(f"  [未命中] Tavily 未查询到有效 USCC: {lookup.get('status')}")
            print(
                "  [调试] Tavily 查询结果: "
                + json.dumps(business_info["uscc_lookup"], ensure_ascii=False, indent=2)
            )

    if not valid_uscc(business_info.get("unified_social_credit_code")):
        business_info["company_detail_fetch_error"] = "公司详情页和 Tavily 均未抓取到有效统一社会信用代码"

    return cleaned


def _company_name_for_lookup(cleaned: dict[str, Any]) -> str:
    business_info = cleaned.get("business_info") if isinstance(cleaned.get("business_info"), dict) else {}
    page_content = cleaned.get("page_content") if isinstance(cleaned.get("page_content"), dict) else {}
    quick_fields = cleaned.get("quick_fields") if isinstance(cleaned.get("quick_fields"), dict) else {}
    candidates = (
        (page_content.get("工商信息") or {}).get("公司名称") if isinstance(page_content.get("工商信息"), dict) else None,
        business_info.get("company_name"),
        business_info.get("company_header_name"),
        quick_fields.get("company"),
    )
    for value in candidates:
        company_name = (value or "").strip() if isinstance(value, str) else ""
        if company_name:
            return company_name
    return ""
