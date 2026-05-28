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
    "行业评分",
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
        "`行业分布`、`主要行业分析`、`行业评分`、`综合评估`。"

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

        "`行业评分`为对象，对公司主营行业（侧重度最高的那个）做整体评分，必须含："
        "`分数`(0-100整数，越高代表行业前景越好越值得进入)、"
        "`星级`(`★☆☆☆☆`-`★★★★★`，0-39一星，40-54二星，55-69三星，70-84四星，85-100五星)、"
        "`等级`(`衰退`/`成熟饱和`/`稳健`/`快速成长`/`战略机会`/`数据不足` 其一)、"
        "`title`(一句结论性短句，10-20字)、"
        "`text`(1-3句分析正文，必须基于 主要行业分析 的判断)、"
        "`kpis`(对象数组，正好4项，每项含 `label`/`val`/`sub`/`source` 四个字段)。"
        "评分口径：快速成长且竞争未充分、政策利好 → 高分；衰退或重监管 → 低分；数据不足时谨慎给中位分。"

        "—— KPI 输出严格要求 ——"
        "1. `kpis` 必须正好 4 项；"
        "2. `label` ≤ 8 字；"
        "3. `val` 必须是「关键值」：方向词或级别词，如 `快速增长`、`稳健`、`战略机会`、`红海`、`数据不足`；"
        "4. `sub` 必须是补充说明，按以下优先级填："
        "  (a) `主要行业分析` 中的判断依据短引用（例：`AI 工具链快速迭代，需求未饱和`）；"
        "  (b) `external_data.summary` 网页摘要短引用（例：`Tavily：跨境电商 2024 年增长承压`）；"
        "  (c) 客观限定（例：`基于训练时数据，2024 后政策可能变化`）；"
        "  (d) 没有任何依据时，老实写 `输入未提供`；"
        "禁止编造（不得出现：年增长率 X%、市场规模 N 亿、Wind 数据、艾瑞 N 等具体数字，除非数字真实出现在 external_data 里）；"
        "5. `source` 只能从白名单选：`Tavily` / `网页查询` / `模型常识` / `LLM推断`；"
        "若来自 external_data 的网页摘要选 `Tavily` 或 `网页查询`，纯方向性判断选 `LLM推断` 或 `模型常识`。"

        "推荐 `行业评分.kpis` 4 项（val 是关键值，sub 是判断依据短引用）："
        "`{label:'行业阶段', val:'萌芽期/快速增长/成熟期/衰退期/数据不足', sub:'引用 行业格局.阶段 的依据短句', source:'LLM推断' 或 'Tavily'}`、"
        "`{label:'短期方向', val:'明显向好/稳健/震荡/走弱/数据不足', sub:'引用 短期前景_3年.理由 短句', source:'LLM推断'}`、"
        "`{label:'长期方向', val:'战略机会/稳健/不确定/承压/数据不足', sub:'引用 长期前景_5_10年.理由 短句', source:'LLM推断'}`、"
        "`{label:'竞争激烈度', val:'蓝海/一般/红海/垄断/数据不足', sub:'引用 行业格局.头部玩家 或 风险与逆风 的短句', source:'LLM推断' 或 'Tavily'}`。"

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
