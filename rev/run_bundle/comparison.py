#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bundle Comparison.

Compares two bundles to find differences.
"""

from typing import Dict, Any, List


def compare_bundles(bundle1: Dict[str, Any], bundle2: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two bundles and identify differences.

    Args:
        bundle1: First bundle
        bundle2: Second bundle

    Returns:
        Dictionary with:
            - differences: List of differences
            - missing_in_bundle2: Steps present in bundle1 but not bundle2
            - missing_in_bundle1: Steps present in bundle2 but not bundle1
    """
    comparison = {
        "differences": [],
        "missing_in_bundle2": [],
        "missing_in_bundle1": []
    }

    # Compare requests
    if bundle1.get("request") != bundle2.get("request"):
        comparison["differences"].append({
            "field": "request",
            "bundle1_value": bundle1.get("request"),
            "bundle2_value": bundle2.get("request")
        })

    # Compare tool calls
    tool_calls1 = bundle1.get("tool_calls", [])
    tool_calls2 = bundle2.get("tool_calls", [])

    # Check length difference
    if len(tool_calls1) != len(tool_calls2):
        comparison["differences"].append({
            "field": "tool_calls_count",
            "bundle1_count": len(tool_calls1),
            "bundle2_count": len(tool_calls2)
        })

    # Compare individual tool calls
    for i in range(min(len(tool_calls1), len(tool_calls2))):
        tc1 = tool_calls1[i]
        tc2 = tool_calls2[i]

        if tc1.get("tool") != tc2.get("tool"):
            comparison["differences"].append({
                "field": f"tool_call[{i}].tool",
                "bundle1_value": tc1.get("tool"),
                "bundle2_value": tc2.get("tool")
            })

        if tc1.get("result") != tc2.get("result"):
            comparison["differences"].append({
                "field": f"tool_call[{i}].result",
                "bundle1_value": tc1.get("result"),
                "bundle2_value": tc2.get("result")
            })

    # Identify missing steps
    if len(tool_calls1) > len(tool_calls2):
        for i in range(len(tool_calls2), len(tool_calls1)):
            comparison["missing_in_bundle2"].append({
                "type": "tool_call",
                "index": i,
                "tool": tool_calls1[i].get("tool")
            })

    if len(tool_calls2) > len(tool_calls1):
        for i in range(len(tool_calls1), len(tool_calls2)):
            comparison["missing_in_bundle1"].append({
                "type": "tool_call",
                "index": i,
                "tool": tool_calls2[i].get("tool")
            })

    return comparison
