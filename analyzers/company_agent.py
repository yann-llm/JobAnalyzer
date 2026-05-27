"""Sub-agent: profile the hiring company and team context."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "company"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("公司画像", "团队信息", "发展阶段与背景", "潜在风险", "汇总要点")


def build_company_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="刻画公司与团队背景")
    system_prompt = (
        "你是专业的招聘信息分析助手，擅长从职位文本里推断公司画像与团队背景。"
        "输入可能包含 `external.qcc` 企查查工商/风险数据；若存在且 status 为 ok，"
        "公司名称、工商状态、注册资本、成立时间、经营风险等公司事实必须优先使用这些外部数据，"
        "再用页面原文补充团队和岗位上下文。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入或可由输入直接推断。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`公司画像`、`团队信息`、`发展阶段与背景`、`潜在风险`、`汇总要点`。"

        "—— 字段说明 ——"

        "`公司画像`为对象，包含`公司名称`、`所属行业`、`主营业务`、`规模`、`公司性质`(国企/民营/外企/创业等)、`官网或介绍链接`六个键，缺失填null。"

        "`团队信息`为对象，包含`所在团队`、`团队规模`、`汇报对象`、`团队亮点`四个键，缺失填null。"

        "`发展阶段与背景`为对象，包含`融资阶段`、`融资金额或估值`、`重要客户或合作方`、`知名度信号`(如`已上市`、`独角兽`、`头部企业`等关键词)四个键。"

        "`潜在风险`为对象，按四类分桶；每个桶的值为字符串数组，每条都要保留触发该风险的页面原文片段或数字。无信号填空数组。"
        "若风险来自 `external.qcc`，保留对应工商/风险字段或数字，并在句末标注`（企查查）`。"
        "包含以下键："
        "`财务风险`(如`刚成立公司`、`注册资金极低`、`经营异常`、`未提及融资来源`)、"
        "`业务风险`(如`赛道竞争激烈`、`项目处于早期`、`业务模式未跑通`、`单一大客户依赖`)、"
        "`管理风险`(如`要求长期加班`、`管理层频繁变动`、`汇报关系模糊`、`要求自带设备/培训费/押金`)、"
        "`法律合规风险`(如`合同条款未明确加班工资基数`、`公司有未足额缴纳社保/公积金记录`、`涉及强监管行业但未提资质`)。"
        "若该桶无相关信号，必须填空数组 `[]`，不要省略键。"

        "`汇总要点`为长度不超过250字的字符串，用于最终汇总，需保留行业、规模、阶段等关键词，并提及最严重的 1-2 条风险。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_company(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_company_messages(cleaned),
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        temperature=0.2,
        expected_keys=EXPECTED_KEYS,
    )
    return {
        "module": MODULE_NAME,
        "url": cleaned.get("url"),
        "model": MODEL_NAME,
        "analysis": analysis,
        "input": agent_input_context(cleaned, focus_hint="刻画公司与团队背景"),
    }
