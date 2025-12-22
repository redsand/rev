#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discriminating Test Validator.

Validates that a test actually discriminates between correct and incorrect implementations.
"""

from typing import Dict, Any
import sys
from io import StringIO


def validate_discriminating_test(test_code: str, correct_impl: str, mutant_impl: str) -> Dict[str, Any]:
    """Validate that a test discriminates between correct and mutant implementations.

    A discriminating test should:
    - Pass on the correct implementation
    - Fail on the mutant implementation
    (or vice versa for negative tests)

    Args:
        test_code: Test code to validate
        correct_impl: Correct implementation code
        mutant_impl: Mutant (incorrect) implementation code

    Returns:
        Dictionary with:
            - discriminates: True if test discriminates
            - passes_on_correct: True if test passes on correct impl
            - fails_on_mutant: True if test fails on mutant
            - error: Error message if any
    """
    result = {
        "discriminates": False,
        "passes_on_correct": False,
        "fails_on_mutant": False,
        "status": "unknown"
    }

    # Safety check: reject dangerous code
    dangerous_patterns = ["import os", "import sys", "exec(", "eval(", "__import__"]
    if any(pattern in test_code for pattern in dangerous_patterns):
        result["status"] = "unsafe_code_detected"
        result["error"] = "Test code contains potentially dangerous operations"
        return result

    if any(pattern in correct_impl for pattern in dangerous_patterns):
        result["status"] = "unsafe_code_detected"
        result["error"] = "Implementation code contains potentially dangerous operations"
        return result

    # Test on correct implementation
    correct_result = _run_test_safely(test_code, correct_impl)
    result["passes_on_correct"] = correct_result["passed"]

    if not correct_result["passed"]:
        result["status"] = "fails_on_correct"
        result["error"] = correct_result.get("error", "Test failed on correct implementation")
        return result

    # Test on mutant implementation
    mutant_result = _run_test_safely(test_code, mutant_impl)
    result["fails_on_mutant"] = not mutant_result["passed"]

    # Test discriminates if it passes on correct but fails on mutant
    result["discriminates"] = result["passes_on_correct"] and result["fails_on_mutant"]

    if result["discriminates"]:
        result["status"] = "success"
    elif not result["fails_on_mutant"]:
        result["status"] = "does_not_discriminate"
        result["error"] = "Test passes on both correct and mutant implementations"

    return result


def _run_test_safely(test_code: str, impl_code: str) -> Dict[str, Any]:
    """Safely execute test code against implementation.

    Args:
        test_code: Test code to run
        impl_code: Implementation code to test

    Returns:
        Dictionary with:
            - passed: True if test passed
            - error: Error message if test failed
    """
    result = {"passed": False, "error": None}

    # Create isolated namespace
    namespace = {}

    try:
        # Execute implementation code to define function
        exec(impl_code, namespace)

        # Execute test code
        exec(test_code, namespace)

        # If we got here without exception, test passed
        result["passed"] = True

    except AssertionError as e:
        # Test failed (assertion failed)
        result["passed"] = False
        result["error"] = f"Assertion failed: {str(e)}"

    except Exception as e:
        # Other error (syntax error, runtime error, etc.)
        result["passed"] = False
        result["error"] = f"Execution error: {str(e)}"

    return result
