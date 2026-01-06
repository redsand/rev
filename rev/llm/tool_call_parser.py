"""Lightweight fallback parser to recover tool calls from assistant text output.

This is used when the model fails to emit native tool_calls but returns JSON or XML
formatted tool calls in the message content.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple


def _as_tool_call(name: str, arguments: Any, counter: int, seen_ids: set[str]) -> Dict[str, Any]:
    """Normalize a parsed tool call into the standard structure and dedupe IDs."""
    # Ensure arguments is JSON-serializable string
    try:
        arg_str = json.dumps(arguments)
    except Exception:
        arg_str = json.dumps({})
    tool_id = f"tc-recovered-{counter}"
    while tool_id in seen_ids:
        counter += 1
        tool_id = f"tc-recovered-{counter}"
    seen_ids.add(tool_id)
    return {
        "id": tool_id,
        "function": {
            "name": name.strip(),
            "arguments": arg_str,
        },
    }


def _parse_json_obj(obj: Any, counter: int, errors: List[str], calls: List[Dict[str, Any]], seen_ids: set[str]) -> int:
    """Parse JSON objects or arrays into tool calls."""
    if isinstance(obj, dict):
        # Direct tool call object - support multiple naming conventions
        name = obj.get("name") or obj.get("tool_name") or obj.get("tool")
        arguments = obj.get("arguments") or obj.get("parameters") or obj.get("args")
        
        if name and arguments is not None:
            calls.append(_as_tool_call(name, arguments, counter, seen_ids))
            return counter + 1
            
        # OpenAI-style tool_calls wrapper
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
            for tc in obj["tool_calls"]:
                if not isinstance(tc, dict):
                    continue
                tc_name = tc.get("name") or tc.get("function", {}).get("name") or tc.get("tool_name")
                tc_args = tc.get("arguments") or tc.get("function", {}).get("arguments") or tc.get("parameters") or tc.get("args") or {}
                if tc_name is None:
                    errors.append("Malformed tool call: missing name")
                    continue
                calls.append(_as_tool_call(tc_name, tc_args if isinstance(tc_args, (dict, list, str)) else {}, counter, seen_ids))
                counter += 1
            return counter
    if isinstance(obj, list):
        for item in obj:
            counter = _parse_json_obj(item, counter, errors, calls, seen_ids)
    return counter


def _extract_json_candidates(content: str) -> List[str]:
    """Collect potential JSON snippets from content (code fences and inline objects)."""
    candidates: List[str] = []
    fence_pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    candidates.extend(match.group(1).strip() for match in fence_pattern.finditer(content))

    # Inline JSON objects with "name" or "tool_name" and "arguments" or "parameters"
    inline_pattern = re.compile(r"\{[^{}]*\"(?:tool_)?name\"[^{}]*\"(?:arguments|parameters)\"\s*:\s*\{.*?\}", re.DOTALL)
    candidates.extend(match.group(0).strip() + "}" for match in inline_pattern.finditer(content))

    # Whole content as a candidate
    candidates.append(content.strip())
    return [c for c in candidates if c]


def _parse_xml_snippets(content: str, counter: int, errors: List[str], calls: List[Dict[str, Any]], seen_ids: set[str]) -> Tuple[int, List[str]]:
    """Parse XML-formatted tool calls."""
    xml_candidates: List[str] = []
    tool_call_blocks = re.findall(r"<tool_call>.*?</tool_call>", content, flags=re.DOTALL | re.IGNORECASE)
    if tool_call_blocks:
        xml_candidates.extend(tool_call_blocks)
    elif "<" in content and ">" in content:
        # Fallback: try the whole content
        xml_candidates.append(content)

    for snippet in xml_candidates:
        try:
            root = ET.fromstring(snippet)
        except Exception as exc:  # pragma: no cover - only on malformed XML
            errors.append(f"Malformed XML tool call: {exc}")
            continue

        # A valid tool call should have a tool name (root or first child) and children as params
        tool_elems = [root] if root.tag != "tool_call" else list(root)
        for elem in tool_elems:
            if len(list(elem)) == 0:
                # Needs parameter children
                continue
            args = {child.tag: (child.text or "").strip() for child in elem}
            calls.append(_as_tool_call(elem.tag, args, counter, seen_ids))
            counter += 1
    return counter, errors


def parse_tool_calls_from_text(content: str) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """Attempt to recover tool calls from assistant text.

    Returns (tool_calls, cleaned_content, errors).
    """
    tool_calls: List[Dict[str, Any]] = []
    errors: List[str] = []
    counter = 1
    seen_ids: set[str] = set()

    # JSON candidates
    for candidate in _extract_json_candidates(content):
        try:
            parsed = json.loads(candidate)
        except Exception as exc:
            errors.append(f"Malformed JSON tool call: {exc}")
            continue
        counter = _parse_json_obj(parsed, counter, errors, tool_calls, seen_ids)

    # XML candidates
    counter, errors = _parse_xml_snippets(content, counter, errors, tool_calls, seen_ids)

    # Remove matched blocks from content
    cleaned = content
    if tool_calls:
        # Remove JSON blocks
        cleaned = re.sub(r"```(?:json)?\\s*.*?```", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"\\{[^{}]*\"name\"[^{}]*\"arguments\"\\s*:\\s*\\{.*?\\}[^{}]*\\}", "", cleaned, flags=re.DOTALL)
        # Remove XML blocks
        cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = cleaned.strip()

    return tool_calls, cleaned, errors
