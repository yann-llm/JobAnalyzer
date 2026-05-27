"""Sub-agent: assess workload intensity, pressure sources, and burnout signals."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "work_intensity"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("强度评级", "工时信号", "压力源", "行业对比", "数据缺口", "汇总要点")


def build_work_intensity_messages(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="评估工作强度与压力源",
        candidate_profile=candidate_profile,
    )
    system_prompt = (
        "你是专业的招聘信息分析助手，擅长从职位描述里捕捉工作强度与压力源信号。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入，宁可标注`数据不足`也不要编造。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`强度评级`、`工时信号`、`压力源`、`行业对比`、`数据缺口`、`汇总要点`。"

        "—— 字段说明 ——"

        "`强度评级`为对象，包含以下键："
        "`星级`(`★☆☆☆☆`-`★★★★★`五档之一)、"
        "`等级`(`轻松`/`适中`/`偏高`/`高强度`/`极高强度`/`数据不足`其一)、"
        "`一句话总结`(必须引用文本里出现的关键词或数字)。"
        "评级口径："
        "★ 朝九晚五双休、明确反对加班；"
        "★★ 双休但偶有加班；"
        "★★★ 工时未明确但岗位涉及多任务/跨部门协作（默认锚点）；"
        "★★★★ 明确大小周 / 弹性=变相加班 / 项目周期紧；"
        "★★★★★ 996 / 007 / 长期高压。"
        "若页面没有任何工时与节奏线索，使用 `数据不足`并配 ★★★（中性占位）。"

        "`工时信号`为对象，包含以下键："
        "`工作制`(原文短语如`大小周`、`双休`、`996`、`弹性工作制`，缺失填null)、"
        "`每周工时`(数字或区间字符串，缺失填null)、"
        "`是否加班`(`是`/`否`/`偶发`/`未明确`其一)、"
        "`加班补偿`(如`调休`/`加班费`/`未明确`)、"
        "`关键原文`(字符串数组，最多5条，原样引用页面中关于工时/加班/节奏的句子)。"

        "`压力源`为对象，按 4 类分桶；每桶值为字符串数组，每条简短，"
        "若该桶无信号填空数组 `[]`，不要省略键。"
        "包含以下键："
        "`时间压力`(如`项目周期紧`、`迭代频率高`、`要求 7×24 待命`、`需上线时陪伴`)、"
        "`协作压力`(如`跨多部门`、`需直接对接高管`、`需对接外部客户`、`远程异地协作`)、"
        "`考核压力`(如`KPI 严苛`、`末位淘汰`、`季度考核`、`目标量化压力大`)、"
        "`角色压力`(如`从0到1搭建`、`身兼数职`、`要求快速决策`、`一人多角色`、`无明确汇报关系`)。"

        "`行业对比`为对象，包含以下键："
        "`参照行业`(如`互联网大厂`、`传统制造`、`金融`、`咨询`、`AI 创业公司`，按页面行业线索选)、"
        "`普遍强度`(`轻松`/`适中`/`偏高`/`高强度`，基于通用认知判断该行业的平均水平，不可编造数据)、"
        "`相对该行业`(`明显偏低`/`持平`/`明显偏高`/`数据不足`其一)、"
        "`理由`(一句话)。"

        "`数据缺口`为字符串数组，列出影响强度判断、希望用户补充的信息，最多4条；"
        "例如`未提及考勤制度`、`未说明项目周期`、`未说明加班补偿政策`、`未说明值班/oncall 要求`。无缺口填空数组。"

        "`汇总要点`为长度不超过250字的字符串，给最终汇总用，需保留强度评级、关键工时词、最严重的1-2条压力源。"

        "—— 如果输入里附带 candidate_profile，额外增加一个字段 `候选人承受度` ——"
        "`候选人承受度`为对象，包含以下键："
        "`vs可接受强度`(`远低于`/`匹配`/`略超出`/`明显超出`/`数据不足`，对照 candidate_profile.constraints.可接受加班强度)、"
        "`工作模式匹配`(`匹配`/`部分匹配`/`不匹配`/`数据不足`，对照 constraints.可接受工作模式)、"
        "`出差匹配`(`匹配`/`接近上限`/`超出`/`数据不足`，对照 constraints.出差接受度)、"
        "`一句话总结`(基于以上字段写一句对该候选人的强度匹配判断，必须引用具体词如`996`、`项目早期`、`远程`)。"
        "若没有 candidate_profile，则不输出此字段。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_work_intensity(
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = chat_json(
        build_work_intensity_messages(cleaned, candidate_profile=candidate_profile),
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
            focus_hint="评估工作强度与压力源",
            candidate_profile=candidate_profile,
        ),
    }
