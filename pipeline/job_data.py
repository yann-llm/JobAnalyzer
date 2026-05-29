"""Job page scraping, cleaned job fields, and run artifact helpers."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent.parent
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
