#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent context provider backed by the ContextBuilder retrieval pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rev.core.context import RevContext
from rev.models.task import Task
from rev.retrieval.context_builder import ContextBuilder, ContextBundle
from rev import config


_BUILDER: ContextBuilder | None = None

_PATH_STRIP_CHARS = "\"'`.,;:)]}>"


def _extract_target_paths(description: str) -> List[str]:
    if not description:
        return []
    patterns = [
        r'`([^`]+)`',
        r'"([^"]+)"',
        r"'([^']+)'",
        r'\b([A-Za-z]:\\[^\s]+)\b',
        r'\b(/[^\s]+)\b',
        r'\b([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,8})\b',
        r'\b(\.[A-Za-z0-9_.-]+)\b',
    ]
    candidates: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, description):
            if not match:
                continue
            token = str(match).strip(_PATH_STRIP_CHARS)
            if not token:
                continue
            if " " in token:
                continue
            candidates.append(token)
    # Deduplicate while preserving order
    seen = set()
    deduped: List[str] = []
    for token in candidates:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _resolve_existing_paths(root: Path, paths: Iterable[str]) -> List[Path]:
    resolved: List[Path] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / raw
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            key = str(candidate.resolve())
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def get_context_builder(root: Optional[Path] = None) -> ContextBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = ContextBuilder((root or Path.cwd()).resolve())
    return _BUILDER


def _collect_memory_items(context: RevContext) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []

    # Always include workspace root so sub-agents don't drift.
    try:
        items.append(("workspace_root", str(config.ROOT)))
    except Exception:
        pass
    if getattr(config, "WORKSPACE_ROOT_ONLY", False):
        items.append(("path_policy", "Workspace root only; use workspace-relative paths (no set_workdir)."))

    # Errors (often the most relevant "memory" signal)
    for i, err in enumerate(context.errors[-10:], start=1):
        items.append((f"error[{i}]", str(err)))

    # Insights (truncate large values)
    for k, v in list(context.agent_insights.items())[-30:]:
        try:
            text = v if isinstance(v, str) else json.dumps(v, indent=2)[:2000]
        except Exception:
            text = str(v)[:2000]
        items.append((f"insight:{k}", text))

    # Clarification history
    for i, entry in enumerate(context.clarification_history[-10:], start=1):
        try:
            items.append((f"clarification[{i}]", json.dumps(entry, indent=2)[:2000]))
        except Exception:
            items.append((f"clarification[{i}]", str(entry)[:2000]))

    # Recently selected tools (helps avoid repeated ref/grep loops)
    selected = context.agent_state.get("selected_tools") or []
    if selected:
        items.append(("selected_tools", ", ".join(selected[:10])))

    # Recent task summaries to keep planner grounded.
    recent_tasks = context.agent_state.get("recent_tasks") or []
    if isinstance(recent_tasks, list) and recent_tasks:
        items.append(("recent_tasks", "; ".join(recent_tasks[-5:])))

    # System Information (Platform awareness)
    try:
        sys_info = config.get_system_info_cached()
        items.append(("os", sys_info.get("os", "unknown")))
        items.append(("platform", sys_info.get("platform", "unknown")))
        items.append(("shell_type", sys_info.get("shell_type", "unknown")))
    except Exception:
        pass

    return items


def build_context_and_tools(
    task: Task,
    context: RevContext,
    *,
    tool_universe: Sequence[Dict[str, Any]],
    candidate_tool_names: Sequence[str],
    max_tools: int = 7,
    force_tool_names: Optional[Sequence[str]] = None,
) -> tuple[str, List[Dict[str, Any]], ContextBundle]:
    """Return rendered context + the (small) tool list to send to the LLM."""

    builder = get_context_builder()
    query = f"{context.user_request}\n\n{task.action_type}: {task.description}".strip()
    target_paths = _resolve_existing_paths(builder.root, _extract_target_paths(task.description or ""))

    if target_paths:
        config_paths = builder.discover_config_files(target_paths)
        bundle = builder.build_minimal(
            query=query,
            tool_universe=tool_universe,
            tool_candidates=candidate_tool_names,
            target_paths=target_paths,
            config_paths=config_paths,
            top_k_tools=max_tools,
            memory_items=_collect_memory_items(context),
        )
    else:
        bundle = builder.build(
            query=query,
            tool_universe=tool_universe,
            tool_candidates=candidate_tool_names,
            top_k_tools=max_tools,
            memory_items=_collect_memory_items(context),
        )

    rendered = builder.render(bundle)
    selected_tool_schemas = [t.schema for t in bundle.selected_tool_schemas]

    # CRITICAL FIX: Always filter to only allowed candidate tools
    # The retrieval system may return tools not in candidate_tool_names based on semantic similarity
    # We must enforce the constraint regardless of what retrieval returns
    # This prevents wrong tools from being available (e.g., read_file for ADD tasks that should only have write_file)
    if candidate_tool_names:
        allowed = set(candidate_tool_names)
        selected_tool_schemas = [
            t for t in selected_tool_schemas
            if t.get("function", {}).get("name") in allowed
        ]

    # If filtering removed all tools, fall back to explicit candidate list
    if not selected_tool_schemas and candidate_tool_names:
        allowed = set(candidate_tool_names)
        selected_tool_schemas = [
            t for t in tool_universe
            if t.get("function", {}).get("name") in allowed
        ][:max_tools]

    if force_tool_names:
        forced = [name for name in force_tool_names if isinstance(name, str) and name.strip()]
        if forced:
            existing = {t.get("function", {}).get("name") for t in selected_tool_schemas}
            for name in forced:
                if name in existing:
                    continue
                for tool in tool_universe:
                    if tool.get("function", {}).get("name") == name:
                        selected_tool_schemas.append(tool)
                        existing.add(name)
                        break

            if max_tools and len(selected_tool_schemas) > max_tools:
                forced_set = set(forced)
                nonforced_limit = max_tools - len(forced_set)
                nonforced_added = 0
                trimmed: List[Dict[str, Any]] = []
                for tool in selected_tool_schemas:
                    name = tool.get("function", {}).get("name")
                    if name in forced_set:
                        trimmed.append(tool)
                        continue
                    if nonforced_limit < 0:
                        continue
                    if nonforced_added < nonforced_limit:
                        trimmed.append(tool)
                        nonforced_added += 1
                selected_tool_schemas = trimmed

    context.agent_state["selected_tools"] = [t.get("function", {}).get("name") for t in selected_tool_schemas]
    return rendered, selected_tool_schemas, bundle
