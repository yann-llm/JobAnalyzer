"""Minimal MCP client for the streamable-HTTP transport.

We only need to call ``tools/call`` against a remote MCP server. The full MCP
spec (notifications, roots, prompts, resources, subscriptions) is overkill
for this project, so this client implements the smallest viable shape:

    1. POST initialize       → server returns capabilities (SSE-framed)
    2. POST notifications/initialized
    3. POST tools/call        → server returns tool result (SSE-framed)

Each POST is independent — the server runs in **stateless** mode for QCC
(no Mcp-Session-Id header is required). The session is recreated on every
call, which is fine for a job-analysis batch and avoids carrying state.

The SSE framing is simple: lines of the form ``data: <json>``, blank line
separates events. We collect everything until the matching ``id`` arrives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import httpx


PROTOCOL_VERSION = "2025-03-26"


class McpError(RuntimeError):
    """Raised on transport-level or JSON-RPC errors."""


@dataclass
class HttpMcpServer:
    name: str
    url: str
    auth_bearer: str | None = None
    timeout: float = 60.0


def _build_headers(server: HttpMcpServer) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if server.auth_bearer:
        headers["Authorization"] = f"Bearer {server.auth_bearer}"
    return headers


def _iter_sse_messages(body: str) -> Iterator[dict[str, Any]]:
    """Parse an SSE response body into a stream of JSON messages.

    Tolerates both ``data: {...}`` lines and bare JSON (some servers).
    """
    buffer: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if buffer:
                payload = "\n".join(buffer)
                buffer = []
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
        elif line.startswith("event:") or line.startswith(":") or line.startswith("id:"):
            # ignore the event / comment / id channels
            continue
        else:
            buffer.append(line)
    if buffer:
        try:
            yield json.loads("\n".join(buffer))
        except json.JSONDecodeError:
            pass


def _post_jsonrpc(
    server: HttpMcpServer,
    payload: dict[str, Any],
    *,
    expect_response: bool,
) -> dict[str, Any] | None:
    """POST a JSON-RPC request and return the matching response dict.

    When ``expect_response`` is False (notifications), the body is discarded.
    """
    headers = _build_headers(server)
    with httpx.Client(timeout=server.timeout, trust_env=False) as client:
        try:
            response = client.post(server.url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise McpError(f"{server.name} HTTP error: {exc}") from exc

    if response.status_code >= 400:
        snippet = response.text[:300].replace("\n", " ")
        raise McpError(f"{server.name} HTTP {response.status_code}: {snippet}")

    if not expect_response:
        return None

    body = response.text
    if not body.strip():
        raise McpError(f"{server.name} returned empty body")

    target_id = payload.get("id")
    for message in _iter_sse_messages(body):
        if not isinstance(message, dict):
            continue
        if message.get("id") != target_id:
            # Skip stray events (progress notifications, log messages, etc.)
            continue
        if "error" in message:
            raise McpError(f"{server.name} JSON-RPC error: {message['error']}")
        return message
    raise McpError(f"{server.name} did not return a matching response for id={target_id}")


def initialize(server: HttpMcpServer) -> dict[str, Any]:
    """Perform the MCP initialize handshake. Returns the server info."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "job-analysis", "version": "0.1.0"},
        },
    }
    reply = _post_jsonrpc(server, request, expect_response=True)
    # Best-effort initialized notification (server is stateless and ignores).
    try:
        _post_jsonrpc(
            server,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_response=False,
        )
    except McpError:
        pass
    return (reply or {}).get("result", {})


def call_tool(
    server: HttpMcpServer,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 2,
) -> dict[str, Any]:
    """Invoke ``tool_name`` and return the parsed result payload.

    MCP tool results normally come back as ``{"content": [{"type": "text", "text": "..."}]}``.
    When the text looks like JSON, we parse it. The structuredContent field
    is also surfaced if present.
    """
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    reply = _post_jsonrpc(server, request, expect_response=True)
    result = (reply or {}).get("result", {}) or {}

    structured = result.get("structuredContent")
    if structured is not None:
        return {"structured": structured, "raw_result": result}

    content = result.get("content") or []
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text") or ""
            if text:
                texts.append(text)
    joined = "\n".join(texts).strip()
    parsed: Any
    if joined:
        try:
            parsed = json.loads(joined)
        except json.JSONDecodeError:
            parsed = {"raw_text": joined}
    else:
        parsed = {}

    return {"parsed": parsed, "raw_result": result, "is_error": bool(result.get("isError"))}
