"""Extract a company name from a scraped job page and resolve it via qcc.

Strategy:

1. Prefer the structured BOSS block ``工商信息`` → ``公司名称``.
2. Use the title shortname as a fallback only after a structured full name.
3. As a last resort, accept ``quick_fields.company`` only when it is already a
   full registered name.

We never补全 / 拼接 / 猜测; qcc does the matching.
"""

from __future__ import annotations

import re
from typing import Any

from .mcp_client import HttpMcpServer
from .qcc_client import resolve_company

# Strict whitelist of suffixes that qcc accepts as a complete name.
COMPANY_SUFFIXES: tuple[str, ...] = (
    "集团股份有限公司",
    "集团有限公司",
    "股份有限公司",
    "有限责任公司",
    "有限合伙企业",
    "普通合伙企业",
    "个人独资企业",
    "股份合作企业",
    "特殊普通合伙",
    "农民专业合作社联合社",
    "农民专业合作社",
    "联营企业",
    "全民所有制",
    "集体所有制",
    "外资企业",
    "合伙企业",
    "有限公司",
    "律师事务所",
)

# Ad / placeholder labels that招聘网站 sometimes puts in the company slot.
# We must NEVER feed these to qcc — they will either resolve to noise or
# fail spuriously.
_QUICK_FIELD_DENYLIST: tuple[str, ...] = (
    "热门企业",
    "知名企业",
    "知名公司",
    "知名互联网公司",
    "上市公司",
    "某大型互联网公司",
    "某知名公司",
    "某公司",
    "公司基本信息",
    "工商信息",
    "公司信息",
    "基本信息",
    "公司主页",
    "查看主页",
)

def _looks_like_full_name(s: str) -> bool:
    if not s:
        return False
    return any(s.endswith(suffix) for suffix in COMPANY_SUFFIXES)


def extract_company_candidates(cleaned: dict[str, Any]) -> list[str]:
    """Return ordered candidate strings to feed into qcc resolution.

    Priority:
      1. Structured company fields around ``工商信息`` / ``公司名称``
      2. Header/title shortnames from job or company pages.
      3. ``quick_fields.company`` only if it is a full registered name

    Duplicates and denylisted ads are filtered.
    """
    full_names: list[str] = []
    fallback_names: list[str] = []
    body = cleaned.get("body_text") or ""

    def add_candidate(value: str | None, bucket: list[str]) -> None:
        candidate = (value or "").strip()
        if not candidate:
            return
        if candidate in full_names or candidate in fallback_names or candidate in _QUICK_FIELD_DENYLIST:
            return
        if 3 <= len(candidate) <= 80:
            bucket.append(candidate)

    if isinstance(body, str) and body:
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            if line == "公司名称" and idx > 0 and "工商信息" in lines[max(0, idx - 5):idx]:
                if idx + 1 < len(lines) and _looks_like_full_name(lines[idx + 1]):
                    add_candidate(lines[idx + 1], full_names)
            if line == "公司基本信息" and idx + 1 < len(lines):
                add_candidate(lines[idx + 1], fallback_names)

    title = cleaned.get("page_title") or (cleaned.get("quick_fields") or {}).get("title")
    if isinstance(title, str):
        for pattern in (
            r"_([^_]+?)招聘-BOSS直聘",
            r"「(.+?)招聘」.*?招聘信息-BOSS直聘",
        ):
            title_match = re.search(pattern, title)
            if title_match:
                add_candidate(title_match.group(1), fallback_names)
                break

    quick = cleaned.get("quick_fields") or {}
    quick_company = (quick.get("company") or "").strip() if isinstance(quick.get("company"), str) else ""
    if _looks_like_full_name(quick_company):
        add_candidate(quick_company, full_names)

    return full_names + fallback_names


def resolve_from_cleaned(
    cleaned: dict[str, Any],
    company_server: HttpMcpServer,
) -> dict[str, Any]:
    """Run the full resolution pipeline. Returns a resolution payload.

    Output shape::

        {
            "status": "locked" | "ambiguous" | "no_candidate" | "all_failed",
            "anchor": {"企业名称": ..., "统一社会信用代码": ...} | None,
            "candidates_tried": [...],
            "rounds": [{"query": ..., "candidates": [...]}, ...]
        }
    """
    candidates = extract_company_candidates(cleaned)
    if not candidates:
        return {
            "status": "no_candidate",
            "anchor": None,
            "candidates_tried": [],
            "rounds": [],
            "note": "页面里未找到符合 qcc 白名单后缀的完整公司名。",
        }

    rounds: list[dict[str, Any]] = []
    locked: dict[str, Any] | None = None
    for query in candidates:
        attempt = resolve_company(company_server, query)
        rounds.append(
            {
                "query": query,
                "status": attempt.get("status"),
                "candidates": attempt.get("candidates"),
                "auto_locked": attempt.get("auto_locked"),
                "error": attempt.get("message"),
            }
        )
        if attempt.get("status") == "ok" and attempt.get("auto_locked"):
            locked = attempt["auto_locked"]
            break
        # Even with multiple candidates, if the first match is an exact name
        # we treat it as locked. qcc returns ordered candidates with the best
        # match first.
        if attempt.get("status") == "ok" and attempt.get("candidates"):
            first = attempt["candidates"][0]
            if isinstance(first, dict):
                first_name = (first.get("企业名称") or "").strip()
                if first_name and first_name == query:
                    locked = first
                    break

    if locked:
        return {
            "status": "locked",
            "anchor": locked,
            "candidates_tried": candidates,
            "rounds": rounds,
        }

    # If we tried every candidate and got nothing, fall back to "all_failed"
    # if every call errored, or "ambiguous" if we got back results we couldn't auto-pick.
    all_errored = all(r.get("status") == "error" for r in rounds)
    return {
        "status": "all_failed" if all_errored else "ambiguous",
        "anchor": None,
        "candidates_tried": candidates,
        "rounds": rounds,
    }
