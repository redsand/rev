#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evidence Density Calculation.

Calculates how much evidence has been gathered during task execution.
Higher density → higher confidence in having sufficient information.
"""

from typing import Any


def calculate_evidence_density(context: Any) -> float:
    """Calculate evidence density from context.

    Evidence comes from:
    - Files read (code inspection)
    - Tool events (grep, glob, execute_python, etc.)
    - Validation results (tests, linting, type checking)

    Args:
        context: Execution context with files_read, tool_events, validation_results

    Returns:
        Evidence density score between 0.0 and 1.0
    """
    score = 0.0

    # Files read (up to 0.25 points)
    files_read = getattr(context, 'files_read', []) or []
    file_count = len(files_read) if hasattr(files_read, '__len__') else 0
    # Logarithmic scaling: 1 file=0.05, 5 files=0.15, 10 files=0.2, 20+ files=0.25
    if file_count > 0:
        file_score = min(0.25, 0.05 + (file_count / 20) * 0.2)
        score += file_score

    # Tool events (up to 0.25 points)
    tool_events = getattr(context, 'tool_events', []) or []
    tool_count = len(tool_events) if hasattr(tool_events, '__len__') else 0
    if tool_count > 0:
        # Each tool use provides evidence
        tool_score = min(0.25, tool_count * 0.03)
        score += tool_score

    # Validation results (up to 0.5 points - highest quality evidence)
    validation_results = getattr(context, 'validation_results', {}) or {}
    if validation_results:
        # Count successful validations
        successful_validations = 0
        for validator, result in validation_results.items():
            if isinstance(result, dict):
                rc = result.get('rc', 1)
                if rc == 0:
                    successful_validations += 1

        # Each successful validation is high-quality evidence
        # 2 validations = 0.5 points
        validation_score = min(0.5, successful_validations * 0.25)
        score += validation_score

    # Cap at 1.0
    return min(1.0, score)
