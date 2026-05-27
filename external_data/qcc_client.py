"""Thin wrappers over MCP calls to qcc-company / qcc-risk / qcc-operation.

The free functions here return Python dicts that downstream code can drop
straight into ``cleaned["external"]["qcc"]``. All functions tolerate
errors — they return ``{"status": "error", "message": "..."}`` instead of
raising, so partial failures (e.g. risk MCP down, company MCP up) still
let the pipeline run.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .mcp_client import HttpMcpServer, McpError, call_tool, initialize

QCC_COMPANY_URL = "https://agent.qcc.com/mcp/company/stream"
QCC_RISK_URL = "https://agent.qcc.com/mcp/risk/stream"
QCC_OPERATION_URL = "https://agent.qcc.com/mcp/operation/stream"
QCC_AUTH_BEARER_ENV = "QCC_AUTH_BEARER"
QCC_TIMEOUT_SECONDS = 60

COMPANY_TOOLS = (
    "get_company_registration_info",
    "get_shareholder_info",
    "get_actual_controller",
    "get_external_investments",
)
RISK_TOOLS = (
    "get_business_exception",
    "get_administrative_penalty",
    "get_judgment_debtor_info",
    "get_dishonest_info",
)
OPERATION_TOOLS = (
    "get_recruitment_info",
    "get_honor_info",
)


def load_qcc_config() -> dict[str, Any] | None:
    """Build QCC MCP config from environment variables.

    Returns None when QCC_AUTH_BEARER is not set.
    """
    bearer = os.getenv(QCC_AUTH_BEARER_ENV)
    if not bearer:
        return None
    return {
        "timeout_seconds": QCC_TIMEOUT_SECONDS,
        "servers": {
            "qcc-company": {"url": QCC_COMPANY_URL, "auth_bearer": bearer},
            "qcc-risk": {"url": QCC_RISK_URL, "auth_bearer": bearer},
            "qcc-operation": {"url": QCC_OPERATION_URL, "auth_bearer": bearer},
        },
    }


def make_server(name: str, config: dict[str, Any]) -> HttpMcpServer | None:
    """Build an HttpMcpServer from the config payload's ``servers.<name>`` entry."""
    server_conf = config.get("servers", {}).get(name)
    if not isinstance(server_conf, dict):
        return None
    url = server_conf.get("url")
    token = server_conf.get("auth_bearer")
    if not url:
        return None
    timeout = float(config.get("timeout_seconds") or server_conf.get("timeout") or 60)
    return HttpMcpServer(name=name, url=url, auth_bearer=token, timeout=timeout)


def _safe_call(server: HttpMcpServer, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call ``tool`` on ``server`` and return a normalized result envelope."""
    try:
        result = call_tool(server, tool, args)
    except McpError as exc:
        return {"status": "error", "tool": tool, "message": str(exc)}
    if result.get("is_error"):
        return {
            "status": "error",
            "tool": tool,
            "message": "tool returned isError=true",
            "raw": result.get("parsed"),
        }
    payload = result.get("parsed") if result.get("parsed") is not None else result.get("structured")
    return {"status": "ok", "tool": tool, "data": payload}


def resolve_company(server: HttpMcpServer, raw_query: str) -> dict[str, Any]:
    """Run ``get_company_by_query`` to anchor the entity.

    Returns ``{"status": "...", "candidates": [...], "auto_locked": {...}|None}``.

    Following the qcc rules strictly: we hand the user's raw string straight
    to ``get_company_by_query`` and let qcc decide. Never补全 / 拼接 / 猜测.

    The qcc tool returns one of these shapes:

      * Unique match: ``{"匹配结果":"唯一精确匹配", "企业信息":{...}}``
      * Multi candidate: ``{"匹配结果":[{...},{...}]}`` (list of candidate dicts)
      * No match: ``{"匹配结果":"未匹配"}`` (or similar)
    """
    res = _safe_call(server, "get_company_by_query", {"searchKey": raw_query})
    if res.get("status") != "ok":
        return {"status": "error", "message": res.get("message"), "query": raw_query}

    data = res.get("data") or {}
    candidates: list[dict[str, Any]] = []
    auto_locked: dict[str, Any] | None = None

    if isinstance(data, dict):
        match_result = data.get("匹配结果")
        # Shape 1: unique match — 企业信息 is a single dict
        single = data.get("企业信息")
        if isinstance(single, dict) and single.get("企业名称"):
            auto_locked = single
            candidates = [single]
        # Shape 2: list of candidates under 匹配结果 / 候选企业 / 候选列表
        elif isinstance(match_result, list):
            candidates = [c for c in match_result if isinstance(c, dict)]
        else:
            for key in ("候选企业", "候选列表", "结果", "candidates", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates = [c for c in value if isinstance(c, dict)]
                    break
        # Shape 3: caller already gave a full identifier — top-level dict IS the result
        if not auto_locked and not candidates and "企业名称" in data and "统一社会信用代码" in data:
            auto_locked = data
            candidates = [data]
    elif isinstance(data, list):
        candidates = [c for c in data if isinstance(c, dict)]

    if auto_locked is None and len(candidates) == 1:
        auto_locked = candidates[0]

    return {
        "status": "ok",
        "query": raw_query,
        "candidates": candidates,
        "auto_locked": auto_locked,
        "raw": data,
    }


def fetch_company_pack(
    company_server: HttpMcpServer | None,
    risk_server: HttpMcpServer | None,
    search_key: str,
    *,
    include_risk: bool = True,
    operation_server: HttpMcpServer | None = None,
) -> dict[str, Any]:
    """Fetch the standard pack of company + risk + operation facts in parallel.

    ``search_key`` should be a 18-digit USCC or a complete registration name
    that ends with a whitelisted suffix. Caller is responsible for ensuring
    that — typically by going through ``resolve_company`` first.
    """
    company_results: dict[str, Any] = {}
    risk_results: dict[str, Any] = {}
    operation_results: dict[str, Any] = {}

    jobs: list[tuple[str, str, HttpMcpServer]] = []
    if company_server:
        jobs.extend(("company", tool, company_server) for tool in COMPANY_TOOLS)
    if risk_server and include_risk:
        jobs.extend(("risk", tool, risk_server) for tool in RISK_TOOLS)
    if operation_server:
        jobs.extend(("operation", tool, operation_server) for tool in OPERATION_TOOLS)

    if not jobs:
        return {"company": company_results, "risk": risk_results, "operation": operation_results}

    with ThreadPoolExecutor(max_workers=min(12, len(jobs))) as pool:
        future_to_meta = {
            pool.submit(_safe_call, srv, tool, {"searchKey": search_key}): (bucket, tool)
            for (bucket, tool, srv) in jobs
        }
        for future in as_completed(future_to_meta):
            bucket, tool = future_to_meta[future]
            try:
                envelope = future.result()
            except Exception as exc:  # noqa: BLE001
                envelope = {"status": "error", "tool": tool, "message": f"{type(exc).__name__}: {exc}"}
            if bucket == "company":
                company_results[tool] = envelope
            elif bucket == "risk":
                risk_results[tool] = envelope
            else:
                operation_results[tool] = envelope

    return {"company": company_results, "risk": risk_results, "operation": operation_results}


def ensure_initialized(server: HttpMcpServer) -> dict[str, Any]:
    """Run the MCP initialize handshake. Best-effort; logs but does not raise."""
    try:
        return initialize(server)
    except McpError as exc:
        return {"error": str(exc)}
