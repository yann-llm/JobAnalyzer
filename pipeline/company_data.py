"""Company data readiness and failure handling for the analysis pipeline."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.job_data import ProgressCallback, emit_progress, isoformat, write_json

USCC_RE = re.compile(r"^[0-9A-Z]{18}$")


def valid_uscc(value: Any) -> str:
    uscc = (value or "").strip().upper() if isinstance(value, str) else ""
    return uscc if USCC_RE.fullmatch(uscc) else ""


def qcc_uscc(qcc: dict[str, Any] | None) -> str:
    if not isinstance(qcc, dict):
        return ""
    anchor = qcc.get("anchor") or {}
    if isinstance(anchor, dict):
        uscc = valid_uscc(anchor.get("统一社会信用代码"))
        if uscc:
            return uscc
    return valid_uscc(qcc.get("search_key"))


def company_ready_for_analysis(qcc: dict[str, Any] | None) -> bool:
    return bool(isinstance(qcc, dict) and qcc.get("status") == "ok" and qcc_uscc(qcc))


def company_error_detail(qcc: dict[str, Any] | None) -> str:
    status = qcc.get("status") if isinstance(qcc, dict) else None
    if status in {"uscc_unresolved", "no_company_name"}:
        return "company_uscc_unresolved"
    if status in {"no_company_server", "init_failed"}:
        return "company_info_failed"
    return "company_info_failed"


def company_error_percent(qcc: dict[str, Any] | None) -> int:
    status = qcc.get("status") if isinstance(qcc, dict) else None
    if status in {"uscc_unresolved", "no_company_name"}:
        return 42
    return 55


def company_failure_result(
    url: str,
    generated_at: datetime,
    base_dir: Path,
    page: Any,
    cleaned: dict[str, Any],
    qcc: dict[str, Any],
    body_len: int,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    message = "获取公司信息失败，未取得有效统一社会信用代码或公司数据查询失败，已停止后续流程。"
    print(f"[中断] {message}")
    emit_progress(progress_callback, "error", message, company_error_percent(qcc), detail=company_error_detail(qcc))
    write_json(base_dir / "company.json", {
        "status": qcc.get("status", "unknown"),
        "error": qcc.get("error"),
        "note": qcc.get("note") or "公司数据未成功获取，无缓存可引用",
    })
    summary = {
        "url": url,
        "generated_at": isoformat(generated_at),
        "output_dir": str(base_dir),
        "stage": "company_enrich",
        "status": "company_info_error",
        "final_url": page.final_url,
        "body_chars": body_len,
        "message": message,
        "company_enrichment": {
            "status": qcc.get("status", "not_configured"),
            "search_key": qcc.get("search_key"),
            "anchor": qcc.get("anchor"),
            "error": qcc.get("error"),
            "note": qcc.get("note"),
        },
        "analysis": {
            "status": "blocked",
            "candidate_profile_used": False,
        },
    }
    return {
        "summary": summary,
        "cleaned": cleaned,
        "analysis": None,
    }
