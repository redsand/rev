#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent context provider backed by the ContextBuilder retrieval pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rev.core.context import RevContext
from rev.models.task import Task
from rev.retrieval.context_builder import ContextBuilder, ContextBundle
from rev import config


_BUILDER: ContextBuilder | None = None


def get_context_builder(root: Optional[Path] = None) -> ContextBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = ContextBuilder((root or Path.cwd()).resolve())
    return _BUILDER


def _collect_memory_items(context: RevContext) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []

    # Always include workspace root so sub-agents don’t drift.
    try:
        items.append(("workspace_root", str(config.ROOT)))
    except Exception:
        pass

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
) -> tuple[str, List[Dict[str, Any]], ContextBundle]:
    """Return rendered context + the (small) tool list to send to the LLM."""

    builder = get_context_builder()
    query = f"{context.user_request}\n\n{task.action_type}: {task.description}".strip()

    bundle = builder.build(
        query=query,
        tool_universe=tool_universe,
        tool_candidates=candidate_tool_names,
        top_k_tools=max_tools,
        memory_items=_collect_memory_items(context),
    )

    rendered = builder.render(bundle)
    selected_tool_schemas = [t.schema for t in bundle.selected_tool_schemas]
    if not selected_tool_schemas:
        # Fall back to the explicit candidate list (preserve existing behavior).
        allowed = set(candidate_tool_names)
        selected_tool_schemas = [t for t in tool_universe if t.get("function", {}).get("name") in allowed][:max_tools]

    context.agent_state["selected_tools"] = [t.get("function", {}).get("name") for t in selected_tool_schemas]
    return rendered, selected_tool_schemas, bundle
