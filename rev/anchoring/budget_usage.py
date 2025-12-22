#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Budget Usage Calculation.

Calculates computational budget consumed during task execution.
Higher usage → less time remaining to gather evidence.
"""

from typing import Any


def calculate_budget_usage(context: Any) -> float:
    """Calculate budget usage from context.

    Budget is consumed by:
    - LLM calls (expensive, limited)
    - Tool calls (less expensive but still limited)

    Args:
        context: Execution context with llm_calls, tool_calls, max_llm_calls, max_tool_calls

    Returns:
        Budget usage score between 0.0 and 1.0
    """
    llm_calls = getattr(context, 'llm_calls', 0) or 0
    tool_calls = getattr(context, 'tool_calls', 0) or 0
    max_llm_calls = getattr(context, 'max_llm_calls', 100) or 100
    max_tool_calls = getattr(context, 'max_tool_calls', 500) or 500

    # Calculate usage as weighted average
    # LLM calls are more expensive, so they have higher weight (0.7)
    # Tool calls have lower weight (0.3)
    llm_usage = min(1.0, llm_calls / max_llm_calls) if max_llm_calls > 0 else 0.0
    tool_usage = min(1.0, tool_calls / max_tool_calls) if max_tool_calls > 0 else 0.0

    # Weighted combination
    budget_usage = (llm_usage * 0.7) + (tool_usage * 0.3)

    # Cap at 1.0
    return min(1.0, budget_usage)
