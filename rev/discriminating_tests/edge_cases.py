#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Case Detector.

Identifies edge cases for parameters based on their types.
"""

from typing import Dict, List, Any


def detect_edge_cases(type_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect edge cases for a parameter based on its type.

    Args:
        type_info: Dictionary with:
            - param_name: Parameter name
            - param_type: Parameter type (e.g., "int", "str", "List[int]")
            - constraints: Optional constraints

    Returns:
        List of edge case dictionaries with:
            - value: Edge case value
            - description: Description of edge case
            - rationale: Why this is an edge case
            - expected_behavior: Optional expected behavior
    """
    param_type = type_info.get("param_type", "Any")
    edge_cases = []

    # Integer edge cases
    if "int" in param_type.lower() and "list" not in param_type.lower():
        edge_cases.extend([
            {
                "value": 0,
                "description": "zero",
                "rationale": "Common boundary condition",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": 1,
                "description": "one",
                "rationale": "Smallest positive integer, common off-by-one source",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": -1,
                "description": "negative_one",
                "rationale": "Negative values often handled differently",
                "expected_behavior": "should_handle_gracefully"
            }
        ])

        # If constraints mention >= 0, add negative edge case
        constraints = type_info.get("constraints", "")
        if constraints and ">=" in constraints and "0" in constraints:
            edge_cases.append({
                "value": -1,
                "description": "below_minimum",
                "rationale": "Test constraint violation",
                "expected_behavior": "should_raise"
            })

    # String edge cases
    elif "str" in param_type.lower() and "list" not in param_type.lower():
        edge_cases.extend([
            {
                "value": "",
                "description": "empty_string",
                "rationale": "Empty input is common edge case",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": " ",
                "description": "whitespace_only",
                "rationale": "Whitespace-only strings often cause issues",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": "test",
                "description": "normal_string",
                "rationale": "Typical valid input",
                "expected_behavior": "should_handle_gracefully"
            }
        ])

    # List edge cases
    elif "list" in param_type.lower():
        edge_cases.extend([
            {
                "value": [],
                "description": "empty_list",
                "rationale": "Empty collections are common edge cases",
                "expected_behavior": "should_return_empty"
            },
            {
                "value": [1],
                "description": "single_element",
                "rationale": "Single element lists often have special behavior",
                "expected_behavior": "should_handle_gracefully"
            }
        ])

    # Optional/None edge cases
    if "optional" in param_type.lower() or "none" in param_type.lower():
        edge_cases.append({
            "value": None,
            "description": "none_value",
            "rationale": "None is critical edge case for Optional types",
            "expected_behavior": "should_handle_gracefully"
        })

    # Dict edge cases
    elif "dict" in param_type.lower():
        edge_cases.extend([
            {
                "value": {},
                "description": "empty_dict",
                "rationale": "Empty dictionaries are common edge cases",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": None,
                "description": "none_value",
                "rationale": "None instead of dict",
                "expected_behavior": "should_handle_gracefully"
            }
        ])

    # Bool edge cases
    elif "bool" in param_type.lower():
        edge_cases.extend([
            {
                "value": True,
                "description": "true_value",
                "rationale": "Test true branch",
                "expected_behavior": "should_handle_gracefully"
            },
            {
                "value": False,
                "description": "false_value",
                "rationale": "Test false branch",
                "expected_behavior": "should_handle_gracefully"
            }
        ])

    return edge_cases
