"""Helpers shared by all job-analysis sub-agents."""

from __future__ import annotations

import json
import re
from typing import Any

from llm import cached_text, text_block

# Trim per-agent inputs so we never blow past the context window. The current
# persisted cleaned data is compact, but descriptions can still be long.
MAX_BODY_TEXT_FOR_AGENT = 12_000
MAX_SECTION_CHARS_FOR_AGENT = 6_000

_JOB_FIELDS = (
    "职位名称",
    "薪资",
    "职位工作地点",
    "要求年限",
    "学历要求",
    "工作地址",
)

_JOB_SCOPE_FIELDS: dict[str, tuple[str, ...]] = {
    "job_value": ("职位名称", "薪资", "职位工作地点", "要求年限", "学历要求", "工作地址"),
    "company_risk": (),
    "industry_outlook": ("职位名称", "职位工作地点"),
}

_COMPANY_INFO_CN_TO_QCC_REG = {
    "公司名称": "企业名称",
    "统一社会信用代码": "统一社会信用代码",
    "法定代表人": "法定代表人",
    "成立日期": "成立日期",
    "企业类型": "企业类型",
    "经营状态": "登记状态",
    "注册资金": "注册资本",
}

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": ("职位描述", "岗位亮点", "岗位介绍", "招聘说明"),
    "responsibilities": ("岗位职责", "工作职责", "工作职责:", "工作职责："),
    "requirements": ("任职要求", "任职资格", "职位要求", "必须具备", "学历要求"),
    "bonus": ("加分项", "优先条件"),
    "compensation": ("岗位福利", "薪资待遇", "福利待遇", "薪酬福利", "工资待遇"),
    "work_intensity": ("工作时间", "加班说明", "工时", "班次", "出差", "值班", "Oncall"),
    "company": ("公司简介", "公司概况", "简介", "公司基本信息", "企业文化", "公司背景"),
    "legal": ("BOSS 安全提示", "BOSS安全提示", "安全提示", "合规提示", "免责声明"),
    "address": ("工作地址", "地址", "公司地址"),
    "other": ("更多职位", "查看全部", "推荐公司", "看过该职位的人还看了", "精选职位"),
}


