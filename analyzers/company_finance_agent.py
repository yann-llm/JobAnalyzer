"""Sub-agent: company financial / business health assessment.

This agent uses the job page plus any external company data attached under
``cleaned["external"]``. Every claim must be tagged with ``信息来源`` so the
user can distinguish page-grounded facts, QCC facts, and model recall. The
agent never invents specific revenue numbers, valuation figures, or financing
rounds.
"""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "company_finance"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "公司基础",
    "财务健康度",
    "融资与资本",
    "业务护城河",
    "管理与战略",
    "总体评级",
    "数据可信度",
    "汇总要点",
)


def build_company_finance_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="评估公司财务、资本与经营健康度", source_scope="company_finance")
    system_prompt = (
        "你是企业研究与尽调辅助助手。"
        "你的输入可能包含 `external.qcc` 企查查工商/风险数据；若存在且 status 为 ok，"
        "公司基础、工商状态、注册资本、成立时间、经营风险、司法/经营异常等事实必须优先使用这些外部数据。"
        "你不做行业前景判断、不做劳动法/社保公积金合规判断，也不重复页面中的团队介绍。"
        "请只使用 `business_info`、`external.qcc`、`sections.company`、`sections.legal` 和 `quick_fields`。"
        "缺少外部数据时，才可基于页面线索和训练时积累的公开知识做方向性判断。"
        "严禁编造具体的`营收数字`、`利润率`、`ROE`、`融资金额`、`估值`、`员工数`这类容易过时或不可验证的精确数据。"
        "可以使用方向性描述（如`营收快速增长`、`持续亏损`、`现金流紧张`、`已实现规模盈利`）。"
        "只输出JSON对象，不要输出多余文本。每个判断都要在 `信息来源` 字段标注是 `企查查`/`页面原文`/`模型常识`/`未知`。"
    )
    user_static = (
        "请基于职位页面里能识别的公司线索、`external.qcc`（若有）和你训练时积累的通用知识，输出JSON："
        "`公司基础`、`财务健康度`、`融资与资本`、`业务护城河`、`管理与战略`、`总体评级`、`数据可信度`、`汇总要点`。"

        "—— 字段说明 ——"

        "`公司基础`为对象，包含以下键："
        "`识别到的公司`(字符串)、`是否上市`(`A股上市`/`港股上市`/`美股上市`/`未上市`/`数据不足` 其一)、"
        "`大致成立年限`(`<3年`/`3-7年`/`7-15年`/`>15年`/`数据不足`)、"
        "`公司性质`(`国企央企`/`民营`/`外企`/`合资`/`创业团队`/`个体/自雇`/`数据不足` 其一)、"
        "`信息来源`(`企查查`/`页面原文`/`模型常识`/`未知`)、"
        "`判断依据`(一句话引用页面中的公司名、注册资金、官网链接等线索)。"

        "`财务健康度`为对象，包含以下键："
        "`营收态势`(`快速增长`/`稳健增长`/`持平`/`下滑`/`数据不足` 其一)、"
        "`盈利能力`(`规模盈利`/`微利`/`收支平衡`/`持续亏损`/`数据不足` 其一)、"
        "`现金流`(`充裕`/`正常`/`紧张`/`数据不足` 其一)、"
        "`偿债压力`(`无明显压力`/`中等`/`偏高`/`数据不足` 其一)、"
        "`信息来源`(同上四档)、"
        "`判断依据`(一句话，必须方向性，禁止编造具体数字)。"

        "`融资与资本`为对象，包含以下键："
        "`最近融资阶段`(如`未融资`/`天使`/`Pre-A`/`A`/`B`/`C+`/`Pre-IPO`/`已上市`/`数据不足`)、"
        "`资本认可度`(`一线VC背书`/`二线VC背书`/`产业资本/CVC`/`无明显认可`/`数据不足`)、"
        "`资金消耗速度`(`稳健`/`偏快`/`烧钱严重`/`数据不足` 其一)、"
        "`信息来源`(同上四档)。"

        "`业务护城河`为对象，包含以下键："
        "`护城河类型`(字符串数组，最多3条，可选 `技术壁垒`/`数据壁垒`/`网络效应`/`品牌`/`牌照资质`/`成本优势`/`渠道`/`无明显护城河`)、"
        "`市场地位`(`细分领域头部`/`头部追赶者`/`中游`/`长尾`/`新入局`/`数据不足`)、"
        "`差异化卖点`(字符串，一句话)、"
        "`信息来源`(同上四档)。"

        "`管理与战略`为对象，包含以下键："
        "`创始人/管理层背景`(字符串，一句话，可基于公开印象，禁止编造个人具体职位/履历)、"
        "`战略清晰度`(`清晰`/`一般`/`模糊`/`频繁切换`/`数据不足` 其一)、"
        "`扩张动作`(字符串数组，最多3条，如`国际化`、`新业务线`、`产业链整合`、`无明显扩张`)、"
        "`信息来源`(同上四档)。"

        "`总体评级`为对象，包含以下键："
        "`评级`(`A+`/`A`/`B+`/`B`/`C+`/`C`/`D` 其一；A 级=头部稳健，B 级=成长型，C 级=早期/承压，D 级=高风险)、"
        "`星级`(`★☆☆☆☆`-`★★★★★`五档，与评级对齐：D ★/C ★★/B ★★★/A ★★★★/A+ ★★★★★)、"
        "`一句话总结`(必须引用 `公司基础`、`财务健康度` 或 `融资与资本` 中的具体词)。"

        "`数据可信度`为对象，包含以下键："
        "`整体可信度`(`高`/`中`/`低` 其一)、"
        "`局限性说明`(一句话，例如`公司规模较小，公开信息有限，主要基于页面线索`)、"
        "`建议用户补充`(字符串数组，最多3条，告诉用户去哪些渠道核实，例如"
        "`查天眼查/企查查看工商和股东信息`、`查公司官网/招聘公众号`、`查公司客户/产品报道`)。"

        "`汇总要点`为长度不超过300字的字符串，给最终汇总用，需突出总体评级、最大优势、最大风险。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_company_finance(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_company_finance_messages(cleaned),
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        temperature=0.3,
        expected_keys=EXPECTED_KEYS,
    )
    return {
        "module": MODULE_NAME,
        "url": cleaned.get("url"),
        "model": MODEL_NAME,
        "analysis": analysis,
        "input": agent_input_context(cleaned, focus_hint="评估公司财务、资本与经营健康度", source_scope="company_finance"),
    }
