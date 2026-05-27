"""Helpers shared by all job-analysis sub-agents."""

from __future__ import annotations

import json
from typing import Any

from llm import cached_text, text_block

# Trim per-agent inputs so we never blow past the context window even on
# unusually long postings. Each agent only consumes the fields it cares about
# plus a slice of the body text.
MAX_BODY_TEXT_FOR_AGENT = 12_000


def agent_input_context(
    cleaned: dict[str, Any],
    focus_hint: str | None = None,
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON context payload handed to a sub-agent.

    Keeps the input lean: title, quick-extracted fields, URL, and a body-text
    slice — every analyzer can still inspect the raw posting wording but the
    total prompt size stays bounded.

    When ``candidate_profile`` is provided, it is attached so agents that
    care about candidate-fit (requirements / compensation / work_intensity /
    final_evaluation) can personalize their output.
    """
    body_text = cleaned.get("body_text") or ""
    if isinstance(body_text, str) and len(body_text) > MAX_BODY_TEXT_FOR_AGENT:
        body_text = body_text[:MAX_BODY_TEXT_FOR_AGENT]
        truncated = True
    else:
        truncated = bool(cleaned.get("body_truncated"))

    context: dict[str, Any] = {
        "url": cleaned.get("url"),
        "final_url": cleaned.get("final_url"),
        "page_title": cleaned.get("page_title"),
        "quick_fields": cleaned.get("quick_fields") or {},
        "external": cleaned.get("external") or {},
        "body_text": body_text,
        "body_truncated": truncated,
        "focus": focus_hint,
    }
    if candidate_profile:
        context["candidate_profile"] = candidate_profile
    return context


def build_messages(
    *,
    system_prompt: str,
    user_static: str,
    user_dynamic_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the [system, user] message pair used by every sub-agent.

    ``user_static`` is wrapped in ``cached_text`` so Anthropic providers can
    reuse it across runs; OpenAI-compatible providers receive the flattened
    string transparently (see ``llm._flatten_message_for_openai``).
    """
    user_dynamic = json.dumps(user_dynamic_payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [cached_text(user_static), text_block(user_dynamic)],
        },
    ]
