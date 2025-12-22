#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Case Generator for Discriminating Tests.

Generates test cases that discriminate between correct and incorrect implementations.
"""

from typing import Dict, List, Any
from .edge_cases import detect_edge_cases


def generate_test_cases(function_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate discriminating test cases for a function.

    Args:
        function_info: Dictionary with:
            - name: Function name
            - signature: Function signature with type hints
            - docstring: Function documentation
            - existing_tests: List of existing test names

    Returns:
        List of test case dictionaries with:
            - description: What the test checks
            - code: Executable test code
            - rationale: Why this test is important
    """
    test_cases = []
    function_name = function_info.get("name", "function")
    signature = function_info.get("signature", "")
    existing_tests = set(function_info.get("existing_tests", []))

    # Parse parameter types from signature
    params = _parse_parameters(signature)

    # Generate edge case tests for each parameter
    for param_name, param_type in params.items():
        type_info = {
            "param_name": param_name,
            "param_type": param_type,
            "constraints": None
        }

        edge_cases = detect_edge_cases(type_info)

        for edge_case in edge_cases:
            test_name = f"test_{function_name}_{param_name}_{edge_case['description'].replace(' ', '_')}"

            # Skip if similar test already exists
            if any(test_name.lower() in existing.lower() for existing in existing_tests):
                continue

            test_code = _generate_test_code(
                function_name,
                param_name,
                edge_case["value"],
                edge_case.get("expected_behavior", "should_handle_gracefully")
            )

            test_cases.append({
                "description": f"Test {function_name} with {edge_case['description']}",
                "code": test_code,
                "rationale": edge_case.get("rationale", "Edge case coverage")
            })

    # If no specific edge cases generated, add some generic discriminating tests
    if not test_cases:
        test_cases.append({
            "description": f"Test {function_name} with typical input",
            "code": f"# assert {function_name}(...) == expected",
            "rationale": "Basic functionality test"
        })

    return test_cases


def _parse_parameters(signature: str) -> Dict[str, str]:
    """Parse parameter names and types from function signature.

    Args:
        signature: Function signature string

    Returns:
        Dictionary mapping parameter names to type strings
    """
    params = {}

    # Simple parsing: extract from "def func(param: type)" format
    if "(" not in signature or ")" not in signature:
        return params

    # Extract parameter list
    param_str = signature[signature.find("(") + 1:signature.find(")")]

    if not param_str.strip():
        return params

    # Split by comma and parse each parameter
    for param in param_str.split(","):
        param = param.strip()
        if ":" in param:
            name, type_hint = param.split(":", 1)
            params[name.strip()] = type_hint.strip()
        elif param:
            # No type hint
            params[param] = "Any"

    return params


def _generate_test_code(function_name: str, param_name: str, value: Any, expected_behavior: str) -> str:
    """Generate test code for a specific edge case.

    Args:
        function_name: Name of function to test
        param_name: Name of parameter being tested
        value: Edge case value
        expected_behavior: Expected behavior description

    Returns:
        Test code as string
    """
    # Format value for code
    if value is None:
        value_str = "None"
    elif isinstance(value, str):
        value_str = f"'{value}'"
    elif isinstance(value, list):
        value_str = str(value)
    else:
        value_str = str(value)

    # Generate assertion based on expected behavior
    if expected_behavior == "should_return_false":
        return f"assert {function_name}({value_str}) == False"
    elif expected_behavior == "should_return_true":
        return f"assert {function_name}({value_str}) == True"
    elif expected_behavior == "should_return_empty":
        return f"assert {function_name}({value_str}) == [] or {function_name}({value_str}) == ''"
    elif expected_behavior == "should_raise":
        return f"# Should handle gracefully or raise: {function_name}({value_str})"
    else:
        return f"assert {function_name}({value_str}) is not None  # TODO: Specify expected result"
