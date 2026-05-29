"""External-data enrichment step run between scraping and LLM analysis.

``enrich(cleaned)`` mutates the cleaned payload by attaching real工商 +
risk data under ``cleaned["external"]["qcc"]``. The downstream agents see
that key and switch their prompts to prefer real data over model recall.

Failures are recorded under ``external.qcc``. The CLI/API orchestration layer
decides whether a missing company anchor should block LLM analysis.

Caching: when a job posting carries a USCC (统一社会信用代码) that we've
already fetched within the TTL window, the QCC MCP calls are skipped and
the cached qcc_block is reused. See ``company_cache.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .company_cache import load_cached, save_cached
from .qcc_client import (
    ensure_initialized,
    fetch_company_pack,
    load_qcc_config,
    make_server,
)
from pipeline.industry_data import attach_industry_data

DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
USCC_RE = re.compile(r"^[0-9A-Z]{18}$")


def _valid_uscc(value: Any) -> str:
    uscc = (value or "").strip().upper() if isinstance(value, str) else ""
    return uscc if USCC_RE.fullmatch(uscc) else ""


def clean_qcc_payload(qcc: dict[str, Any] | None) -> dict[str, Any]:
    """Reduce the raw qcc block to cleaned sections for downstream agents."""
    qcc = qcc or {}
    company = qcc.get("company") or {}
    risk = qcc.get("risk") or {}
    operation = qcc.get("operation") or {}

    def _data(block: dict[str, Any], tool: str) -> Any:
        item = block.get(tool) or {}
        if not isinstance(item, dict):
            return None
        return item.get("data")

    cleaned: dict[str, Any] = {
        "registration_info": _data(company, "get_company_registration_info") or {},
        "shareholdinfo": _data(company, "get_shareholder_info") or {},
        "controller": _data(company, "get_actual_controller") or {},
        "investments": _data(company, "get_external_investments") or {},
        "risk": {
            "business_exception": _data(risk, "get_business_exception") or {},
            "administrative_penalty": _data(risk, "get_administrative_penalty") or {},
            "judgment_debtor_info": _data(risk, "get_judgment_debtor_info") or {},
            "dishonest_info": _data(risk, "get_dishonest_info") or {},
        },
        "operation": {
            "recruitment": _data(operation, "get_recruitment_info") or {},
            "honor": _data(operation, "get_honor_info") or {},
        },
    }
    return {k: v for k, v in cleaned.items() if v}


def has_qcc_config() -> bool:
    """Cheap probe used by main.py to decide whether to print the enrichment banner."""
    return load_qcc_config() is not None


def enrich(cleaned: dict[str, Any], *, data_root: Path | None = None) -> dict[str, Any]:
    """Attach qcc external data to ``cleaned`` if a config is present.

    The original ``cleaned`` dict is returned (mutated in place for callers
    that hold a reference).

    ``data_root`` is the base directory under which the company cache lives
    (``<data_root>/_company_cache/<USCC>.json``). Defaults to the project
    ``data/`` folder.
    """
    cache_root = data_root or DEFAULT_DATA_ROOT
    site_business_info = cleaned.setdefault("business_info", {})
    raw_site_uscc = (site_business_info.get("unified_social_credit_code") or "").strip()
    site_uscc = _valid_uscc(raw_site_uscc)
    site_company_name = (site_business_info.get("company_name") or "").strip()
    uscc_source = "job_site_business_info"
    if raw_site_uscc and not site_uscc:
        print(f"[external] 页面 USCC 无效，按未获取处理: {raw_site_uscc}")
        site_business_info.pop("unified_social_credit_code", None)

    if not site_uscc:
        cleaned.setdefault("external", {})["qcc"] = {
            "status": "uscc_unresolved",
            "note": "页面/公司页未提供有效统一社会信用代码，停止 QCC 数据整合。",
        }
        print("  [中断] 未取得有效统一社会信用代码，停止 QCC 数据整合")
        return cleaned

    # Cache fast-path: if we already have a USCC and a fresh cached pack, reuse
    # it without touching the QCC config / MCP.
    if site_uscc:
        cached = load_cached(cache_root, site_uscc)
        if cached is not None:
            print(f"[external] 命中公司缓存 USCC={site_uscc}，跳过 qcc MCP 调用")
            cached_block = dict(cached)
            cached_block["cache_hit"] = True
            cleaned.setdefault("external", {})["qcc"] = cached_block
            return cleaned

    config = load_qcc_config()
    if config is None:
        cleaned.setdefault("external", {})["qcc"] = {
            "status": "no_qcc_config",
            "anchor": {
                "企业名称": site_company_name,
                "统一社会信用代码": site_uscc,
                "source": uscc_source,
            },
            "note": "已取得统一社会信用代码，但缺少 QCC_AUTH_BEARER，无法进入 QCC 公司数据整合。",
        }
        return cleaned

    company_server = make_server("qcc-company", config)
    risk_server = make_server("qcc-risk", config)
    operation_server = make_server("qcc-operation", config)
    if company_server is None and risk_server is None:
        return cleaned

    external = cleaned.setdefault("external", {})
    qcc_block: dict[str, Any] = {"status": "pending"}
    external["qcc"] = qcc_block

    print("[external] 使用 USCC 查询 qcc 公司数据...")

    if not _valid_uscc(site_uscc):
        qcc_block["status"] = "uscc_unresolved"
        qcc_block["note"] = "未取得有效的 18 位统一社会信用代码，停止 QCC 数据整合。"
        print("  [中断] 未取得有效 USCC，停止 QCC / LLM 分析")
        return cleaned

    anchor = {
        "企业名称": site_company_name,
        "统一社会信用代码": site_uscc,
        "source": uscc_source,
    }
    resolution = {
        "status": "locked",
        "anchor": anchor,
        "candidates_tried": [site_uscc],
        "rounds": [],
        "source": anchor["source"],
    }
    qcc_block["resolution"] = resolution

    if company_server is None:
        qcc_block["status"] = "no_company_server"
        qcc_block["note"] = "缺少 qcc-company server，无法查询公司数据。"
        print("  [中断] 缺少 qcc-company server，停止 QCC / LLM 分析")
        return cleaned

    init_info = ensure_initialized(company_server)
    if "error" in init_info:
        qcc_block["status"] = "init_failed"
        qcc_block["error"] = init_info["error"]
        print(f"  [失败] qcc-company initialize: {init_info['error']}")
        return cleaned

    search_key = (anchor.get("统一社会信用代码") or anchor.get("企业名称") or "").strip()
    if not search_key:
        qcc_block["status"] = "no_search_key"
        print("  [跳过] 锚定结果缺少 USCC 与企业名称")
        return cleaned

    print(
        f"  [USCC] {anchor.get('企业名称') or '(职位站点未给公司名)'}  "
        f"USCC={anchor.get('统一社会信用代码')}"
    )

    pack = fetch_company_pack(
        company_server, risk_server, search_key,
        include_risk=True, operation_server=operation_server,
    )
    qcc_block["status"] = "ok"
    qcc_block["anchor"] = anchor
    qcc_block["search_key"] = search_key
    qcc_block["company"] = pack["company"]
    qcc_block["risk"] = pack["risk"]
    qcc_block["operation"] = pack["operation"]
    qcc_block["cleaned"] = clean_qcc_payload(qcc_block)
    qcc_block["cache_hit"] = False

    ok_company = sum(1 for r in pack["company"].values() if r.get("status") == "ok")
    ok_risk = sum(1 for r in pack["risk"].values() if r.get("status") == "ok")
    ok_operation = sum(1 for r in pack["operation"].values() if r.get("status") == "ok")
    print(
        f"  [完成] qcc 工商 {ok_company}/{len(pack['company'])} ok，"
        f"风险 {ok_risk}/{len(pack['risk'])} ok，"
        f"经营 {ok_operation}/{len(pack['operation'])} ok"
    )

    attach_industry_data(qcc_block)

    # Persist to cache for future runs.
    cache_uscc = (anchor.get("统一社会信用代码") or "").strip()
    if cache_uscc:
        save_cached(cache_root, cache_uscc, qcc_block)

    return cleaned
