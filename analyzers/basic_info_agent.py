"""Sub-agent: extract basic posting metadata (title, company, location, etc.)."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "basic_info"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("职位名称", "公司名称", "工作地点", "工作类型", "发布信息", "汇总要点")


def build_basic_info_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="提取职位基础信息字段")
    system_prompt = (
        "你是专业的招聘信息抽取助手。"
        "请从职位页面文本中抽取结构化的基础信息字段。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入，不得编造。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`职位名称`、`公司名称`、`工作地点`、`工作类型`、`发布信息`、`汇总要点`。"
        "字段说明："
        "`职位名称`为单一字符串，优先使用页面标题或首段中明确出现的岗位名；"
        "`公司名称`为雇主或招聘方主体；"
        "`工作地点`为城市/区/地址，可包含多个用逗号分隔；"
        "`工作类型`为对象，包含`雇佣形式`(全职/兼职/实习/外包/合同等)、`工作模式`(现场/远程/混合)、`是否出差`三个键，未提及时填null；"
        "`发布信息`为对象，包含`发布日期`、`招聘人数`、`截止日期`三个键，未提及时填null；"
        "`汇总要点`为长度不超过200字的字符串，用于最终汇总，需保留关键原始词汇。"
        "若字段缺失必须填null，不得编造。"
        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_basic_info(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_basic_info_messages(cleaned),
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        temperature=0.1,
        expected_keys=EXPECTED_KEYS,
    )
    return {
        "module": MODULE_NAME,
        "url": cleaned.get("url"),
        "model": MODEL_NAME,
        "analysis": analysis,
        "input": agent_input_context(cleaned, focus_hint="提取职位基础信息字段"),
    }
