"""Sub-agent: extract and summarize the job responsibilities / duties."""

from __future__ import annotations

from typing import Any

from llm import DEFAULT_MODEL, chat_json

from ._shared import agent_input_context, build_messages

MODULE_NAME = "responsibilities"
MODEL_NAME = DEFAULT_MODEL
EXPECTED_KEYS = ("岗位职责", "核心任务", "技术栈", "汇总要点")


def build_responsibility_messages(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input_context(cleaned, focus_hint="拆解岗位职责与核心任务")
    system_prompt = (
        "你是专业的招聘信息分析助手，擅长把岗位描述拆解为可执行的职责清单。"
        "只输出JSON对象，不要输出多余文本。所有结论必须来源于输入。"
    )
    user_static = (
        "请阅读下面的职位页面数据，输出JSON，字段必须使用中文："
        "`岗位职责`、`核心任务`、`技术栈`、`汇总要点`。"
        "字段说明："
        "`岗位职责`为字符串数组，逐条提取页面中的职责描述，保持原文动词与名词，避免合并；最多15条。"
        "`核心任务`为字符串数组，提炼3-6条该岗位最核心的工作产出（优先级高、影响面大的任务）。"
        "`技术栈`为对象，包含`编程语言`、`框架与库`、`工具与平台`、`数据库与中间件`、`其他`五个键，每个键的值为字符串数组；"
        "若岗位非技术岗或未提及技术栈，每个键填空数组。"
        "`汇总要点`为长度不超过300字的字符串，用于最终汇总，需保留关键技术词与业务方向。"
        "JSON键名必须严格使用上述中文键名。"
    )
    return build_messages(
        system_prompt=system_prompt,
        user_static=user_static,
        user_dynamic_payload=context,
    )


def analyze_responsibilities(cleaned: dict[str, Any]) -> dict[str, Any]:
    analysis = chat_json(
        build_responsibility_messages(cleaned),
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
        "input": agent_input_context(cleaned, focus_hint="拆解岗位职责与核心任务"),
    }
