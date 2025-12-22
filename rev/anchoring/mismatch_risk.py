#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mismatch Risk Calculation.

Calculates uncertainty and conflicting information in current state.
Higher risk → lower confidence in correctness.
"""

from typing import Any


def calculate_mismatch_risk(context: Any) -> float:
    """Calculate mismatch risk from context.

    Risk factors include:
    - Failed validations (tests, linting, type errors)
    - Failed actions (edit failures, tool errors)
    - Conflicting tool results

    Args:
        context: Execution context with validation_results, failed_actions, tool_events

    Returns:
        Mismatch risk score between 0.0 and 1.0
    """
    risk = 0.0

    # Failed validations (up to 0.5 points)
    validation_results = getattr(context, 'validation_results', {}) or {}
    if validation_results:
        failed_validations = 0
        for validator, result in validation_results.items():
            if isinstance(result, dict):
                rc = result.get('rc', 0)
                if rc != 0:
                    failed_validations += 1

        # Each failed validation adds risk
        validation_risk = min(0.5, failed_validations * 0.25)
        risk += validation_risk

    # Failed actions (up to 0.4 points)
    failed_actions = getattr(context, 'failed_actions', []) or []
    failed_count = len(failed_actions) if hasattr(failed_actions, '__len__') else 0
    if failed_count > 0:
        # Each failed action indicates mismatch between expectation and reality
        # 2 failures = 0.4 risk
        action_risk = min(0.4, failed_count * 0.2)
        risk += action_risk

    # Conflicting tool results (up to 0.1 points)
    # This is harder to detect automatically, so we'll use a heuristic:
    # If we have many tool events but few successful outcomes, that's suspicious
    tool_events = getattr(context, 'tool_events', []) or []
    tool_count = len(tool_events) if hasattr(tool_events, '__len__') else 0

    # Check for conflicting tool results
    # If tool_events exist but no validation_results, that's a potential conflict
    if tool_count >= 2 and not validation_results:
        # Tools used but no validation - potential inconsistency
        conflict_risk = 0.1
        risk += conflict_risk
    elif tool_count > 5:
        # Many tool calls with failed validation suggests confusion/conflict
        if validation_results and any(
            result.get('rc', 0) != 0
            for result in validation_results.values()
            if isinstance(result, dict)
        ):
            conflict_risk = 0.1
            risk += conflict_risk

    # Cap at 1.0
    return min(1.0, risk)
