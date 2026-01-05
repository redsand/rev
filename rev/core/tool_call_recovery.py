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


def _looks_like_code_reference(text: str) -> bool:
    """Check if text looks like a code reference rather than a file path."""
    if not text:
        return False

    # Has path separators? Likely a real file path
    if '/' in text or '\\' in text:
        return False

    # Count dots
    dot_count = text.count('.')

    # 2+ dots without path separators = definitely code reference
    if dot_count >= 2:
        return True

    # For single-dot patterns, check common patterns
    if dot_count == 1:
        parts = text.split('.')
        if len(parts) == 2:
            name, extension = parts
            common_vars = {
                'app', 'obj', 'this', 'self', 'req', 'res', 'ctx', 'config',
                'server', 'client', 'router', 'express', 'console', 'process',
                'module', 'api', 'db', 'prisma', 'auth', 'user'
            }
            common_methods = {
                'listen', 'get', 'post', 'put', 'delete', 'use', 'send', 'status',
                'json', 'log', 'error', 'warn', 'info', 'debug', 'find', 'save',
                'create', 'update', 'remove', 'connect', 'disconnect'
            }
            if name.lower() in common_vars or extension.lower() in common_methods:
                return True
    return False


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

    def _clean_path_token(token: str) -> str:
        cleaned = token.strip().strip("\"'`")
        if cleaned.endswith(":"):
            cleaned = cleaned[:-1].strip()
        return cleaned

    if any(first_line.lower().startswith(marker) for marker in ("path:", "file:", "filepath:")):
        path = _clean_path_token(first_line.split(":", 1)[1])
    else:
        # detect the first file-like token anywhere on the line
        path_match = re.search(r"[\w./\\-]+\.\w+", first_line)
        if path_match:
            candidate = _clean_path_token(path_match.group(0))
            if not _looks_like_code_reference(candidate):
                path = candidate

    if not path:
        return None

    body = "\n".join(lines[1:])

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

    snippet = _extract_json_snippet(content)
    if snippet:
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            # Guard: avoid re-executing tool calls embedded in sub-agent outputs.
            if "tool_name" in parsed and "tool_args" in parsed:
                return None

    allowed = set(allowed_tools) if allowed_tools is not None else None

    patch = _extract_patch_from_text(content or "")
    if patch and (allowed is None or "apply_patch" in allowed):
        return RecoveredToolCall(name="apply_patch", arguments={"patch": patch})

    file_block = _extract_file_from_text(content or "")
    if file_block and (allowed is None or "write_file" in allowed):
        path, body = file_block
        return RecoveredToolCall(name="write_file", arguments={"path": path, "content": body})

    if not snippet:
        return None

    if not isinstance(parsed, (dict, list)):
        return None

    candidates = [parsed] if isinstance(parsed, dict) else [x for x in parsed if isinstance(x, dict)]

    for candidate in candidates:
        recovered = _parse_tool_call_object(candidate)
        if not recovered:
            continue
        if allowed is not None and recovered.name not in allowed:
            continue
        return recovered

    return None


def _extract_tool_name_lenient(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r'"tool_name"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
        r'"tool"\s*:\s*"([^"]+)"',
        r'"function"\s*:\s*{\s*"name"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    return None


def _decode_json_string_fragment(value: str) -> str:
    if value is None:
        return ""
    try:
        return json.loads(f"\"{value}\"")
    except Exception:
        return value


def _extract_json_string_value(text: str, key: str) -> Optional[str]:
    if not text or not key:
        return None
    pattern = rf'"{re.escape(key)}"\s*:\s*"'
    match = re.search(pattern, text)
    if not match:
        return None
    start = match.end()
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "\"":
            raw_value = text[start:idx]
            return _decode_json_string_fragment(raw_value)
    raw_value = text[start:]
    return _decode_json_string_fragment(raw_value.rstrip())


def _extract_arguments_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    match = re.search(r'"arguments"\s*:\s*{', text)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    end = None
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        return None
    snippet = text[start:end]
    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def recover_tool_call_from_text_lenient(
    content: str,
    *,
    allowed_tools: Optional[Iterable[str]] = None,
) -> Optional[RecoveredToolCall]:
    """Best-effort recovery for JSON-like tool calls (handles truncated output)."""
    if not content:
        return None
    tool_name = _extract_tool_name_lenient(content)
    if not tool_name:
        return None
    allowed = set(allowed_tools) if allowed_tools is not None else None
    if allowed is not None and tool_name not in allowed:
        return None

    args_obj = _extract_arguments_object(content)
    if args_obj is not None:
        return RecoveredToolCall(name=tool_name, arguments=args_obj)

    tool_lower = tool_name.lower()
    if tool_lower in {"write_file", "append_to_file"}:
        path = _extract_json_string_value(content, "path")
        content_value = _extract_json_string_value(content, "content")
        if path and content_value is not None:
            return RecoveredToolCall(name=tool_name, arguments={"path": path, "content": content_value})
        return None

    if tool_lower == "replace_in_file":
        path = _extract_json_string_value(content, "path")
        find_value = _extract_json_string_value(content, "find") or _extract_json_string_value(content, "old_string")
        replace_value = _extract_json_string_value(content, "replace") or _extract_json_string_value(content, "new_string")
        if path and find_value is not None and replace_value is not None:
            return RecoveredToolCall(name=tool_name, arguments={"path": path, "find": find_value, "replace": replace_value})
        return None

    if tool_lower in {"move_file", "copy_file"}:
        src = _extract_json_string_value(content, "src") or _extract_json_string_value(content, "source")
        dest = _extract_json_string_value(content, "dest") or _extract_json_string_value(content, "path")
        if src and dest:
            return RecoveredToolCall(name=tool_name, arguments={"src": src, "dest": dest})
        return None

    if tool_lower in {"delete_file", "read_file", "get_file_info", "file_exists"}:
        path = _extract_json_string_value(content, "path")
        if path:
            return RecoveredToolCall(name=tool_name, arguments={"path": path})
        return None

    return None
