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

    stripped = text.lstrip()
    # Fast-path: message begins with a fenced JSON block
    if stripped.startswith("```json") or stripped.startswith("```JSON") or stripped.startswith("```"):
        # Remove the opening fence and grab everything up to the next fence (if present)
        fence_stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).lstrip()
        if "```" in fence_stripped:
            return fence_stripped.split("```", 1)[0].strip()
        # If no closing fence, fall through to best-effort braces extraction below
        stripped = fence_stripped

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


def _extract_patch_from_text(text: str) -> Optional[str]:
    if not text:
        return None

    diff_match = re.search(r"```diff\s+(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if diff_match:
        return diff_match.group(1).strip()

    if "*** Begin Patch" in text and "*** End Patch" in text:
        start = text.find("*** Begin Patch")
        end = text.rfind("*** End Patch")
        if start >= 0 and end >= start:
            return text[start : end + len("*** End Patch")].strip()

    raw_match = re.search(r"^diff --git.*", text, re.DOTALL | re.MULTILINE)
    if raw_match:
        return raw_match.group(0).strip()

    return None


def _extract_file_from_text(text: str) -> Optional[Tuple[str, str]]:
    if not text:
        return None

    fence = re.search(r"```[\w+-]*\s+([\s\S]*?)```", text)
    if not fence:
        return None

    block = fence.group(1)
    lines = block.splitlines()
    if not lines:
        return None

    first_line = lines[0].strip()
    path = None
    if any(first_line.lower().startswith(marker) for marker in ("path:", "file:", "filepath:")):
        path = first_line.split(":", 1)[1].strip()
        body = "\n".join(lines[1:])
    elif (
        "." in first_line
        and " " not in first_line
        and first_line.lower().endswith((".py", ".js", ".ts", ".md", ".json", ".yaml", ".yml", ".txt"))
    ):
        path = first_line
        body = "\n".join(lines[1:])
    else:
        return None

    body = body.rstrip("\n")
    if not path or not body:
        return None
    return path, body


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

    allowed = set(allowed_tools) if allowed_tools is not None else None

    patch = _extract_patch_from_text(content or "")
    if patch and (allowed is None or "apply_patch" in allowed):
        return RecoveredToolCall(name="apply_patch", arguments={"patch": patch})

    file_block = _extract_file_from_text(content or "")
    if file_block and (allowed is None or "write_file" in allowed):
        path, body = file_block
        return RecoveredToolCall(name="write_file", arguments={"path": path, "content": body})

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
        if allowed is not None and recovered.name not in allowed:
            continue
        return recovered

    return None
