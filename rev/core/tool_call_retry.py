from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from rev.llm.client import ollama_chat
from rev.core.tool_call_recovery import RecoveredToolCall, recover_tool_call_from_text


def _parse_tool_call_from_message(message: Dict[str, Any]) -> Optional[RecoveredToolCall]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None

    call = tool_calls[0]
    if not isinstance(call, dict):
        return None

    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = fn.get("name")
    args = fn.get("arguments")
    if not isinstance(name, str) or not name.strip():
        return None

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None

    if not isinstance(args, dict):
        return None

    return RecoveredToolCall(name=name.strip(), arguments=args)


def retry_tool_call_with_response_format(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    *,
    allowed_tools: Optional[Iterable[str]] = None,
    model: Optional[str] = None,
    supports_tools: bool = True,
) -> Optional[RecoveredToolCall]:
    """Retry a tool call request with strict JSON formatting before text recovery."""
    if not messages:
        return None

    guidance = (
        "Return ONLY a JSON object for a tool call. Example:\n"
        "{\"tool_name\":\"list_dir\",\"arguments\":{\"pattern\":\"src/**\"}}"
    )
    retry_messages = list(messages) + [{"role": "user", "content": guidance}]

    response = ollama_chat(
        retry_messages,
        tools=tools,
        model=model,
        supports_tools=supports_tools,
        response_format={"type": "json_object"},
        format="json",
    )

    message = response.get("message") if isinstance(response, dict) else None
    if isinstance(message, dict):
        recovered = _parse_tool_call_from_message(message)
        if recovered:
            if allowed_tools is None or recovered.name in set(allowed_tools):
                return recovered

    content = ""
    if isinstance(message, dict):
        content = message.get("content") or ""
    return recover_tool_call_from_text(content, allowed_tools=allowed_tools)
