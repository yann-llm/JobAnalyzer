"""Shared LLM SDK helpers with OpenAI, Anthropic, and DeepSeek provider support.

Adapted from the eastmoney project. Reads provider/model/api_key/base_url from
``llm_config.json`` next to this file (override path via ``LLM_CONFIG_PATH``),
falling back to environment variables. Provides:

- ``chat_completion`` / ``chat_text``: free-form chat calls
- ``chat_json``: chat calls that must return a JSON object (with validation)
- ``cached_text`` / ``text_block``: Anthropic-style content blocks. OpenAI
  callers receive them flattened into a plain string transparently.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH_ENV = "LLM_CONFIG_PATH"
DEFAULT_CONFIG_PATH = PROJECT_DIR / "llm_config.json"

DEFAULT_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
API_KEY_ENV = "MY_API_KEY"
BASE_URL_ENV = "MY_BASE_URL"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_BASE_URL_ENV = "ANTHROPIC_BASE_URL"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
TIMEOUT_ENV = "MY_LLM_TIMEOUT_SECONDS"
MAX_RETRIES_ENV = "MY_LLM_MAX_RETRIES"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 8192
TEMPERATURE_REJECT_MODELS_ENV = "MY_LLM_TEMPERATURE_REJECT_MODELS"
DEFAULT_TEMPERATURE_REJECT_MODELS: tuple[str, ...] = ("opus-4-7",)

_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "model": DEFAULT_OPENAI_MODEL,
        "api_key_env": API_KEY_ENV,
        "base_url_env": BASE_URL_ENV,
        "default_base_url": None,
    },
    "anthropic": {
        "model": DEFAULT_ANTHROPIC_MODEL,
        "api_key_env": ANTHROPIC_API_KEY_ENV,
        "base_url_env": ANTHROPIC_BASE_URL_ENV,
        "default_base_url": None,
    },
    "deepseek": {
        "model": DEFAULT_DEEPSEEK_MODEL,
        "api_key_env": DEEPSEEK_API_KEY_ENV,
        "base_url_env": DEEPSEEK_BASE_URL_ENV,
        "default_base_url": DEFAULT_DEEPSEEK_BASE_URL,
    },
}

_OPENAI_COMPATIBLE_PROVIDERS = frozenset({"openai", "deepseek"})

Message = dict[str, str]


@lru_cache(maxsize=1)
def _temperature_reject_patterns() -> tuple[str, ...]:
    raw = os.getenv(TEMPERATURE_REJECT_MODELS_ENV)
    if raw is None:
        return DEFAULT_TEMPERATURE_REJECT_MODELS
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


def _model_rejects_temperature(model: str) -> bool:
    name = (model or "").lower()
    return any(p in name for p in _temperature_reject_patterns())


def _provider_config(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = payload.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(provider), dict):
        return providers[provider]
    nested = payload.get(provider)
    return nested if isinstance(nested, dict) else {}


def _provider_defaults(provider: str) -> dict[str, Any]:
    return _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS[DEFAULT_PROVIDER])


def _configured_default_model() -> str:
    config_path = Path(os.getenv(CONFIG_PATH_ENV, str(DEFAULT_CONFIG_PATH)))
    payload: dict[str, Any] = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    provider = str(payload.get("provider") or os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    provider_payload = _provider_config(payload, provider)
    default_model = _provider_defaults(provider)["model"]
    return str(provider_payload.get("model") or payload.get("model") or os.getenv("LLM_MODEL") or default_model)


DEFAULT_MODEL = _configured_default_model()


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    timeout: float
    max_retries: int


def _read_config_file() -> dict[str, Any]:
    config_path = Path(os.getenv(CONFIG_PATH_ENV, str(DEFAULT_CONFIG_PATH)))
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid LLM config JSON: {config_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"LLM config must be a JSON object: {config_path}")
    return payload


def _config_value(provider_payload: dict[str, Any], root_payload: dict[str, Any], key: str, env_name: str | None = None) -> Any:
    if provider_payload.get(key) not in (None, ""):
        return provider_payload.get(key)
    if root_payload.get(key) not in (None, ""):
        return root_payload.get(key)
    return os.getenv(env_name) if env_name else None


def _required(value: str | None, label: str) -> str:
    if not value:
        raise RuntimeError(f"Missing required LLM configuration: {label}")
    return value


@lru_cache(maxsize=1)
def get_llm_config() -> LlmConfig:
    payload = _read_config_file()
    provider = str(payload.get("provider") or os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if provider not in _PROVIDER_DEFAULTS:
        supported = ", ".join(sorted(_PROVIDER_DEFAULTS))
        raise RuntimeError(f"Unsupported LLM provider: {provider} (supported: {supported})")

    provider_payload = _provider_config(payload, provider)
    defaults = _provider_defaults(provider)
    model = str(_config_value(provider_payload, payload, "model") or os.getenv("LLM_MODEL") or defaults["model"])
    timeout = float(_config_value(provider_payload, payload, "timeout", TIMEOUT_ENV) or DEFAULT_TIMEOUT_SECONDS)
    max_retries = int(_config_value(provider_payload, payload, "max_retries", MAX_RETRIES_ENV) or DEFAULT_MAX_RETRIES)
    api_key = _config_value(provider_payload, payload, "api_key", defaults["api_key_env"])
    base_url = _config_value(provider_payload, payload, "base_url", defaults["base_url_env"]) or defaults["default_base_url"]

    return LlmConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


def default_model() -> str:
    return get_llm_config().model


@lru_cache(maxsize=1)
def get_openai_client() -> Any:
    from openai import OpenAI

    config = get_llm_config()
    api_key_label = f"{config.provider}.api_key or {_provider_defaults(config.provider)['api_key_env']}"
    kwargs: dict[str, Any] = {
        "api_key": _required(config.api_key, api_key_label),
        "base_url": config.base_url,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["http_client"] = _build_direct_http_client(config.timeout)
    return OpenAI(**kwargs)


@lru_cache(maxsize=1)
def get_anthropic_client() -> Any:
    from anthropic import Anthropic

    config = get_llm_config()
    kwargs: dict[str, Any] = {
        "api_key": _required(config.api_key, "anthropic.api_key or ANTHROPIC_API_KEY"),
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
        kwargs["http_client"] = _build_direct_http_client(config.timeout)
    return Anthropic(**kwargs)


def _build_direct_http_client(timeout: float) -> Any:
    import httpx

    return httpx.Client(timeout=timeout, trust_env=False)


def get_llm_client() -> Any:
    config = get_llm_config()
    if config.provider == "anthropic":
        return get_anthropic_client()
    if config.provider in _OPENAI_COMPATIBLE_PROVIDERS:
        return get_openai_client()
    raise RuntimeError(f"Unsupported LLM provider: {config.provider}")


def chat_completion(
    messages: Sequence[Message],
    *,
    model: str | None = None,
    **kwargs: Any,
) -> Any:
    config = get_llm_config()
    selected_model = model or config.model
    if config.provider == "anthropic":
        return _anthropic_chat_completion(messages, model=selected_model, **kwargs)
    if config.provider not in _OPENAI_COMPATIBLE_PROVIDERS:
        raise RuntimeError(f"Unsupported LLM provider: {config.provider}")
    kwargs.setdefault("timeout", config.timeout)
    return get_openai_client().chat.completions.create(
        model=selected_model,
        messages=[_flatten_message_for_openai(m) for m in messages],
        **kwargs,
    )


def _flatten_message_for_openai(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)
    text_parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return {**message, "content": "\n\n".join(text_parts)}


def _anthropic_chat_completion(
    messages: Sequence[Message],
    *,
    model: str,
    **kwargs: Any,
) -> Any:
    system_blocks: list[dict[str, Any]] = []
    anthropic_messages: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_blocks.extend(_to_anthropic_text_blocks(content))
        else:
            anthropic_messages.append({
                "role": "assistant" if role == "assistant" else "user",
                "content": content if isinstance(content, list) else content,
            })

    kwargs.pop("response_format", None)
    if _model_rejects_temperature(model):
        kwargs.pop("temperature", None)
    timeout = kwargs.pop("timeout", get_llm_config().timeout)
    max_tokens = kwargs.pop("max_tokens", None) or kwargs.pop("max_completion_tokens", None) or DEFAULT_MAX_TOKENS
    if "stream" in kwargs:
        kwargs.pop("stream")

    request: dict[str, Any] = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "timeout": timeout,
        **kwargs,
    }
    if system_blocks:
        request["system"] = system_blocks

    response = get_anthropic_client().messages.create(**request)
    return _openai_compatible_completion(response)


def _to_anthropic_text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return [{"type": "text", "text": str(content)}]


def cached_text(text: str) -> dict[str, Any]:
    """Wrap a static text segment as an Anthropic block with ephemeral cache_control.

    For OpenAI the block list is flattened back to a plain string in
    ``_flatten_message_for_openai`` — cache hints are silently ignored.
    """
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _openai_compatible_completion(response: Any) -> Any:
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", ""))
    content = "".join(text_parts)
    return SimpleNamespace(
        id=getattr(response, "id", None),
        model=getattr(response, "model", None),
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(role="assistant", content=content),
                finish_reason=getattr(response, "stop_reason", None),
            )
        ],
        usage=getattr(response, "usage", None),
        raw_response=response,
    )


def chat_text(
    messages: Sequence[Message],
    *,
    model: str | None = None,
    **kwargs: Any,
) -> str:
    completion = chat_completion(messages, model=model, **kwargs)
    message = completion.choices[0].message
    return message.content or ""


class LlmResponseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        raw_text: str = "",
        model: str | None = None,
        expected_keys: Sequence[str] | None = None,
        missing_keys: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.model = model
        self.expected_keys = list(expected_keys) if expected_keys else None
        self.missing_keys = list(missing_keys) if missing_keys else None


def _preview(text: str, limit: int = 300) -> str:
    snippet = text.strip().replace("\n", "\\n")
    return snippet if len(snippet) <= limit else snippet[:limit] + "...(truncated)"


def chat_json(
    messages: Sequence[Message],
    *,
    model: str | None = None,
    expected_keys: Sequence[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    completion = chat_completion(messages, model=model, **kwargs)
    used_model = getattr(completion, "model", None) or model
    content = (completion.choices[0].message.content or "").strip()

    if not content:
        raise LlmResponseError("LLM 返回空内容", raw_text="", model=used_model)

    parsed = parse_llm_json(content)
    failure_keys = {"raw_text", "raw_value"}
    if parsed.keys() & failure_keys:
        reason = "LLM 响应不是 JSON 对象" if "raw_value" in parsed else "LLM 响应无法解析为 JSON"
        raise LlmResponseError(
            f"{reason}: {_preview(content)}",
            raw_text=content,
            model=used_model,
        )

    if expected_keys:
        missing = [key for key in expected_keys if key not in parsed]
        if missing:
            raise LlmResponseError(
                f"LLM 响应缺少必需字段 {missing}: {_preview(content)}",
                raw_text=content,
                model=used_model,
                expected_keys=expected_keys,
                missing_keys=missing,
            )

    return parsed


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    body = stripped[3:]
    newline = body.find("\n")
    if newline != -1 and body[:newline].strip().lower() in {"json", ""}:
        body = body[newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body


def _repair_inline_quotes(text: str) -> str:
    out: list[str] = []
    n = len(text)
    in_string = False
    i = 0
    while i < n:
        c = text[i]
        if not in_string:
            out.append(c)
            if c == '"':
                in_string = True
            i += 1
            continue
        if c == "\\":
            out.append(c)
            if i + 1 < n:
                out.append(text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            next_char = text[j] if j < n else ""
            if next_char in {",", ":", "}", "]", ""}:
                out.append(c)
                in_string = False
                i += 1
            else:
                out.append('\\"')
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_llm_json(content: str) -> dict[str, Any]:
    if not content:
        return {}
    candidates = [content, _strip_code_fence(content)]
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        return {"raw_value": parsed}
    repaired = _repair_inline_quotes(_strip_code_fence(content))
    try:
        parsed = json.loads(repaired)
    except json.JSONDecodeError:
        return {"raw_text": content}
    if isinstance(parsed, dict):
        return parsed
    return {"raw_value": parsed}