def agent_input_context(
    cleaned: dict[str, Any],
    focus_hint: str | None = None,
    *,
    qcc_cleaned: dict[str, Any] | None = None,
    candidate_profile: dict[str, Any] | None = None,
    source_scope: str | None = None,
    external_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON context payload handed to a sub-agent.

    The current pipeline persists two cleaned files:

    * job cleaned data: top-level Chinese job fields plus ``职位描述``.
    * QCC cleaned data: registration / shareholders / controller /
      investments / risk.

    Agents receive only the job fields and description sections relevant to
    their scope. Company facts prefer QCC data; job-site ``工商信息`` is used
    only as a fallback when QCC is absent.

    When ``candidate_profile`` is provided, it is attached so agents that
    care about candidate-fit can personalize their output.

    When ``external_data`` is provided (e.g., from Tavily), it is attached
    for agents that need real-time web data (e.g., industry_outlook).
    """
    scope = source_scope or ""
    qcc_cleaned = qcc_cleaned or _extract_qcc_cleaned(cleaned)
    job_info = _select_job_info(cleaned, scope)
    company_info = _build_company_info(cleaned, qcc_cleaned, scope)
    body_text = _body_text_from_job(cleaned)
    body_text, truncated = _truncate_text(body_text, MAX_BODY_TEXT_FOR_AGENT)

    sections = _split_sections(body_text)
    selected_sections = _select_sections(sections, source_scope or "")
    selected_sections = _trim_sections(selected_sections)
    context: dict[str, Any] = {
        "url": cleaned.get("url"),
        "final_url": cleaned.get("final_url"),
        "focus": focus_hint,
        "company": company_info,
        "body_truncated": truncated,
    }
    if job_info or selected_sections:
        context["job"] = {
            "source": "cleaned.json",
            "fields": job_info,
            "sections": selected_sections,
        }

    if candidate_profile:
        context["candidate_profile"] = candidate_profile
    if external_data:
        context["external_data"] = external_data
    return context


def _extract_qcc_cleaned(cleaned: dict[str, Any]) -> dict[str, Any]:
    if isinstance(cleaned.get("qcc_cleaned"), dict):
        return cleaned["qcc_cleaned"]
    if isinstance(cleaned.get("company_qcc"), dict):
        return cleaned["company_qcc"]
    external = cleaned.get("external")
    if isinstance(external, dict):
        qcc = external.get("qcc")
        if isinstance(qcc, dict) and isinstance(qcc.get("cleaned"), dict):
            return qcc["cleaned"]
    return {}


def _select_job_info(cleaned: dict[str, Any], scope: str) -> dict[str, Any]:
    fields = _JOB_SCOPE_FIELDS.get(scope, _JOB_FIELDS)
    return {field: cleaned.get(field) for field in fields if cleaned.get(field) not in (None, "")}


def _build_company_info(cleaned: dict[str, Any], qcc_cleaned: dict[str, Any], scope: str) -> dict[str, Any]:
    if scope not in {"company_risk", "industry_outlook"}:
        return {}
    if qcc_cleaned:
        return _select_qcc_company_info(qcc_cleaned, scope)
    return {
        "source": "job_cleaned_fallback",
        "registration_info": _qcc_registration_from_job_business_info(cleaned.get("工商信息")),
    }


def _select_qcc_company_info(qcc_cleaned: dict[str, Any], scope: str) -> dict[str, Any]:
    registration = qcc_cleaned.get("registration_info") if isinstance(qcc_cleaned.get("registration_info"), dict) else {}
    company: dict[str, Any] = {
        "source": "qcc_cleaned",
        "registration_info": _select_registration_info(registration, scope),
    }
    if scope == "company_risk":
        for key in ("shareholdinfo", "controller", "investments", "risk", "operation"):
            value = qcc_cleaned.get(key)
            if value:
                company[key] = value
    elif scope == "industry_outlook":
        company["industry_fields"] = {
            key: registration.get(key)
            for key in ("国标行业", "经营范围", "企业类型", "人员规模")
            if registration.get(key) not in (None, "")
        }
    return company


def _select_registration_info(registration: dict[str, Any], scope: str) -> dict[str, Any]:
    if scope == "industry_outlook":
        keys = ("企业名称", "国标行业", "经营范围", "企业类型", "人员规模")
    else:
        return registration
    return {key: registration.get(key) for key in keys if registration.get(key) not in (None, "")}


def _qcc_registration_from_job_business_info(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    registration: dict[str, Any] = {}
    for job_key, qcc_key in _COMPANY_INFO_CN_TO_QCC_REG.items():
        if value.get(job_key) not in (None, ""):
            registration[qcc_key] = value[job_key]
    if value.get("公司详情页"):
        registration["公司详情页"] = value["公司详情页"]
    return registration


def _body_text_from_job(cleaned: dict[str, Any]) -> str:
    body_text = cleaned.get("body_text")
    if isinstance(body_text, str) and body_text.strip():
        return body_text.strip()

    parts: list[str] = []
    description = cleaned.get("职位描述")
    if description not in (None, ""):
        parts.append(f"职位描述\n{description}")
    address = cleaned.get("工作地址")
    if address not in (None, ""):
        parts.append(f"工作地址\n{address}")
    return "\n\n".join(parts)


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _trim_sections(sections: dict[str, list[str]]) -> dict[str, list[str]]:
    trimmed: dict[str, list[str]] = {}
    for key, values in sections.items():
        text = "\n".join(values)
        text, _ = _truncate_text(text, MAX_SECTION_CHARS_FOR_AGENT)
        trimmed[key] = [line for line in text.splitlines() if line.strip()]
    return trimmed


def _normalize_line(text: str) -> str:
    return re.sub(r"[\s:：;；]+$", "", re.sub(r"\s+", "", text or ""))


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
    if source_scope == "job_value":
        keys = ("overview", "responsibilities", "requirements", "bonus", "compensation", "work_intensity", "address")
    elif source_scope == "company_risk":
        keys = ()
    elif source_scope == "industry_outlook":
        keys = ("overview", "company")
    else:
        keys = tuple(sections.keys())
    if not keys:
        return {}
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
