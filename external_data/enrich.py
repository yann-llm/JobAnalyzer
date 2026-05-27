"""External-data enrichment step run between scraping and LLM analysis.

``enrich(cleaned)`` mutates the cleaned payload by attaching real工商 +
risk data under ``cleaned["external"]["qcc"]``. The downstream agents see
that key and switch their prompts to prefer real data over model recall.

Failures are non-fatal — if anything goes wrong, the cleaned dict is
returned with an ``error`` field under ``external.qcc`` and the pipeline
proceeds with model-only analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .company_resolver import resolve_from_cleaned
from .qcc_client import (
    ensure_initialized,
    fetch_company_pack,
    load_qcc_config,
    make_server,
)


def has_qcc_config(path: str | Path | None = None) -> bool:
    """Cheap probe used by main.py to decide whether to print the enrichment banner."""
    return load_qcc_config(path) is not None


def enrich(cleaned: dict[str, Any], *, config_path: str | Path | None = None) -> dict[str, Any]:
    """Attach qcc external data to ``cleaned`` if a config is present.

    The original ``cleaned`` dict is returned (mutated in place for callers
    that hold a reference).
    """
    config = load_qcc_config(config_path)
    if config is None:
        return cleaned

    company_server = make_server("qcc-company", config)
    risk_server = make_server("qcc-risk", config)
    if company_server is None and risk_server is None:
        return cleaned

    external = cleaned.setdefault("external", {})
    qcc_block: dict[str, Any] = {"status": "pending"}
    external["qcc"] = qcc_block

    print("[external] 调用 qcc MCP 抓取真实工商 / 风险数据...")

    site_business_info = cleaned.get("business_info") or {}
    site_uscc = (site_business_info.get("unified_social_credit_code") or "").strip()
    site_company_name = (site_business_info.get("company_name") or "").strip()
    if site_uscc:
        anchor = {
            "企业名称": site_company_name,
            "统一社会信用代码": site_uscc,
            "source": "job_site_business_info",
        }
        resolution = {
            "status": "locked",
            "anchor": anchor,
            "candidates_tried": [site_uscc],
            "rounds": [],
            "source": "job_site_business_info",
        }
        qcc_block["resolution"] = resolution
    else:
        if company_server is None:
            qcc_block["status"] = "no_company_server"
            qcc_block["note"] = "qcc_config 缺少 qcc-company server，且招聘站点未提供统一社会信用代码，跳过实体锚定。"
            return cleaned
        # MCP servers in stateless mode don't actually need initialize, but doing
        # it once surfaces auth / network errors early before the parallel calls.
        init_info = ensure_initialized(company_server)
        if "error" in init_info:
            qcc_block["status"] = "init_failed"
            qcc_block["error"] = init_info["error"]
            print(f"  [失败] qcc-company initialize: {init_info['error']}")
            return cleaned
        resolution = resolve_from_cleaned(cleaned, company_server)
        qcc_block["resolution"] = resolution
        if resolution.get("status") != "locked":
            qcc_block["status"] = resolution.get("status") or "unresolved"
            print(f"  [跳过] 未能锚定唯一企业实体 (status={qcc_block['status']})")
            return cleaned
        anchor = resolution["anchor"]

    search_key = (anchor.get("统一社会信用代码") or anchor.get("企业名称") or "").strip()
    if not search_key:
        qcc_block["status"] = "no_search_key"
        print("  [跳过] 锚定结果缺少 USCC 与企业名称")
        return cleaned

    print(
        f"  [锚定] {anchor.get('企业名称') or '(职位站点未给公司名)'}  "
        f"USCC={anchor.get('统一社会信用代码')}"
    )

    pack = fetch_company_pack(company_server, risk_server, search_key, include_risk=True)
    qcc_block["status"] = "ok"
    qcc_block["anchor"] = anchor
    qcc_block["search_key"] = search_key
    qcc_block["company"] = pack["company"]
    qcc_block["risk"] = pack["risk"]

    ok_company = sum(1 for r in pack["company"].values() if r.get("status") == "ok")
    ok_risk = sum(1 for r in pack["risk"].values() if r.get("status") == "ok")
    print(
        f"  [完成] qcc 工商 {ok_company}/{len(pack['company'])} ok，"
        f"风险 {ok_risk}/{len(pack['risk'])} ok"
    )
    return cleaned
