#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standard sub-agent I/O: summarized results + evidence + patch plan.

Sub-agents execute tools, but must return standardized outputs:
- result_summary (short)
- patch_plan (files + intent)
- evidence (artifact refs, tests/commands)
- risks_assumptions
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from rev.execution.artifacts import write_tool_output_artifact
from rev.execution.evidence import summarize_tool_output
from rev.core.context import RevContext


def _patch_plan_from_tool(tool: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    tool_lower = (tool or "").lower()
    plan: List[Dict[str, Any]] = []
    if tool_lower in {"write_file", "replace_in_file", "append_to_file", "delete_file", "read_file"}:
        path = args.get("path") or args.get("file_path")
        if isinstance(path, str) and path.strip():
            intent = {
                "write_file": "create/update file content",
                "replace_in_file": "modify file content",
                "append_to_file": "append content",
                "delete_file": "delete file",
                "read_file": "read file for context",
            }.get(tool_lower, "change file")
            plan.append({"path": path, "intent": intent})
    elif tool_lower == "create_directory":
        path = args.get("path")
        if isinstance(path, str) and path.strip():
            plan.append({"path": path, "intent": "create directory"})
    elif tool_lower in {"run_cmd", "run_tests"}:
        cmd = args.get("cmd")
        if isinstance(cmd, str) and cmd.strip():
            plan.append({"path": None, "intent": f"run: {cmd[:120]}"})
    return plan


def build_subagent_output(
    *,
    agent_name: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_output: str,
    context: RevContext,
    task_id: Optional[str] = None,
) -> str:
    """Return a JSON string representing standardized sub-agent output."""

    artifact, meta = write_tool_output_artifact(
        tool=tool_name,
        args=tool_args if isinstance(tool_args, dict) else {"args": tool_args},
        output=tool_output,
        session_id=getattr(context, "session_id", None) or context.agent_state.get("session_id"),
        task_id=str(task_id) if task_id is not None else None,
        step_id=context.agent_state.get("current_iteration"),
        agent_name=agent_name,
    )
    evidence = summarize_tool_output(
        tool=tool_name,
        args=tool_args if isinstance(tool_args, dict) else {"args": tool_args},
        output=tool_output,
        artifact_ref=artifact.as_posix(),
    )
    evidence["artifact_meta"] = meta

    payload = {
        "result_summary": evidence.get("summary", "")[:400],
        "patch_plan": _patch_plan_from_tool(tool_name, tool_args),
        "evidence": [evidence],
        "risks_assumptions": [],
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_output": tool_output,
    }
    return json.dumps(payload, ensure_ascii=False)

