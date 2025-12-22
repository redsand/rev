#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bundle Analysis.

Analyzes bundles for debugging and statistics.
"""

from typing import Dict, Any, List


def analyze_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a bundle and provide statistics.

    Args:
        bundle: Bundle to analyze

    Returns:
        Dictionary with:
            - total_tool_calls: Number of tool calls
            - total_llm_calls: Number of LLM calls
            - files_modified: Number of files modified
            - failures: List of failures
            - total_tokens: Total LLM tokens used
    """
    stats = {
        "total_tool_calls": 0,
        "total_llm_calls": 0,
        "files_modified": 0,
        "failures": [],
        "total_tokens": 0
    }

    # Count tool calls
    tool_calls = bundle.get("tool_calls", [])
    stats["total_tool_calls"] = len(tool_calls)

    # Check for tool failures
    for tool_call in tool_calls:
        if "error" in tool_call:
            stats["failures"].append({
                "type": "tool_error",
                "tool": tool_call.get("tool"),
                "error": tool_call.get("error")
            })

    # Count LLM calls and tokens
    llm_calls = bundle.get("llm_calls", [])
    stats["total_llm_calls"] = len(llm_calls)

    for llm_call in llm_calls:
        usage = llm_call.get("usage", {})
        stats["total_tokens"] += usage.get("prompt", 0) + usage.get("completion", 0)

    # Count file modifications
    file_modifications = bundle.get("file_modifications", [])
    stats["files_modified"] = len(file_modifications)

    # Check validations for failures
    validations = bundle.get("validations", [])
    for validation in validations:
        result = validation.get("result", {})
        rc = result.get("rc", 0)
        if rc != 0:
            stats["failures"].append({
                "type": "validation_failure",
                "validator": validation.get("validator"),
                "result": result
            })

    return stats
