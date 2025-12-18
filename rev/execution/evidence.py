#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence summaries for tool outputs.

Goal: keep the LLM message history token-stable by storing full outputs on disk
and inlining only a short summary + an artifact handle.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _status_from_result(tool_result: str) -> str:
    payload = _try_parse_json(tool_result)
    if payload and isinstance(payload.get("error"), str) and payload.get("error"):
        return "error"
    return "success"


def summarize_tool_output(
    *,
    tool: str,
    args: Dict[str, Any],
    output: str,
    artifact_ref: str,
) -> Dict[str, Any]:
    """Create a compact evidence record for a tool output."""

    payload = _try_parse_json(output) or {}
    status = _status_from_result(output)

    summary = ""
    tool_lower = (tool or "").lower()

    if status == "error":
        err = payload.get("error") if isinstance(payload, dict) else None
        summary = f"{tool}: error: {err or 'unknown error'}"
    elif tool_lower == "replace_in_file":
        count = payload.get("replaced")
        file_ = payload.get("path_rel") or payload.get("file")
        summary = f"Updated {file_} ({count} replacements)" if file_ else f"replace_in_file applied ({count} replacements)"
    elif tool_lower == "write_file":
        wrote = payload.get("path_rel") or payload.get("wrote")
        bytes_ = payload.get("bytes")
        summary = f"Wrote {wrote} ({bytes_} bytes)" if wrote else "write_file applied"
    elif tool_lower == "create_directory":
        created = payload.get("path_rel") or payload.get("created")
        summary = f"Created directory {created}" if created else "create_directory applied"
    elif tool_lower == "delete_file":
        deleted = payload.get("path_rel") or payload.get("deleted")
        summary = f"Deleted {deleted}" if deleted else "delete_file applied"
    elif tool_lower in {"run_tests", "run_cmd"}:
        rc = payload.get("rc")
        stdout = payload.get("stdout", "") or ""
        stderr = payload.get("stderr", "") or ""
        out = (stdout + "\n" + stderr).strip()
        first = out.splitlines()[0] if out else ""
        summary = f"{tool} rc={rc} {first}".strip()
    elif tool_lower == "search_code":
        matches = payload.get("matches")
        if isinstance(matches, list):
            summary = f"Found {len(matches)} matches"
        else:
            summary = "search_code completed"
    elif tool_lower in {"git_diff", "tree_view", "analyze_code_structures", "run_all_analysis"}:
        summary = f"{tool} completed (see artifact)"
    else:
        preview = output.strip().replace("\r\n", "\n")
        preview = preview[:160].replace("\n", " ")
        summary = f"{tool} completed: {preview}".strip()

    return {
        "tool": tool,
        "result": status,
        "summary": summary[:400],
        "artifact_ref": artifact_ref,
    }

