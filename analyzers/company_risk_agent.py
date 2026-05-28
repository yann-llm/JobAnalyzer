"""Sub-agent: unified company health and risk score."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "company_risk"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = (
    "公司画像",
    "统一评分",
    "风险明细",
    "稳定性判断",
    "需要追问",
    "数据可信度",
    "汇总要点",
)


def build_company_risk_messages(
    cleaned: dict[str, Any],
    *,
    qcc_cleaned: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = agent_input_context(
        cleaned,
        focus_hint="基于企查查数据评估公司主体健康度与风险",
        source_scope="company_risk",
        qcc_cleaned=qcc_cleaned,
    )
    system_prompt = (
        "你是企业尽调与招聘风险分析助手。"
        "你把原先的公司画像、法律主体风险、经营/财务健康度合并成一个统一判断。"
        "输入中的 `company` 来自企查查清洗结果，公司事实必须只以 `company` 为准。"
        "其中 `company.operation` 含招聘活跃度（recruitment）与荣誉资质（honor）："
        "招聘活跃度反映扩张/收缩信号，荣誉（高新技术、专精特新、各级资质）反映背书与经营质量。"
        "不要分析职位薪资、工时、福利、劳动条款或岗位侧风险，这些由其他 agent 处理。"
        "严禁编造营收、利润、融资金额、估值、司法案件编号、法条条文号等精确数据。"
        "只输出JSON对象，不要输出多余文本。"
    )
    user_static = (
        "请阅读下面的企查查清洗数据，输出JSON，字段必须使用中文："
        "`公司画像`、`统一评分`、`风险明细`、`稳定性判断`、`需要追问`、`数据可信度`、`汇总要点`。"

        "—— 公司画像 ——"
        "`公司画像`为对象，包含："
        "`公司名称`、`统一社会信用代码`、`成立时间`、`注册资本`、`企业类型`、`登记状态`、"
        "`人员规模`、`参保人数`、`所属行业`、`实际控制人`、`股东结构摘要`、`对外投资摘要`、"
        "`招聘活跃度`(基于 `company.operation.recruitment`，"
        "字段含义：有职位列表/数量则为活跃；明确返回未发现/无记录则为不活跃；填`活跃`/`一般`/`不活跃`/`数据不足`+一句话说明)、"
        "`荣誉资质`(基于 `company.operation.honor`，列出高新技术、专精特新、政府/行业奖项等关键标签数组；无则空数组)。"
        "优先从 `company.registration_info`、`company.controller`、`company.shareholdinfo`、`company.investments`、`company.operation` 提取。"
        "缺失填null，禁止用模型常识补具体事实。"

        "—— 统一评分 ——"
        "`统一评分`为对象，包含："
        "`分数`(0-100数字，越高代表公司侧越稳健、越值得推进)、"
        "`星级`(`★☆☆☆☆`-`★★★★★`，0-39一星，40-54二星，55-69三星，70-84四星，85-100五星)、"
        "`等级`(`高风险`/`偏谨慎`/`中性可看`/`较稳健`/`优质稳健`/`数据不足`其一)、"
        "`一句话总结`。"
        "评分权重：工商与存续状态20%，股东/控制人稳定性20%，经营规模与参保人数15%，"
        "企查查风险记录25%，对外投资与主体扩张稳定性10%，招聘活跃度与荣誉资质10%。"
        "硬性规则："
        "若存在失信、被执行人、经营异常或重大行政处罚明确记录，分数不得超过59；"
        "若登记状态非存续/在营，分数不得超过49；"
        "若公司事实主要缺失，分数不得超过69；"
        "若企查查风险均显示未发现异常，不能仅凭模型常识打低分；"
        "招聘活跃 + 有省级及以上荣誉资质可酌情上调；"
        "新成立公司（< 1 年）招聘和荣誉缺失属正常，不构成扣分项。"

        "—— 风险明细 ——"
        "`风险明细`为对象，包含："
        "`工商风险`、`司法与处罚风险`、`经营稳定性风险`、`股东控制风险`、`对外投资风险`。"
        "每个键的值为字符串数组；每条必须引用输入里的具体字段或原文。无风险信号填空数组。"

        "—— 稳定性判断 ——"
        "`稳定性判断`为对象，包含："
        "`经营稳定性`(`高`/`中`/`低`/`数据不足`)、"
        "`组织规模可信度`(`高`/`中`/`低`/`数据不足`)、"
        "`资本结构稳定性`(`高`/`中`/`低`/`数据不足`)、"
        "`扩张稳定性`(`高`/`中`/`低`/`数据不足`，结合对外投资数量、状态、时间，"
        "以及 `company.operation.recruitment` 招聘活跃度共同判断："
        "招聘活跃 + 投资稳定 → 高；招聘冻结 + 投资退出 → 低)。"

        "`需要追问`为字符串数组，最多6条，给候选人在面试或offer沟通中追问。"
        "只覆盖公司主体层面问题：劳动合同签约主体、任职主体与招聘主体是否一致、项目归属、客户/总部合作模式、公司/分支机构承接关系。"

        "`数据可信度`为对象，包含："
        "`整体可信度`(`高`/`中`/`低`)、"
        "`主要来源`(字符串数组，如`企查查工商登记`、`企查查风险`、`职位页`)、"
        "`局限性`(字符串数组，最多4条)。"

        "`汇总要点`为长度不超过300字的字符串，结构为："
        "公司事实一句话 → 统一评分和等级 → 最主要优势 → 最主要风险/待确认点。"

        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_company_risk(cleaned: dict[str, Any], *, qcc_cleaned: dict[str, Any] | None = None) -> dict[str, Any]:
    analysis = chat_json(
        build_company_risk_messages(cleaned, qcc_cleaned=qcc_cleaned),
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
            focus_hint="基于企查查数据评估公司主体健康度与风险",
            source_scope="company_risk",
            qcc_cleaned=qcc_cleaned,
        ),
    }
