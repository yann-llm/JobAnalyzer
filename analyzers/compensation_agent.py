"""Sub-agent: extract salary, benefits, and overall compensation signals."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "compensation"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("薪资", "福利待遇", "工作时间", "薪酬竞争力", "汇总要点")


def build_compensation_messages(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="分析薪资、福利与工作强度",
        candidate_profile=candidate_profile,
    )
    system_prompt = (
        "你是专业的招聘信息分析助手，擅长解读薪资构成、福利结构与工作强度信号。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`薪资`、`福利待遇`、`工作时间`、`薪酬竞争力`、`汇总要点`。"

        "—— 字段说明 ——"

        "`薪资`为对象，需做精细拆解，包含以下键："
        "`薪资范围`(原始文本)、`月薪下限`、`月薪上限`、`货币单位`、"
        "`发薪月数`(如`12薪`/`13薪`/`16薪`，未提及填null)、"
        "`基本工资占比`(若文本提及`底薪+提成`等结构则估算，否则填null)、"
        "`绩效奖金`(对象，包含`类型`如季度/年度/项目奖、`比例或月数`、`原文`)、"
        "`年终奖`(对象，包含`月数`、`是否承诺`、`原文`)、"
        "`股权或期权`(对象，包含`是否提供`、`授予条件`、`vesting周期`、`原文`)、"
        "`其他现金激励`(字符串数组，如`签字费`、`项目分红`)。"
        "金额一律以阿拉伯数字字符串表示（单位换算成元/月，K=千元）；若文本仅给出年薪，记录原文并把月薪下/上限填null。"
        "未提及的子字段填null，不要编造。"

        "`福利待遇`为对象，按类别分桶，包含以下键："
        "`法定福利`(字符串数组，如`五险一金`、`住房公积金`、`带薪年假`、`高温补贴`，并保留缴纳基数/比例的原文表述如有)、"
        "`特色福利`(字符串数组，公司额外提供的福利，如`补充医疗`、`年度体检`、`节日福利`、`员工旅游`、`子女教育补贴`)、"
        "`隐性福利`(字符串数组，如`通勤班车`、`住房补贴`、`餐补`、`宿舍`、`晋升通道明晰`、`内部培训体系`、`扁平管理`)。"
        "每个数组最多10条；无明显信号填空数组。原文未明示`五险一金`等基础项时也不要默认补上。"

        "`工作时间`为对象，包含`工作制`(如`大小周`、`双休`、`996`、`弹性工作制`)、`每周工时`、`是否加班`、`加班补偿`(如`调休`、`加班费`、`未明确`)四个键，缺失填null。"

        "`薪酬竞争力`为对象，包含以下键："
        "`评估等级`(`偏低`/`一般`/`有竞争力`/`高于市场`/`数据不足`其一)、"
        "`星级`(`★☆☆☆☆`-`★★★★★`五档之一，与评估等级对齐：偏低★/一般★★/有竞争力★★★/高于市场★★★★/数据不足★★★)、"
        "`理由`(一句话，必须引用文本中的薪资数字或福利原文)、"
        "`行业参考`(基于通用认知给出该城市+岗位的大致薪资区间作为对比锚点，不得编造具体公司或具体数据；若无把握填null)。"
        "评估依据仅限文本中显式的薪资范围、福利、奖金描述；`行业参考`仅作宽泛锚点。"

        "`汇总要点`为长度不超过250字的字符串，用于最终汇总，需保留薪资数字、关键福利、加班信号。"

        "—— 如果输入里附带 candidate_profile，额外增加一个字段 `候选人匹配度` ——"
        "`候选人匹配度`为对象，包含以下键："
        "`vs底线`(`高于底线`/`接近底线`/`低于底线`/`数据不足`，对照 candidate_profile.career_goals.理想薪资底线)、"
        "`vs目标`(`达到目标`/`接近目标`/`低于目标`/`数据不足`，对照 career_goals.理想薪资目标)、"
        "`福利命中`(字符串数组，从`福利待遇`中挑出与 candidate_profile.preferences.看重的福利 重合的项)、"
        "`福利缺口`(字符串数组，候选人看重但岗位未提供的福利)、"
        "`一句话总结`(基于以上字段写一句对该候选人的薪资匹配判断)。"
        "若没有 candidate_profile，则不输出此字段。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_compensation(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = chat_json(
        build_compensation_messages(cleaned, candidate_profile=candidate_profile),
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
            focus_hint="分析薪资、福利与工作强度",
            candidate_profile=candidate_profile,
        ),
    }
