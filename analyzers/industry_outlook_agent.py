"""Sub-agent: industry / business outlook analysis.

This agent reasons from the LLM's *training-time knowledge* about the
industry the posting belongs to. It is NOT a real-time web search — every
substantive claim must be marked with a ``信息来源`` field so the user can
see whether the conclusion came from page text or from model recall, and
weigh it accordingly.

Future work: this agent is structured so an external data fetcher (web
search / Wind / Crunchbase) can be slotted in as a pre-step and merged
into the ``外部数据`` field.
"""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

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


def build_industry_outlook_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="评估行业与赛道前景")
    system_prompt = (
        "你是熟悉中国市场的行业研究助手。"
        "你的判断来自训练时积累的公开知识，不能联网获取实时数据，因此严禁编造具体的`年增长率`、`市场规模`数字、"
        "`政策文号`、`融资金额`这类容易过时的精确数据。可以使用方向性判断如`快速增长`、`稳健增长`、`存量博弈`、`需求收缩`等。"
        "只输出JSON对象，不要输出多余文本。每个判断都要在 `信息来源` 字段标注是 `页面原文`/`模型常识`/`未知`。"
    )
    user_static = (
        "请基于职位页面里能识别的行业和你训练时积累的通用知识，输出JSON："
        "`行业识别`、`行业格局`、`趋势与驱动`、`风险与逆风`、`短期前景_3年`、`长期前景_5_10年`、`数据可信度`、`汇总要点`。"

        "—— 字段说明 ——"

        "`行业识别`为对象，包含以下键："
        "`一级行业`(如`互联网/AI`、`金融/银行`、`电商`、`新能源`、`半导体`、`医疗器械`、`K12 教育`、`制造业` 等)、"
        "`细分赛道`(更具体的子行业，如`AI Agent 应用`、`跨境电商`、`SaaS`)、"
        "`公司在赛道中的位置`(`头部`/`腰部`/`长尾`/`新入局`/`数据不足`)、"
        "`信息来源`(`页面原文`/`模型常识`/`未知` 其一)、"
        "`判断依据`(一句话引用页面里的公司名/产品名/客户名等线索)。"

        "`行业格局`为对象，包含以下键："
        "`阶段`(`萌芽期`/`快速增长`/`成长期`/`成熟期`/`衰退期`/`数据不足` 其一)、"
        "`竞争激烈度`(`蓝海`/`一般竞争`/`激烈红海`/`垄断格局`/`数据不足`)、"
        "`头部玩家`(字符串数组，最多4个，可列出训练时已知的代表性公司；不知道填 `[]`)、"
        "`信息来源`(同上三档)。"

        "`趋势与驱动`为对象，包含以下键："
        "`核心驱动`(字符串数组，最多4条，方向性描述，如`大模型成本下降`、`内容消费下沉`、`产业政策支持`)、"
        "`技术变化`(字符串数组，最多3条)、"
        "`政策环境`(`明显利好`/`中性`/`存在收紧风险`/`明显利空`/`数据不足` 其一)、"
        "`信息来源`(同上三档)。"

        "`风险与逆风`为对象，包含以下键："
        "`行业级风险`(字符串数组，最多4条，如`监管收紧`、`同质化加剧`、`资本退潮`、`需求侧疲软`)、"
        "`公司在该行业的特定风险`(字符串数组，最多3条，需结合 `行业识别.公司在赛道中的位置`)、"
        "`信息来源`(同上三档)。"

        "`短期前景_3年`为对象，包含以下键："
        "`方向判断`(`明显向好`/`稳健向好`/`震荡`/`明显走弱`/`数据不足` 其一)、"
        "`理由`(一句话，必须方向性，禁止编造具体数字)、"
        "`信息来源`(同上三档)。"

        "`长期前景_5_10年`为对象，包含以下键："
        "`方向判断`(`战略机会`/`稳健`/`存在不确定性`/`长期承压`/`数据不足` 其一)、"
        "`理由`(一句话)、"
        "`信息来源`(同上三档)。"

        "`数据可信度`为对象，包含以下键："
        "`整体可信度`(`高`/`中`/`低` 其一，反映本次行业判断的把握度)、"
        "`局限性说明`(一句话，例如`基于训练时知识，可能未反映最新政策变化`)、"
        "`建议用户补充`(字符串数组，最多3条，告诉用户去哪些渠道核实，如`查 Wind / 同花顺看最新行业数据`、"
        "`查工信部 / 国务院近期政策文件`、`查竞品融资动态`)。"

        "`汇总要点`为长度不超过300字的字符串，给最终汇总用，需突出短期/长期方向判断和最重要的 1-2 条风险。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_industry_outlook(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_industry_outlook_messages(cleaned),
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
        "input": agent_input_context(cleaned, focus_hint="评估行业与赛道前景"),
    }
