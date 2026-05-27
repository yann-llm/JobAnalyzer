"""Fetch real-time industry data via Tavily search API."""

from __future__ import annotations

import os
from typing import Any

import requests


TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def fetch_industry_data(
    company_name: str,
    business_description: str | None = None,
    *,
    max_results: int = 5,
) -> dict[str, Any]:
    """Fetch real-time industry data for a company.

    Returns dict with keys: industries, summary, raw_results, query.
    If no reliable data is found, returns industries=[] with no error.
    On network failure returns dict with an 'error' key.
    """
    api_key = os.getenv(TAVILY_API_KEY_ENV)
    if not api_key:
        return {"industries": [], "summary": "", "raw_results": [], "error": "TAVILY_API_KEY not set"}

    query = f"{company_name} 主营业务 行业"
    if business_description:
        query += f" {business_description[:80]}"

    try:
        resp = requests.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "include_answer": True,
                "max_results": max_results,
                "include_raw_content": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"industries": [], "summary": "", "raw_results": [], "error": str(e)}

    # Validate: check if any result actually mentions the target company.
    relevant_results = _filter_relevant_results(company_name, data)
    if not relevant_results:
        # No direct match in web results. Surface Tavily's AI answer
        # as a reference hint (may involve parent/sister companies).
        result: dict[str, Any] = {
            "industries": [],
            "raw_results": data.get("results", []),
            "query": query,
        }
        answer = (data.get("answer") or "").strip()
        if answer:
            result["summary"] = f"[可能相关] {answer}"
            result["note"] = "未找到该企业直接信息，以下为可能关联的企业或同名企业信息"
        else:
            result["summary"] = ""
            result["note"] = f"搜索结果中未找到与「{company_name}」相关的信息"
        return result

    industries = _extract_industries(company_name, relevant_results)
    return {
        "industries": industries,
        "summary": relevant_results.get("answer", ""),
        "raw_results": relevant_results.get("results", []),
        "query": query,
    }


def _filter_relevant_results(company_name: str, tavily_data: dict[str, Any]) -> dict[str, Any] | None:
    """Filter Tavily results to only those mentioning the exact company.

    Returns a filtered tavily_data dict, or None if nothing is relevant.
    Only trusts actual web page results (not Tavily's AI-generated answer,
    which may hallucinate company details from unrelated sources).
    """
    core = _extract_core_name(company_name)
    if not core:
        return None

    # Only check actual search results, NOT the AI-generated answer.
    # Tavily's answer often parrots the query company name even when
    # the underlying results are about a different entity.
    relevant = []
    for r in tavily_data.get("results", []):
        title = r.get("title", "")
        content = r.get("content", "")
        text = f"{title} {content}"
        if core in text:
            relevant.append(r)

    if not relevant:
        return None

    # Only include the answer if we have at least one relevant result
    # (the answer is likely grounded in those results).
    filtered: dict[str, Any] = {"results": relevant}
    answer = tavily_data.get("answer", "")
    if answer:
        filtered["answer"] = answer
    return filtered


def _extract_core_name(company_name: str) -> str:
    """Extract the distinctive part of a company name for matching.

    '新余易米品牌管理有限责任公司' → '新余易米品牌管理'
    '字节跳动科技有限公司' → '字节跳动科技'
    """
    suffixes = ("有限责任公司", "股份有限公司", "有限公司", "集团公司", "集团")
    name = company_name
    for s in suffixes:
        if name.endswith(s):
            name = name[: -len(s)]
            break
    return name.strip()


def _extract_industries(company_name: str, filtered_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Use LLM to classify industries from verified search results."""
    from llm import chat_json

    snippets = []
    if filtered_data.get("answer"):
        snippets.append(filtered_data["answer"])
    for r in filtered_data.get("results", [])[:5]:
        if r.get("content"):
            snippets.append(r["content"][:200])

    if not snippets:
        return []

    combined = "\n".join(snippets[:2000])
    messages = [
        {
            "role": "system",
            "content": (
                "根据搜索结果识别公司所在行业及侧重度。"
                "严格基于搜索结果中的事实，不要编造或推测。"
                "如果搜索结果信息不足以判断行业，返回空数组。"
                "返回JSON: {\"industries\": [{\"name\": \"行业名\", \"weight\": 0.6, \"keywords\": [...]}]}。"
                "按weight降序，weight范围0-1。"
            ),
        },
        {"role": "user", "content": f"公司: {company_name}\n\n搜索结果:\n{combined}"},
    ]

    try:
        result = chat_json(messages, response_format={"type": "json_object"}, temperature=0.2)
        return result.get("industries", [])
    except Exception:
        return []

