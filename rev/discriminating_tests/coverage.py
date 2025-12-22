#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Coverage Analysis.

Analyzes existing tests to identify gaps and calculate coverage.
"""

from typing import List, Dict, Any
import ast
import re


def identify_untested_paths(function_code: str, existing_tests: List[str]) -> List[Dict[str, Any]]:
    """Identify code paths not covered by existing tests.

    Args:
        function_code: Function source code
        existing_tests: List of existing test code

    Returns:
        List of untested path descriptions
    """
    untested = []

    # Simple heuristic: find conditional branches
    branches = _extract_branches(function_code)

    # Check which values are tested
    tested_values = set()
    for test in existing_tests:
        # Extract tested values from assertions
        values = _extract_test_values(test)
        tested_values.update(values)

    # Identify untested branches
    for branch in branches:
        branch_value = branch.get("value")
        if branch_value is not None and str(branch_value) not in tested_values:
            untested.append({
                "type": "branch",
                "condition": branch.get("condition", "unknown"),
                "value": branch_value,
                "description": f"Branch with value {branch_value} not tested"
            })

    # If no branches found, at least check if empty/None cases are tested
    if not untested:
        # Check for common edge cases
        common_edge_cases = ["0", "None", "[]", "''", "-1", "1"]
        for edge_case in common_edge_cases:
            if edge_case not in tested_values and edge_case not in str(tested_values):
                untested.append({
                    "type": "edge_case",
                    "value": edge_case,
                    "description": f"Common edge case {edge_case} not tested"
                })

    return untested


def calculate_branch_coverage(function_code: str, existing_tests: List[str]) -> float:
    """Calculate branch coverage percentage.

    Args:
        function_code: Function source code
        existing_tests: List of existing test code

    Returns:
        Coverage percentage (0.0 to 1.0)
    """
    branches = _extract_branches(function_code)

    if not branches:
        # No branches = 100% coverage if any test exists
        return 1.0 if existing_tests else 0.0

    # Extract tested values
    tested_values = set()
    for test in existing_tests:
        values = _extract_test_values(test)
        tested_values.update(values)

    # Count how many branches are covered
    covered = 0
    for branch in branches:
        branch_value = branch.get("value")
        if branch_value is not None and str(branch_value) in tested_values:
            covered += 1

    # Calculate coverage
    coverage = covered / len(branches) if branches else 1.0

    return max(0.0, min(1.0, coverage))


def _extract_branches(code: str) -> List[Dict[str, Any]]:
    """Extract conditional branches from code.

    Args:
        code: Source code

    Returns:
        List of branch information dictionaries
    """
    branches = []

    # Find if statements
    if_pattern = r'if\s+(.+?):'
    matches = re.finditer(if_pattern, code)

    for match in matches:
        condition = match.group(1).strip()

        # Try to extract comparison value
        value = None
        if "==" in condition:
            parts = condition.split("==")
            if len(parts) == 2:
                value = parts[1].strip().strip('"').strip("'")
        elif "<" in condition or ">" in condition:
            # Extract number from comparisons
            numbers = re.findall(r'\b\d+\b', condition)
            if numbers:
                value = numbers[0]

        branches.append({
            "condition": condition,
            "value": value,
            "type": "if"
        })

    # Find elif statements
    elif_pattern = r'elif\s+(.+?):'
    matches = re.finditer(elif_pattern, code)

    for match in matches:
        condition = match.group(1).strip()

        value = None
        if "==" in condition:
            parts = condition.split("==")
            if len(parts) == 2:
                value = parts[1].strip().strip('"').strip("'")

        branches.append({
            "condition": condition,
            "value": value,
            "type": "elif"
        })

    return branches


def _extract_test_values(test_code: str) -> List[str]:
    """Extract values being tested from test code.

    Args:
        test_code: Test code string

    Returns:
        List of tested values as strings
    """
    values = []

    # Extract values from assertions like "assert func(5)"
    # Match numbers
    numbers = re.findall(r'\b\d+\b', test_code)
    values.extend(numbers)

    # Match negative numbers
    neg_numbers = re.findall(r'-\d+', test_code)
    values.extend(neg_numbers)

    # Match strings
    strings = re.findall(r'"([^"]*)"', test_code)
    values.extend(strings)

    strings = re.findall(r"'([^']*)'", test_code)
    values.extend(strings)

    # Check for None
    if "None" in test_code:
        values.append("None")

    # Check for empty lists/dicts
    if "[]" in test_code:
        values.append("[]")

    if "{}" in test_code:
        values.append("{}")

    return [str(v) for v in values]
