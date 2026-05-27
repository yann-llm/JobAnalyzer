"""Sub-agent: extract candidate requirements (skills, experience, education)."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "requirements"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("硬性要求", "加分项", "软技能", "学历经验", "汇总要点")


def build_requirement_messages(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="提取候选人要求与门槛",
        candidate_profile=candidate_profile,
        source_scope="requirements",
    )
    system_prompt = (
        "你是专业的招聘信息分析助手，擅长区分岗位的硬性门槛与加分项。"
        "你只分析候选人要求，不分析薪资、公司背景、行业前景或法律风险。"
        "请只使用 `sections.requirements`、`sections.overview`、`quick_fields` 和可选的 `candidate_profile`。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`硬性要求`、`加分项`、`软技能`、`学历经验`、`汇总要点`。"
        "字段说明："
        "`硬性要求`为字符串数组，列出必须满足的技能、证书、经验、行业背景等门槛；最多12条。"
        "`加分项`为字符串数组，列出文中明确标注为优先/加分/Nice to have的能力或经验；最多10条。"
        "`软技能`为字符串数组，提取沟通、团队合作、抗压、领导力等非技术能力要求；最多8条。"
        "`学历经验`为对象，包含`最低学历`、`偏好学历`、`最低经验年限`、`偏好经验年限`、`行业背景`五个键；"
        "经验年限以阿拉伯数字字符串表示（如`3`、`5-7`、`应届`），缺失填null。"
        "`汇总要点`为长度不超过300字的字符串，用于最终汇总，需保留关键的硬性条件。"
        "区分硬/软原则：用`必须`、`要求`、`需要`、`不少于`、`X年以上`描述的为硬性；用`优先`、`加分`、`熟悉`、`了解`描述的为加分项；"
        "若同一条同时出现两类信号，按更严格的硬性归类。"

        "—— 如果输入里附带 candidate_profile，额外增加一个字段 `候选人匹配度` ——"
        "`候选人匹配度`为对象，包含以下键："
        "`满足项`(字符串数组，从`硬性要求`中挑出候选人 skills/basic/career_goals 里能对得上的)、"
        "`欠缺项`(字符串数组，候选人未提及或明显不满足的硬性要求)、"
        "`加分项命中`(字符串数组，候选人能命中的加分项)、"
        "`匹配等级`(`高匹配`/`基本匹配`/`部分匹配`/`不匹配`/`数据不足`其一)、"
        "`一句话总结`(必须引用具体的候选人技能或缺口词，禁止泛化表达)。"
        "判断时引用 candidate_profile.skills / basic.学历 / basic.工作年限 / career_goals 等字段；"
        "禁止编造候选人没有的技能。若没有 candidate_profile，则不输出此字段。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_requirements(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = chat_json(
        build_requirement_messages(cleaned, candidate_profile=candidate_profile),
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
        "input": agent_input_context(
            cleaned,
            focus_hint="提取候选人要求与门槛",
            candidate_profile=candidate_profile,
            source_scope="requirements",
        ),
    }
