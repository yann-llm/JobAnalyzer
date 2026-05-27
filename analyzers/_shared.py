"""Helpers shared by all job-analysis sub-agents."""

from __future__ import annotations

import json
import re
from typing import Any

from llm import cached_text, text_block

# Trim per-agent inputs so we never blow past the context window even on
# unusually long postings. Each agent only consumes the fields it cares about
# plus a slice of the body text.
MAX_BODY_TEXT_FOR_AGENT = 12_000

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": ("职位描述", "岗位亮点", "岗位介绍", "公司简介", "公司概况", "简介", "招聘说明"),
    "responsibilities": ("岗位职责", "工作职责", "职位描述"),
    "requirements": ("任职要求", "职位要求", "必须具备", "加分项", "学历要求"),
    "compensation": ("薪资待遇", "福利待遇", "薪酬福利", "工资待遇"),
    "work_intensity": ("工作时间", "加班说明", "工时", "班次", "出差", "值班", "Oncall"),
    "company": ("公司简介", "公司基本信息", "企业文化", "工商信息", "公司背景"),
    "legal": ("BOSS 安全提示", "BOSS安全提示", "安全提示", "合规提示", "免责声明"),
    "address": ("工作地址", "地址", "公司地址"),
    "other": ("更多职位", "查看全部", "推荐公司", "看过该职位的人还看了", "精选职位"),
}


def agent_input_context(
    cleaned: dict[str, Any],
    focus_hint: str | None = None,
    *,
    candidate_profile: dict[str, Any] | None = None,
    source_scope: str | None = None,
) -> dict[str, Any]:
    """Build the JSON context payload handed to a sub-agent.

    Keeps the input lean: title, quick-extracted fields, URL, and a body-text
    slice — every analyzer can still inspect the raw posting wording but the
    total prompt size stays bounded.

    When ``candidate_profile`` is provided, it is attached so agents that
    care about candidate-fit (requirements / compensation / work_intensity /
    final_evaluation) can personalize their output.
    """
    body_text = cleaned.get("body_text") or ""
    if isinstance(body_text, str) and len(body_text) > MAX_BODY_TEXT_FOR_AGENT:
        body_text = body_text[:MAX_BODY_TEXT_FOR_AGENT]
        truncated = True
    else:
        truncated = bool(cleaned.get("body_truncated"))

    sections = _split_sections(body_text)
    selected_sections = _select_sections(sections, source_scope or "")
    context: dict[str, Any] = {
        "url": cleaned.get("url"),
        "final_url": cleaned.get("final_url"),
        "page_title": cleaned.get("page_title"),
        "body_excerpt": _compose_section_excerpt(selected_sections),
        "body_truncated": truncated,
        "focus": focus_hint,
    }

    if source_scope in {"basic_info", "requirements", "compensation", "work_intensity"}:
        context["quick_fields"] = cleaned.get("quick_fields") or {}
    if source_scope in {"company", "company_finance", "legal_risk", "industry_outlook", "basic_info"}:
        context["business_info"] = cleaned.get("business_info") or {}
    if source_scope in {"company", "company_finance", "legal_risk", "industry_outlook"}:
        external = cleaned.get("external") or {}
        qcc = external.get("qcc") if isinstance(external, dict) else {}
        context["external"] = {"qcc": qcc} if qcc else {}
    if source_scope in {"basic_info", "responsibilities", "requirements", "compensation", "company", "work_intensity", "legal_risk", "industry_outlook", "company_finance"}:
        context["sections"] = selected_sections
    if candidate_profile:
        context["candidate_profile"] = candidate_profile
    return context


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _split_sections(body_text: str) -> dict[str, list[str]]:
    lines = [line.strip() for line in (body_text or "").splitlines()]
    sections: dict[str, list[str]] = {"general": []}
    current = "general"
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        normalized = _normalize_line(line)
        matched = None
        for section_name, aliases in _SECTION_ALIASES.items():
            if normalized in {_normalize_line(alias) for alias in aliases}:
                matched = section_name
                break
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {name: values for name, values in sections.items() if values}


def _select_sections(sections: dict[str, list[str]], source_scope: str) -> dict[str, list[str]]:
    if not sections:
        return {}
    if source_scope == "basic_info":
        keys = ("general", "address", "company")
    elif source_scope == "responsibilities":
        keys = ("responsibilities", "overview")
    elif source_scope == "requirements":
        keys = ("requirements", "overview")
    elif source_scope == "compensation":
        keys = ("compensation", "work_intensity", "overview")
    elif source_scope == "company":
        keys = ("company", "overview", "address")
    elif source_scope == "work_intensity":
        keys = ("work_intensity", "compensation", "overview")
    elif source_scope == "legal_risk":
        keys = ("legal", "compensation", "work_intensity", "company")
    elif source_scope == "industry_outlook":
        keys = ("overview", "company")
    elif source_scope == "company_finance":
        keys = ("company", "legal", "overview")
    else:
        keys = tuple(sections.keys())
    selected = {key: sections[key] for key in keys if key in sections}
    if not selected:
        selected = {"general": sections.get("general", [])}
    return selected


def _compose_section_excerpt(selected_sections: dict[str, list[str]]) -> str:
    if not selected_sections:
        return ""
    parts: list[str] = []
    for key, values in selected_sections.items():
        if not values:
            continue
        parts.append(f"[{key}]\n" + "\n".join(values))
    text = "\n\n".join(parts)
    if len(text) > MAX_BODY_TEXT_FOR_AGENT:
        return text[:MAX_BODY_TEXT_FOR_AGENT]
    return text


def build_messages(
    *,
    system_prompt: str,
    user_static: str,
    user_dynamic_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the [system, user] message pair used by every sub-agent.

    ``user_static`` is wrapped in ``cached_text`` so Anthropic providers can
    reuse it across runs; OpenAI-compatible providers receive the flattened
    string transparently (see ``llm._flatten_message_for_openai``).
    """
    user_dynamic = json.dumps(user_dynamic_payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [cached_text(user_static), text_block(user_dynamic)],
        },
    ]
