"""Industry lookup attachment for company QCC blocks."""

from __future__ import annotations

from typing import Any


def attach_industry_data(qcc_block: dict[str, Any]) -> None:
    """Fetch industry data via Tavily and attach it to a successful qcc block."""
    anchor = qcc_block.get("anchor") or {}
    company_name = (anchor.get("企业名称") or "").strip()
    if not company_name:
        return

    from external_data.industry_fetcher import fetch_industry_data

    print(f"  [行业] 通过 Tavily 获取行业数据: {company_name}")
    industry_data = fetch_industry_data(company_name)
    qcc_block["industry_data"] = industry_data
    if industry_data.get("error"):
        print(f"  [行业] 获取失败（不影响主流程）: {industry_data['error'][:80]}")
    else:
        print(f"  [行业] 识别到 {len(industry_data.get('industries', []))} 个行业")
