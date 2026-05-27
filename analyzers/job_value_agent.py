"""Sub-agent: unified job-side value, fit, compensation, and workload score."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "job_value"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "岗位画像",
    "维度评分",
    "职责与产出",
    "候选人要求",
    "薪酬福利",
    "工作强度",
    "机会与风险",
    "需要追问",
    "汇总要点",
)


def build_job_value_messages(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="综合评估职位职责、要求、薪酬福利与工作强度",
        candidate_profile=candidate_profile,
        source_scope="job_value",
    )
    system_prompt = (
        "你是专业的岗位分析助手。"
        "你把原先的岗位职责、候选人要求、薪酬福利、工作强度合并成一个职位侧综合判断。"
        "只使用输入中的 `job` 和可选的 `candidate_profile`，不要分析公司工商、股东、司法风险或行业前景。"
        "所有判断必须基于职位清洗数据；缺失信息要标注`数据不足`，不得编造。"
        "只输出JSON对象，不要输出多余文本。"
    )
    user_static = (
        "请阅读下面的职位清洗数据，输出JSON，字段必须使用中文："
        "`岗位画像`、`维度评分`、`职责与产出`、`候选人要求`、`薪酬福利`、`工作强度`、"
        "`机会与风险`、`需要追问`、`汇总要点`。"

        "—— 岗位画像 ——"
        "`岗位画像`为对象，包含：`岗位名称`、`岗位定位`、`工作地点`、`经验要求`、`学历要求`、"
        "`关键词`(最多8个，保留技术/业务原词)、`一句话总结`。"

        "—— 维度评分 ——"
        "`维度评分`为对象，包含以下四个维度，每个维度都输出对象："
        "`职责质量`、`要求合理性`、`薪酬福利`、`工作强度`。"
        "每个维度对象包含：`分数`(0-100)、`星级`(`★☆☆☆☆`-`★★★★★`)、`等级`、`理由`。"
        "评分口径：职责清晰、有核心产出、技术成长明确则职责质量高；"
        "要求与薪资/级别匹配、硬性要求清楚则要求合理性高；"
        "薪资和福利明确且有竞争力则薪酬福利高；"
        "工作强度维度分数越高代表强度越友好、可持续，而不是越累越高。"

        "—— 职责与产出 ——"
        "`职责与产出`为对象，包含：`岗位职责`(最多12条)、`核心任务`(3-6条)、`技术栈`、`业务方向`、`成长信号`。"
        "`技术栈`为对象，含`编程语言`、`框架与库`、`工具与平台`、`数据库与中间件`、`其他`，每项为数组。"

        "—— 候选人要求 ——"
        "`候选人要求`为对象，包含：`硬性要求`、`加分项`、`软技能`、`学历经验`、`候选人匹配度`。"
        "`学历经验`包含`最低学历`、`偏好学历`、`最低经验年限`、`偏好经验年限`、`行业背景`。"
        "若无 candidate_profile，`候选人匹配度`填null；若有，则按候选人画像输出命中项、缺口项、匹配等级和一句话总结。"

        "—— 薪酬福利 ——"
        "`薪酬福利`为对象，包含：`薪资范围`、`月薪下限`、`月薪上限`、`发薪月数`、"
        "`福利亮点`、`缺失信息`、`竞争力判断`。"
        "金额用职位原文推断，无法可靠换算则填null；不要编造奖金、年终奖或社保公积金。"

        "—— 工作强度 ——"
        "`工作强度`为对象，包含：`强度等级`、`友好度星级`、`工时信号`、`压力源`、`数据缺口`。"
        "明确`不加班`、`双休`、`朝九晚六`、`居家`等是友好信号；未提及不能自动视为高强度。"

        "`机会与风险`为对象，包含：`机会`、`风险`、`适合人群`、`不适合人群`，每项为字符串数组。"

        "`需要追问`为字符串数组，最多6条，只问职位侧问题，例如薪资结构、发薪月数、项目归属、转内岗真实性、"
        "加班补偿、远程/居家稳定性、技术栈和团队分工。"

        "`汇总要点`为长度不超过350字的字符串，结构为：岗位定位 → 四个维度评分结论 → 最大亮点 → 最大风险/待确认点。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_job_value(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = chat_json(
        build_job_value_messages(cleaned, candidate_profile=candidate_profile),
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
            focus_hint="综合评估职位职责、要求、薪酬福利与工作强度",
            candidate_profile=candidate_profile,
            source_scope="job_value",
        ),
    }
