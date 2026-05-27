"""Final synthesis agent — combine all sub-agent outputs into a verdict."""

from __future__ import annotations

import json
from typing import Any

from llm import DEFAULT_MODEL, cached_text, chat_json, text_block

MODULE_NAME = "final_evaluation"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "综合评分",
    "星级",
    "岗位画像",
    "匹配建议",
    "优势亮点",
    "潜在风险",
    "适合人群",
    "短期前景_3年",
    "长期前景_5_10年",
    "申请建议",
    "markdown_summary",
)

MODULE_LABELS = {
    "job_value": "职位综合价值",
    "company_risk": "公司风险与健康度",
    "industry_outlook": "行业与赛道前景",
}


def _module_label(module_name: str) -> str:
    return MODULE_LABELS.get(module_name, module_name)


def _analysis_payload(module_payload: dict[str, Any]) -> dict[str, Any]:
    analysis = module_payload.get("analysis") if isinstance(module_payload, dict) else None
    return analysis if isinstance(analysis, dict) else {}


def build_final_evaluation_context(
    url: str,
    module_analyses: dict[str, dict[str, Any]],
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    modules = []
    ordered = [m for m in MODULE_LABELS if m in module_analyses]
    ordered.extend(m for m in module_analyses if m not in MODULE_LABELS)
    for module_name in ordered:
        payload = module_analyses.get(module_name, {})
        modules.append(
            {
                "module": module_name,
                "name": _module_label(module_name),
                "model": payload.get("model"),
                "analysis": _analysis_payload(payload),
            }
        )
    context: dict[str, Any] = {"url": url, "modules": modules}
    if candidate_profile:
        context["candidate_profile"] = candidate_profile
    return context


def build_final_evaluation_messages(
    url: str,
    module_analyses: dict[str, dict[str, Any]],
    candidate_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = build_final_evaluation_context(url, module_analyses, candidate_profile)
    system_prompt = (
        "你是专业的招聘顾问助手。"
        "你会收到针对同一个职位的多个子分析结果（职位综合价值、公司风险与健康度、行业与赛道前景），"
        "可能还会附带 `candidate_profile`（候选人画像）。"
        "你只根据各子模块的结构化结果做整合，不重新读取原始职位正文，不重算子模块已经分离出的事实。"
        "请整合所有信息，给出最终的岗位画像和申请建议。"
        "不得编造子分析中未出现的数据。若 `industry_outlook` / `company_risk` 中"
        "`信息来源` 标注为 `模型常识`，使用时要在文字里明确说明 `(基于行业常识)`。"
        "只输出JSON对象，不要输出多余文本。"
    )
    user_static = (
        "请基于下方各子模块的`analysis`和（若有）`candidate_profile`输出最终汇总JSON，字段必须使用中文："
        "`综合评分`、`星级`、`岗位画像`、`匹配建议`、`优势亮点`、`潜在风险`、"
        "`适合人群`、`短期前景_3年`、`长期前景_5_10年`、`申请建议`、`markdown_summary`。"

        "—— 评分与等级 ——"
        "`综合评分`为0-100之间的数字，越值得关注分数越高。"
        "评分锚点（共100%）："
        "职位综合价值50%，公司风险与健康度30%，行业与赛道前景20%。"
        "硬性下调规则（任意一条命中即生效）："
        "(a) `company_risk.统一评分.等级` 为 `高风险` → 综合评分不得超过 49；"
        "(b) `company_risk.统一评分.等级` 为 `偏谨慎` → 综合评分不得超过 69；"
        "(c) `job_value.工作强度.强度等级` 为 `极高强度` → 综合评分不得超过 64；"
        "(d) `industry_outlook.短期前景_3年.方向判断` 为 `明显走弱` → 综合评分不得超过 64。"
        "若多个子模块字段缺失，应避免给出80分以上的高分。"
        "若有 `candidate_profile`，把岗位与候选人画像的匹配度也作为加权调整：高匹配 +3，部分匹配 0，不匹配 -5；"
        "但调整后的分数仍须遵守上述硬性下调规则。"
        "`星级`为字符串，从`★☆☆☆☆`-`★★★★★`五档之一，须与`综合评分`对齐："
        "0-39 → ★☆☆☆☆，40-54 → ★★☆☆☆，55-69 → ★★★☆☆，70-84 → ★★★★☆，85-100 → ★★★★★。"

        "—— 画像与匹配 ——"
        "`岗位画像`为对象，包含`岗位定位`(`基础岗`/`核心岗`/`管理岗`/`专家岗`/`新兴方向`其一)、"
        "`关键词`(字符串数组，最多8个)、`一句话总结`三个键；优先使用 `job_value.岗位画像`。"
        "`匹配建议`为对象，包含以下键："
        "`理想候选人画像`(字符串)、`不建议人群`(字符串)、`经验匹配区间`(如`3-5年`)、"
        "`vs 候选人画像`(对象，仅当有 candidate_profile 时输出，否则填 null。结构："
        "`匹配等级`=`高匹配`/`基本匹配`/`部分匹配`/`不匹配`/`数据不足`, "
        "`命中项`=字符串数组(最多4条，引用候选人具体技能/经验), "
        "`缺口项`=字符串数组(最多4条，候选人不满足的硬性要求), "
        "`一句话总结`=字符串)。"

        "—— 亮点与风险 ——"
        "`优势亮点`为字符串数组，最多5条，必须保留子模块`汇总要点`或`分析`中出现的原始数据(如薪资数字、技术栈、福利)。"
        "`潜在风险`为字符串数组，最多5条，整合各子模块的风险信号；"
        "每条末尾用括号标注来源分类，可选 `(财务)` `(业务)` `(管理)` `(法律)` `(强度)` `(行业)`；"
        "公司侧风险统一来自 `company_risk.风险明细` 和 `company_risk.汇总要点`。"

        "—— 人群与前景 ——"
        "`适合人群`为字符串数组，最多4条，给出适合投递该岗位的候选人类型（如`3-5年全栈工程师`、`想转 AI 工程的后端`）。"
        "`短期前景_3年`为对象，包含三个键："
        "`业务稳定性`(`高`/`中`/`低`/`数据不足`)、`核心风险`(字符串，一句话)、`机会`(字符串，一句话)。"
        "需综合 `company_risk.稳定性判断`、`industry_outlook.短期前景_3年`、`job_value.机会与风险` 给出判断。"
        "`长期前景_5_10年`为对象，包含三个键："
        "`成长天花板`(`高`/`中`/`低`/`数据不足`)、`赛道判断`(字符串，一句话谈行业 5-10 年的位置)、"
        "`转换能力`(字符串，一句话，谈这段经历能转向哪些方向)。"
        "需综合 `industry_outlook.长期前景_5_10年`、`company_risk.稳定性判断`、`job_value.职责与产出.技术栈` 等给出判断。"
        "若 `industry_outlook` / `company_risk` 中相关项标注 `信息来源` 为 `模型常识`，须在 `赛道判断` 末尾加 `(基于行业常识)`。"
        "若信息不足无法给出长期判断，对应字段填`数据不足`或`信息不足以判断`，不要编造行业增长数字。"

        "—— 申请建议 ——"
        "`申请建议`为对象，包含以下键："
        "`建议动作`(`立即投递`/`重点关注`/`谨慎评估`/`暂不推荐`其一)、"
        "`理由`(一句话)、"
        "`面试准备建议`(字符串数组，最多4条，若有候选人画像应针对其`技能盲区`重点准备)、"
        "`必问问题`(字符串数组，最多4条，从 `company_risk.需要追问`、`job_value.需要追问`、"
        "`industry_outlook.数据可信度.建议用户补充` 中挑出最关键的)、"
        "`补救建议`(字符串数组，仅当有候选人画像且存在`缺口项`时输出，给出候选人在投递前可快速补强的方向，最多3条)。"
        "`建议动作`必须与`综合评分`一致：75-100对应`立即投递`或`重点关注`，"
        "60-74对应`重点关注`或`谨慎评估`，40-59对应`谨慎评估`，0-39对应`暂不推荐`。"

        "—— 可读性汇总 ——"
        "`markdown_summary`为一段 markdown 文本（120-450字），按下面格式给出人类可读摘要，"
        "使用 emoji 锚点，所有数字 / 关键术语必须来源于子模块的原始分析："
        "```\n"
        "## 📌 {一句话总结}\n"
        "**综合评分**：{综合评分}/100 {星级}　·　**建议**：{建议动作}\n"
        "{若有候选人画像：**vs 候选人**：{匹配等级}}\n\n"
        "- 💰 **薪酬**：{job_value 薪资范围} · {job_value 薪酬福利评分/等级}\n"
        "- 🏭 **公司**：{公司名称} · {规模} · {行业} · {company_risk 统一评分等级}\n"
        "- 🚀 **岗位**：{岗位定位} · {核心任务一句话}\n"
        "- 📊 **工作强度**：{job_value 工作强度友好度星级} {强度等级} · {压力源最关键一条}\n"
        "- ⚠️ **公司风险**：{company_risk 星级} {等级} · {最关键一条风险/待确认点}\n"
        "- 🌐 **行业**：{阶段} · {短期方向判断} · {长期方向判断}\n"
        "- ✅ **亮点**：{优势亮点最多3条，用 / 分隔}\n"
        "- 🛑 **风险**：{潜在风险最多3条带分类标签，用 / 分隔}\n"
        "- 📈 **3年视角**：{业务稳定性} · {核心风险一句话}\n"
        "- 🔭 **5-10年视角**：{成长天花板} · {赛道判断一句话}\n"
        "- 💡 **必问**：{必问问题最多2条，用 / 分隔}\n"
        "```\n"
        "上面的花括号占位符必须替换成具体内容；保留所有 markdown 语法和 emoji。"
        "若某条数据缺失，可写 `数据不足`，不要省略整行。"
        "若没有候选人画像，**vs 候选人** 那一行整行省略，不要保留 `{}` 占位。"

        "请把判断放入上述评价字段中，不要额外输出未要求的字段；字段值中保留专业术语原文。"
        "JSON键名必须严格使用上述中文键名。"
    )
    user_dynamic = json.dumps(context, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [cached_text(user_static), text_block(user_dynamic)]},
    ]


def analyze_final_evaluation(
    url: str,
    module_analyses: dict[str, dict[str, Any]],
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = chat_json(
        build_final_evaluation_messages(url, module_analyses, candidate_profile),
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        temperature=0.2,
        expected_keys=EXPECTED_KEYS,
    )
    return {
        "module": MODULE_NAME,
        "url": url,
        "model": MODEL_NAME,
        "analysis": analysis,
        "input": build_final_evaluation_context(url, module_analyses, candidate_profile),
    }
