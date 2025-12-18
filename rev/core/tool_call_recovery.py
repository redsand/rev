#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recover tool calls when a model returns JSON as plain text.

Some models (or tool-calling adapters) occasionally emit a JSON tool call in
`message.content` instead of populating `message.tool_calls`. This module
detects and parses those cases so execution can continue without replanning.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class RecoveredToolCall:
    name: str
    arguments: Dict[str, Any]


def _extract_json_snippet(text: str) -> Optional[str]:
    """Extract the most likely JSON object/array snippet from a text blob."""

    if not text:
        return None

    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        # Prefer the first fenced block; models typically emit one.
        return fenced[0].strip()

    # Best-effort: take from first '{' or '[' to last matching '}' or ']'.
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj == -1 and start_arr == -1:
        return None
    start = start_obj if start_arr == -1 else (start_arr if start_obj == -1 else min(start_obj, start_arr))

    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end == -1 or end <= start:
        return None
    return text[start : end + 1].strip()


def _coerce_args(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _parse_tool_call_object(obj: Dict[str, Any]) -> Optional[RecoveredToolCall]:
    # Common formats:
    # 1) {"tool_name":"create_directory","arguments":{...}}
    # 2) {"name":"create_directory","args":{...}}
    # 3) {"function":{"name":"create_directory","arguments":{...}}}
    name = obj.get("tool_name") or obj.get("name") or obj.get("tool")
    args = obj.get("arguments") or obj.get("args")

    if not name and isinstance(obj.get("function"), dict):
        fn = obj["function"]
        name = fn.get("name")
        args = fn.get("arguments")

    if not isinstance(name, str) or not name.strip():
        return None

    coerced = _coerce_args(args)
    if coerced is None:
        return None

    return RecoveredToolCall(name=name.strip(), arguments=coerced)


def recover_tool_call_from_text(
    content: str,
    *,
    allowed_tools: Optional[Iterable[str]] = None,
) -> Optional[RecoveredToolCall]:
    """Recover a single tool call from text content, if present."""

    snippet = _extract_json_snippet(content)
    if not snippet:
        return None

    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError:
        return None

    candidates = []
    if isinstance(parsed, dict):
        candidates = [parsed]
    elif isinstance(parsed, list):
        candidates = [x for x in parsed if isinstance(x, dict)]
    else:
        return None

    for candidate in candidates:
        recovered = _parse_tool_call_object(candidate)
        if not recovered:
            continue
        if allowed_tools is not None and recovered.name not in set(allowed_tools):
            continue
        return recovered

    return None
