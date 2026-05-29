"""LLM-assisted USCC lookup for companies missing a credit code.

The scraper calls this module only after the job/company pages fail to provide
an effective unified social credit code. This fallback intentionally does not
perform direct query heuristics itself: it gives Tavily to the LLM as a tool and
asks the model to search, reason over the evidence, and return one structured
company anchor.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from llm import get_llm_config, get_openai_client, parse_llm_json
from pipeline.company_data import valid_uscc

TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_TOOL_ROUNDS = 6
DEFAULT_TAVILY_RESULTS = 5


def lookup_uscc_by_company_name(company_name: str, *, max_results: int = DEFAULT_TAVILY_RESULTS, allow_short_name: bool = False) -> dict[str, Any]:
    """Use an LLM with a Tavily tool to resolve a missing company USCC.

    ``allow_short_name`` is kept for call-site compatibility. The LLM prompt
    handles both legal company names and brand/short names.
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return {"status": "no_company_name", "note": "缺少公司名称，无法查询统一社会信用代码"}

    tavily_api_key = os.getenv(TAVILY_API_KEY_ENV)
    if not tavily_api_key:
        return {"status": "no_api_key", "note": "TAVILY_API_KEY not set"}

    try:
        config = get_llm_config()
    except Exception as exc:  # noqa: BLE001
        return {"status": "no_llm_config", "company_name": company_name, "error": str(exc)}

    if config.provider != "openai":
        return {
            "status": "llm_tool_unsupported",
            "company_name": company_name,
            "error": f"LLM Tavily tool lookup currently requires openai-compatible provider, got {config.provider}",
        }

    return _run_llm_tavily_lookup(
        company_name,
        tavily_api_key=tavily_api_key,
        max_results=max_results,
    )


def _run_llm_tavily_lookup(company_name: str, *, tavily_api_key: str, max_results: int) -> dict[str, Any]:
    config = get_llm_config()
    client = get_openai_client()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt()},
        {
            "role": "user",
            "content": (
                f"待查询公司名：{company_name}\n"
                "请调用 tavily_search 查询经营主体全称和统一社会信用代码。"
            ),
        },
    ]
    tool_results: list[dict[str, Any]] = []

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            completion = _create_completion(client, config.model, messages, config.timeout)
            message = completion.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if not tool_calls:
                parsed = parse_llm_json(message.content or "")
                print("[调试] LLM Tavily 最终返回: " + _json_dumps(parsed))
                return _normalize_llm_result(company_name, parsed, tool_results)

            messages.append(_assistant_tool_call_message(message, tool_calls))
            for call in tool_calls:
                payload = _execute_tavily_tool_call(call.function.arguments, tavily_api_key, max_results)
                tool_results.append(payload)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _json_dumps(payload),
                })

        payload = {
            "status": "not_found",
            "company_name": company_name,
            "tool_results": tool_results,
            "note": "LLM Tavily 工具调用达到轮次上限，未返回最终 JSON",
        }
        print("[调试] LLM Tavily 未返回最终 JSON: " + _json_dumps(payload))
        return payload
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "error",
            "company_name": company_name,
            "error": f"{type(exc).__name__}: {exc}",
            "tool_results": tool_results,
        }
        print("[调试] LLM Tavily 调用失败: " + _json_dumps(payload))
        return payload


def _system_prompt() -> str:
    return (
        "你是企业工商主体锚定助手。你可以调用 tavily_search 搜索网页。"
        "任务：根据职位页抓到的公司名，找出最可信的经营主体全称和统一社会信用代码。"
        "如果输入是品牌简称，必须先查询并判断经营主体全称，再查询该主体的统一社会信用代码。"
        "不要选择分公司、子公司、管理咨询公司、已注销、吊销、撤销、迁出或清算企业，"
        "除非用户输入本身就是这些实体的完整名称。"
        "高置信依据优先级：官网/招聘页主体说明、企查查/天眼查/爱企查等工商页、多个来源一致。"
        "最终必须只返回 JSON，不要 Markdown。JSON 字段固定为："
        "status(ok/not_found), input_company_name, resolved_company_name, uscc, "
        "confidence(high/medium/low), reason, sources。"
        "sources 是数组，每项包含 title/url/evidence。"
        "无法高置信锚定时返回 status=not_found，uscc 为空，并在 reason 说明原因。"
    )


def _create_completion(client: Any, model: str, messages: list[dict[str, Any]], timeout: float) -> Any:
    request = {
        "model": model,
        "messages": messages,
        "tools": [_tavily_tool_schema()],
        "tool_choice": "auto",
        "temperature": 0,
        "timeout": timeout,
    }
    try:
        return client.chat.completions.create(
            **request,
            response_format={"type": "json_object"},
        )
    except Exception:
        return client.chat.completions.create(**request)


def _tavily_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": "Search the web through Tavily and return answer plus result snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "description": "Maximum result count, 1-10."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


def _assistant_tool_call_message(message: Any, tool_calls: list[Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ],
    }


def _execute_tavily_tool_call(arguments: str, api_key: str, default_max_results: int) -> dict[str, Any]:
    args = parse_llm_json(arguments or "{}")
    query = str(args.get("query") or "").strip()
    max_results = args.get("max_results")
    if not isinstance(max_results, int):
        max_results = default_max_results
    max_results = max(1, min(10, max(max_results, default_max_results)))
    if not query:
        return {"status": "error", "error": "missing query"}

    try:
        data = _tavily_search(api_key, query, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "query": query, "error": str(exc)}

    return {
        "status": "ok",
        "query": query,
        "answer": _truncate(str(data.get("answer") or ""), 1500),
        "results": [
            {
                "title": str(result.get("title") or ""),
                "url": str(result.get("url") or ""),
                "content": _truncate(str(result.get("content") or ""), 1500),
            }
            for result in data.get("results", []) or []
        ],
    }


def _tavily_search(api_key: str, query: str, *, max_results: int) -> dict[str, Any]:
    response = requests.post(
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
    response.raise_for_status()
    return response.json()


def _normalize_llm_result(company_name: str, parsed: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    status = str(parsed.get("status") or "").strip().lower()
    resolved_company_name = str(parsed.get("resolved_company_name") or parsed.get("company_name") or "").strip()
    uscc = valid_uscc(parsed.get("uscc"))
    sources = parsed.get("sources") if isinstance(parsed.get("sources"), list) else []

    if status == "ok" and resolved_company_name and uscc:
        return {
            "status": "ok",
            "company_name": resolved_company_name,
            "input_company_name": company_name,
            "resolved_company_name": resolved_company_name,
            "uscc": uscc,
            "query": "llm_tavily_tool",
            "source": "LLM Tavily tool",
            "confidence": parsed.get("confidence"),
            "reason": parsed.get("reason"),
            "sources": sources,
            "raw_llm_result": parsed,
            "tool_results": tool_results,
        }

    return {
        "status": "not_found",
        "company_name": company_name,
        "input_company_name": company_name,
        "resolved_company_name": resolved_company_name,
        "uscc": uscc,
        "confidence": parsed.get("confidence"),
        "reason": parsed.get("reason") or "LLM 未返回高置信经营主体和有效 USCC",
        "sources": sources,
        "raw_llm_result": parsed,
        "tool_results": tool_results,
    }


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text[:limit]


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
