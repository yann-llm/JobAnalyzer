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
        "每个维度对象必须含以下字段："
        "`分数`(0-100整数)、`星级`(`★☆☆☆☆`-`★★★★★`，0-39一星，40-54二星，55-69三星，70-84四星，85-100五星)、"
        "`等级`、`title`(一句结论性短句，10-20字)、`text`(1-3句分析正文，必须基于JD原文证据)、"
        "`kpis`(对象数组，正好4项，每项含 `label`/`val`/`sub`/`source` 四个字段)。"

        "评分口径：职责清晰、有核心产出、技术成长明确则职责质量高；"
        "要求与薪资/级别匹配、硬性要求清楚则要求合理性高；"
        "薪资和福利明确且有竞争力则薪酬福利高；"
        "工作强度维度分数越高代表强度越友好、可持续，而不是越累越高。"

        "—— KPI 输出严格要求 ——"
        "1. 每个维度的 `kpis` 必须正好 4 项；"
        "2. `label` ≤ 8 字，简短指标名；"
        "3. `val` 必须是「关键值」：可量化数字（如 `5`）、带单位的数字（如 `38 字`、`490 字符`、`57%`、`30-45K`）、"
        "级别词（如 `高`、`明确`、`友好`）、组合（如 `4/5`、`本科+5年`）；"
        "禁止用「完整」「适中」「未提及」等抽象词单独作为 val——必须给出可量化值；"
        "4. `sub` 必须是补充说明，按以下优先级填："
        "  (a) 客观计算结果（例：`总长 490 字符`、`命中 12 个技术名词：React/TypeScript/...`、`议价空间 15K`）；"
        "  (b) JD 原文短引用（例：`引用 \"接受高强度工作节奏\"`、`要求 \"4 年以上后端经验\"`）；"
        "  (c) 真实对比基准（仅在确知时使用，例：`Hudson 2025 全栈程序员区间`）；"
        "  (d) 没有任何基准/引用时，老实写 `未提供基准` 或 `JD 未提及`；"
        "禁止编造未接入的数据源（不得出现：脉脉、看准网、Glassdoor、WakaTime、市场分位 P82、行业均值 N 等具体数字）；"
        "5. `source` 只能从白名单选：`JD原文` / `LLM推断`；"
        "客观可数（条目数、字符数、关键词数）选 `JD原文`，定性判断选 `LLM推断`。"

        "—— 各维度推荐 KPI 模板（val 是关键值，sub 是基准或引用） ——"
        "`职责质量.kpis`："
        "`{label:'职责条目数', val:'5'(数字), sub:'前两条简述：负责X / 推进Y', source:'JD原文'}`、"
        "`{label:'平均描述长度', val:'38 字' 或 '总 490 字', sub:'JD职责段总字符数', source:'JD原文'}`、"
        "`{label:'技术关键词密度', val:'高/中/低', sub:'命中 12 个技术名词：Python/React/...', source:'JD原文'}`、"
        "`{label:'业务上下文', val:'明确/一般/弱', sub:'引用具体团队/产品/客户名 例 \"飞书文档编辑器核心模块\"', source:'JD原文'}`。"

        "`要求合理性.kpis`："
        "`{label:'硬性门槛', val:'本科+5年' 等组合, sub:'引用JD原文「本科及以上、5-10年经验」', source:'JD原文'}`、"
        "`{label:'技能要求数', val:'8'(数字), sub:'其中较稀缺3项：A/B/C', source:'JD原文'}`、"
        "`{label:'经验匹配薪资', val:'匹配/偏高/偏低', sub:'5-10年对应30-45K，符合中级偏上级别', source:'LLM推断'}`、"
        "`{label:'JD完整度', val:'完整/部分完整/简略', sub:'职责、要求、薪资范围、福利明细的覆盖情况', source:'JD原文'}`。"
        "注意：`薪资范围`不等同于`福利明细`。若 JD 只给出薪资范围但未提发薪月数、年终奖、社保公积金、补贴、期权等，"
        "`JD完整度.sub`不得写`福利覆盖度（3/3）`或暗示福利覆盖完整，应写`职责和要求较完整，薪资范围已给出；福利明细不足`。"

        "`薪酬福利.kpis`："
        "`{label:'现金月薪', val:'30-45K', sub:'JD原文薪资范围', source:'JD原文'}`（注：此项 main.py 会用 Hudson 基准覆盖为更权威的对比）、"
        "`{label:'薪资跨度', val:'50%' 或 '15K' 跨度绝对值, sub:'议价空间适中', source:'JD原文'}`、"
        "`{label:'福利完备度', val:'2/5', sub:'命中：餐补、年终；缺失：住房、社保明细、股票', source:'JD原文'}`、"
        "`{label:'缺失福利信息', val:'3 项' 数量, sub:'未提及：发薪月数、年终奖、社保公积金', source:'JD原文'}`。"

        "`工作强度.kpis`："
        "`{label:'工时信号', val:'友好/中性/警示', sub:'引用 \"双休\"/\"弹性\"/\"高强度\"/\"无加班说明\" 等 JD 原文', source:'JD原文'}`、"
        "`{label:'强度等级', val:'低/中/高/极高', sub:'综合判断依据一句，避免编造数字', source:'LLM推断'}`、"
        "`{label:'压力源', val:'1 条' 或最关键描述（≤6字）, sub:'JD原文短引用 \"快速迭代\" / \"客户响应\"', source:'JD原文'}`、"
        "`{label:'远程灵活性', val:'弹性/居家/不支持/未提', sub:'JD原文引用或填\"JD 未提及\"', source:'JD原文'}`。"

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
