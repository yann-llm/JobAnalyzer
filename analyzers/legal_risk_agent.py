"""Sub-agent: surface labor/legal/compliance risks from a job posting.

This agent only produces *preliminary* hints based on the page text. The
output always carries a disclaimer reminding the user to consult a real
lawyer before acting on anything sensitive.
"""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "legal_risk"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "整体风险等级",
    "劳动合同关注点",
    "公司合规信号",
    "行业监管要求",
    "建议追问的问题",
    "免责声明",
    "汇总要点",
)


def build_legal_risk_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="预警劳动法/合规风险", source_scope="legal_risk")
    system_prompt = (
        "你是熟悉中国劳动法与招聘合规的辅助分析助手。"
        "你只做**初步提示**，不提供法律意见，不替代专业律师。"
        "输入可能包含 `external.qcc` 企查查工商/风险数据；若存在且 status 为 ok，"
        "公司经营异常、司法风险、行政处罚等合规信号必须优先使用这些外部数据。"
        "你只关注劳动合同、社保、公积金、押金、培训费、加班补偿和监管合规，不重复公司画像或财务健康。"
        "请只使用 `sections.legal`、`sections.compensation`、`sections.work_intensity`、`business_info` 和 `external.qcc`。"
        "所有结论必须基于输入数据，禁止编造法条具体条文号或具体仲裁案件编号。"
        "只输出JSON对象，不要输出多余文本。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`整体风险等级`、`劳动合同关注点`、`公司合规信号`、`行业监管要求`、"
        "`建议追问的问题`、`免责声明`、`汇总要点`。"

        "—— 字段说明 ——"

        "`整体风险等级`为对象，包含以下键："
        "`星级`(`★☆☆☆☆`-`★★★★★`，星越多风险越高)、"
        "`等级`(`基本无风险`/`存在疑点`/`需重点核实`/`高风险，谨慎`/`数据不足`其一)、"
        "`一句话总结`(必须引用文本里出现的关键词，禁止泛泛而谈)。"
        "评级口径："
        "★ 无任何疑点；"
        "★★ 仅常规法定福利缺一类描述；"
        "★★★ 有未明确的合同条款（如未提加班补偿、未提试用期）；"
        "★★★★ 出现要求押金 / 培训费 / 自带设备 / 模糊的违约金；"
        "★★★★★ 文本含明显违规暗示（拒绝缴纳社保、长期未缴公积金、性别/年龄歧视等）。"

        "`劳动合同关注点`为字符串数组，最多 6 条；逐条提示需要核实的条款，"
        "例如`合同未提加班工资计算基数`、`未明确试用期长度与转正条件`、`未说明违约金条款`、"
        "`未说明保密/竞业限制范围`、`未说明知识产权归属`、`需确认岗位等级与职级体系`。"
        "若文本足以判断某条款合规，可输出`合同条款看起来合规`并附理由；无明显疑点填 `[]`。"

        "`公司合规信号`为对象，包含以下键："
        "`五险一金`(`明确缴纳`/`仅提及未说明基数`/`未提及`/`存在违规暗示`其一)、"
        "`公积金`(同上四档)、"
        "`其他合规信号`(字符串数组，如`要求押金`、`要求培训费`、`要求自带设备`、`要求体检报销由员工承担`、`公开承诺合规`，无填 `[]`)、"
        "`关键原文`(字符串数组，最多3条原样引用页面里关于五险一金/合规承诺/费用要求的句子；"
        "若来自 `external.qcc`，引用对应风险摘要并标注`（企查查）`)。"

        "`行业监管要求`为对象，先判断岗位所属强监管行业，再给出对应提示，包含以下键："
        "`所属强监管行业`(如`金融`、`医疗`、`教育(K12)`、`保险`、`证券`、`房产中介`、"
        "`涉外`、`互联网内容安全`、`无明显强监管` 其一)、"
        "`合规要点`(字符串数组，每条简短，根据所属行业列出岗位需要关注的资质或合规要求；"
        "若`所属强监管行业`为`无明显强监管`则填 `[]`)。"
        "示例：金融岗 → `反洗钱(AML)合规`、`从业资格证`；"
        "医疗岗 → `执业医师资格`、`处方权范围`；"
        "K12 教培岗 → `双减政策下学科类培训限制`、`教师资格证`；"
        "证券岗 → `证券从业资格`、`内幕信息隔离`。"

        "`建议追问的问题`为字符串数组，最多 5 条，给候选人在 offer 沟通或面试中可以追问的具体问题，"
        "每条必须可回答（如`五险一金缴纳基数是按月薪全额还是按当地最低基数？`、"
        "`加班工资计算基数是基本工资还是综合工资？`、`试用期是否压一个月工资？`）。"
        "不要泛泛输出`建议咨询律师`这类无操作性的话。"

        "`免责声明`必须固定为以下文本："
        "`本节为基于公开招聘页面文本的初步合规提示，不构成法律意见。涉及劳动合同、社保公积金、违约金等具体争议，请以正式合同文本为准，并在必要时咨询专业律师或当地人社部门。`"

        "`汇总要点`为长度不超过250字的字符串，用于最终汇总，须按以下结构组织："
        "整体风险等级（含星级）→ 最关键的 1-2 条关注点 → 是否属于强监管行业及对应资质提醒。"
        "保留触发风险判断的页面原文关键词。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_legal_risk(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_legal_risk_messages(cleaned),
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
        "input": agent_input_context(cleaned, focus_hint="预警劳动法/合规风险", source_scope="legal_risk"),
    }
