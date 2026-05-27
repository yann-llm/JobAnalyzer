"""Sub-agent: industry / business outlook analysis.

Supports multi-industry analysis with real-time web data via Tavily.
Each industry is analyzed separately with its own outlook assessment.
"""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages
from external_data.industry_fetcher import fetch_industry_data

MODULE_NAME = "industry_outlook"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "行业识别",
    "行业格局",
    "趋势与驱动",
    "风险与逆风",
    "短期前景_3年",
    "长期前景_5_10年",
    "数据可信度",
    "汇总要点",
)

MULTI_INDUSTRY_EXPECTED_KEYS = (
    "行业分布",
    "主要行业分析",
    "综合评估",
)


def build_industry_outlook_messages(
    cleaned: dict[str, Any],
    *,
    qcc_cleaned: dict[str, Any] | None = None,
    external_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="评估行业与赛道前景",
        source_scope="industry_outlook",
        qcc_cleaned=qcc_cleaned,
        external_data=external_data,
    )
    system_prompt = (
        "你是熟悉中国市场的行业研究助手。"
        "你的判断来自训练时积累的公开知识和实时网页数据。"
        "严禁编造具体的`年增长率`、`市场规模`数字、`政策文号`、`融资金额`这类容易过时的精确数据。"
        "可以使用方向性判断如`快速增长`、`稳健增长`、`存量博弈`、`需求收缩`等。"
        "你只分析赛道和行业，不分析公司财务、劳动合规或具体薪酬福利。"
        "请只使用 `job.fields`、`job.sections.overview`、`job.sections.company`、"
        "`company.registration_info` / `company.industry_fields` 和 `external_data`。"
        "只输出JSON对象，不要输出多余文本。每个判断都要在 `信息来源` 字段标注是 `页面原文`/`模型常识`/`网页查询`/`未知`。"
    )
    user_static = (
        "请基于职位页面、企查查数据和实时网页查询结果，分析公司所在行业。"
        "如果公司涉及多个行业，请按侧重度依次列出，对每个行业分别分析。"
        "输出JSON，包含以下顶层键："
        "`行业分布`、`主要行业分析`、`综合评估`。"

        "—— 字段说明 ——"

        "`行业分布`为对象数组，每个元素包含："
        "`行业名`(如`AI/大模型`、`云计算`、`SaaS`)、"
        "`侧重度`(0-1之间的数字，表示公司在该行业的业务占比)、"
        "`关键词`(字符串数组，该行业的核心业务关键词)、"
        "`信息来源`(`页面原文`/`模型常识`/`网页查询`/`未知` 其一)。"
        "按侧重度降序排列。"

        "`主要行业分析`为对象数组，对侧重度最高的 1-3 个行业分别分析，每个元素包含："
        "`行业名`、"
        "`行业识别`(对象，包含`一级行业`、`细分赛道`、`公司在赛道中的位置`、`信息来源`、`判断依据`)、"
        "`行业格局`(对象，包含`阶段`、`竞争激烈度`、`头部玩家`、`信息来源`)、"
        "`趋势与驱动`(对象，包含`核心驱动`、`技术变化`、`政策环境`、`信息来源`)、"
        "`风险与逆风`(对象，包含`行业级风险`、`公司在该行业的特定风险`、`信息来源`)、"
        "`短期前景_3年`(对象，包含`方向判断`、`理由`、`信息来源`)、"
        "`长期前景_5_10年`(对象，包含`方向判断`、`理由`、`信息来源`)。"

        "`综合评估`为对象，包含："
        "`整体可信度`(`高`/`中`/`低`)、"
        "`多行业风险`(字符串数组，如`行业间协同不足`、`主业竞争加剧`等)、"
        "`建议用户补充`(字符串数组，最多3条)、"
        "`汇总要点`(不超过300字)。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_industry_outlook(
    cleaned: dict[str, Any],
    *,
    qcc_cleaned: dict[str, Any] | None = None,
    fetch_external_data: bool = True,
) -> dict[str, Any]:
    """Analyze industry outlook with optional real-time web data.

    Args:
        cleaned: Cleaned job posting data
        qcc_cleaned: QCC company registration data (may include industry_data from enrich step)
        fetch_external_data: Whether to fetch real-time data via Tavily if not cached
    """
    # Prefer cached industry_data from enrich step.
    external_data = None
    if qcc_cleaned:
        external_data = qcc_cleaned.get("industry_data")

    # Fallback: fetch live if not cached.
    if not external_data and fetch_external_data and qcc_cleaned:
        company_name = qcc_cleaned.get("registration_info", {}).get("企业名称")
        if company_name:
            external_data = fetch_industry_data(company_name)

    analysis = chat_json(
        build_industry_outlook_messages(cleaned, qcc_cleaned=qcc_cleaned, external_data=external_data),
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        temperature=0.3,
        expected_keys=MULTI_INDUSTRY_EXPECTED_KEYS,
    )
    return {
        "module": MODULE_NAME,
        "url": cleaned.get("url"),
        "model": MODEL_NAME,
        "analysis": analysis,
        "external_data": external_data,
        "input": agent_input_context(
            cleaned,
            focus_hint="评估行业与赛道前景",
            source_scope="industry_outlook",
            qcc_cleaned=qcc_cleaned,
            external_data=external_data,
        ),
    }
