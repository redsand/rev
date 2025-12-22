#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Discriminating-Tests Generator.

A discriminating test is one that passes on the correct implementation
but fails on plausible incorrect implementations (or vice versa).

This helps verify that:
1. Tests are actually testing the right behavior
2. Edge cases are covered
3. Implementation is robust against common mistakes
"""

import unittest
from unittest.mock import Mock, MagicMock
from typing import Dict, List, Any


class TestTestCaseGenerator(unittest.TestCase):
    """Test generation of discriminating test cases."""

    def test_generate_edge_cases_for_function(self):
        """Generator should create edge case tests for a function."""
        from rev.discriminating_tests.generator import generate_test_cases

        # Example function signature and behavior
        function_info = {
            "name": "is_prime",
            "signature": "def is_prime(n: int) -> bool",
            "docstring": "Returns True if n is prime, False otherwise",
            "existing_tests": ["test_prime_2", "test_prime_3"]
        }

        test_cases = generate_test_cases(function_info)

        self.assertIsInstance(test_cases, list)
        self.assertGreater(len(test_cases), 0)

        # Should suggest edge cases like 0, 1, negative numbers
        test_case_descriptions = [tc["description"] for tc in test_cases]
        self.assertTrue(any("0" in desc or "negative" in desc or "1" in desc
                           for desc in test_case_descriptions))

    def test_generate_tests_for_boundary_conditions(self):
        """Generator should create boundary condition tests."""
        from rev.discriminating_tests.generator import generate_test_cases

        function_info = {
            "name": "find_index",
            "signature": "def find_index(arr: List[int], target: int) -> int",
            "docstring": "Returns index of target in arr, -1 if not found",
            "existing_tests": ["test_find_middle"]
        }

        test_cases = generate_test_cases(function_info)

        # Should suggest: empty array, first element, last element, not found
        test_descriptions = [tc["description"].lower() for tc in test_cases]
        boundary_tests = ["empty", "first", "last", "not found"]

        # At least some boundary conditions should be suggested
        suggested = sum(1 for boundary in boundary_tests
                       if any(boundary in desc for desc in test_descriptions))
        self.assertGreater(suggested, 0)

    def test_generate_tests_includes_test_code(self):
        """Generated test cases should include executable test code."""
        from rev.discriminating_tests.generator import generate_test_cases

        function_info = {
            "name": "add",
            "signature": "def add(a: int, b: int) -> int",
            "docstring": "Returns sum of a and b",
            "existing_tests": []
        }

        test_cases = generate_test_cases(function_info)

        # Each test case should have code
        for test_case in test_cases:
            self.assertIn("code", test_case)
            self.assertIn("assert", test_case["code"])

    def test_generate_tests_avoids_duplicates(self):
        """Generator should not suggest tests that already exist."""
        from rev.discriminating_tests.generator import generate_test_cases

        function_info = {
            "name": "is_even",
            "signature": "def is_even(n: int) -> bool",
            "docstring": "Returns True if n is even",
            "existing_tests": [
                "test_even_positive",
                "test_even_negative",
                "test_even_zero"
            ]
        }

        test_cases = generate_test_cases(function_info)

        # Should generate fewer suggestions since coverage is already good
        # Or suggest more complex edge cases
        self.assertIsInstance(test_cases, list)


class TestEdgeCaseDetector(unittest.TestCase):
    """Test edge case detection for code."""

    def test_detect_edge_cases_from_type_signature(self):
        """Detector should identify edge cases from type signatures."""
        from rev.discriminating_tests.edge_cases import detect_edge_cases

        type_info = {
            "param_name": "count",
            "param_type": "int",
            "constraints": "count >= 0"
        }

        edge_cases = detect_edge_cases(type_info)

        self.assertIsInstance(edge_cases, list)
        # Should suggest: 0, 1, large number, etc.
        self.assertTrue(any(ec["value"] == 0 for ec in edge_cases))

    def test_detect_edge_cases_for_list_type(self):
        """Detector should identify edge cases for list parameters."""
        from rev.discriminating_tests.edge_cases import detect_edge_cases

        type_info = {
            "param_name": "items",
            "param_type": "List[int]",
            "constraints": None
        }

        edge_cases = detect_edge_cases(type_info)

        # Should suggest: empty list, single item, duplicates
        edge_case_descriptions = [ec["description"].lower() for ec in edge_cases]
        self.assertTrue(any("empty" in desc for desc in edge_case_descriptions))

    def test_detect_edge_cases_for_string_type(self):
        """Detector should identify edge cases for string parameters."""
        from rev.discriminating_tests.edge_cases import detect_edge_cases

        type_info = {
            "param_name": "text",
            "param_type": "str",
            "constraints": None
        }

        edge_cases = detect_edge_cases(type_info)

        # Should suggest: empty string, whitespace, special characters
        descriptions = [ec["description"].lower() for ec in edge_cases]
        self.assertTrue(any("empty" in desc or "whitespace" in desc
                           for desc in descriptions))

    def test_detect_edge_cases_for_optional_type(self):
        """Detector should identify None as edge case for Optional types."""
        from rev.discriminating_tests.edge_cases import detect_edge_cases

        type_info = {
            "param_name": "config",
            "param_type": "Optional[Dict]",
            "constraints": None
        }

        edge_cases = detect_edge_cases(type_info)

        # Should suggest None as an edge case
        self.assertTrue(any(ec.get("value") is None for ec in edge_cases))


class TestMutantAnalysis(unittest.TestCase):
    """Test mutant analysis for discriminating tests."""

    def test_generate_mutants_for_code(self):
        """Generate plausible incorrect implementations (mutants)."""
        from rev.discriminating_tests.mutants import generate_mutants

        original_code = """
def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True
"""

        mutants = generate_mutants(original_code)

        self.assertIsInstance(mutants, list)
        self.assertGreater(len(mutants), 0)

        # Each mutant should have code and description
        for mutant in mutants:
            self.assertIn("code", mutant)
            self.assertIn("description", mutant)
            self.assertNotEqual(mutant["code"], original_code)

    def test_mutants_include_off_by_one_errors(self):
        """Common mutant: off-by-one errors."""
        from rev.discriminating_tests.mutants import generate_mutants

        original_code = """
def get_last_index(arr):
    return len(arr) - 1
"""

        mutants = generate_mutants(original_code)

        # Should include mutant with "len(arr)" instead of "len(arr) - 1"
        mutant_codes = [m["code"] for m in mutants]
        self.assertTrue(any("len(arr)" in code and "- 1" not in code
                           for code in mutant_codes))

    def test_mutants_include_boundary_condition_errors(self):
        """Common mutant: wrong boundary conditions."""
        from rev.discriminating_tests.mutants import generate_mutants

        original_code = """
def is_valid_age(age):
    return age >= 0 and age <= 120
"""

        mutants = generate_mutants(original_code)

        # Should include mutants with < instead of <=, etc.
        descriptions = [m["description"].lower() for m in mutants]
        self.assertTrue(any("boundary" in desc or "comparison" in desc
                           for desc in descriptions))


class TestDiscriminatingTestValidator(unittest.TestCase):
    """Test validation that tests actually discriminate."""

    def test_validate_test_discriminates(self):
        """Validator should check if test passes on correct impl, fails on mutants."""
        from rev.discriminating_tests.validator import validate_discriminating_test

        test_code = "assert is_prime(4) == False"  # 4 is not prime
        correct_impl = "def is_prime(n):\n    if n <= 1: return False\n    if n == 2: return True\n    return all(n % i != 0 for i in range(2, n))"
        mutant_impl = "def is_prime(n):\n    return n > 1"  # Wrong: doesn't check divisibility, will return True for 4

        result = validate_discriminating_test(test_code, correct_impl, mutant_impl)

        self.assertIn("discriminates", result)
        self.assertTrue(result["discriminates"])
        self.assertIn("passes_on_correct", result)
        self.assertIn("fails_on_mutant", result)

    def test_non_discriminating_test_detected(self):
        """Validator should detect when test doesn't discriminate."""
        from rev.discriminating_tests.validator import validate_discriminating_test

        test_code = "assert is_prime(1) == False"  # Both impls agree on this
        correct_impl = "def is_prime(n):\n    if n <= 1: return False\n    return True"
        mutant_impl = "def is_prime(n):\n    if n <= 1: return False\n    return n > 10"  # Wrong but agrees on n=1

        result = validate_discriminating_test(test_code, correct_impl, mutant_impl)

        # Test passes on both, so it doesn't discriminate
        self.assertFalse(result["discriminates"])

    def test_validator_runs_test_safely(self):
        """Validator should safely execute test code."""
        from rev.discriminating_tests.validator import validate_discriminating_test

        # Malicious test code should be caught
        test_code = "import os; os.system('echo bad')"
        correct_impl = "def foo(): pass"
        mutant_impl = "def foo(): return 1"

        result = validate_discriminating_test(test_code, correct_impl, mutant_impl)

        # Should detect as unsafe
        self.assertIn("unsafe", result.get("status", "").lower())
        self.assertIn("error", result)


class TestIntegrationWithDebateMode(unittest.TestCase):
    """Test integration of discriminating tests with debate mode."""

    def test_skeptic_requests_discriminating_test(self):
        """Skeptic should request discriminating tests as evidence."""
        from rev.debate.skeptic import SkepticAgent

        # Mock LLM to return evidence request for discriminating test
        def mock_llm(**kwargs):
            return '''```json
{
  "gaps": ["No test that distinguishes correct from plausible incorrect implementations"],
  "evidence_requests": [
    {
      "type": "discriminating_test",
      "description": "Generate test that passes on proposed solution but fails on common mistakes",
      "rationale": "Verify solution handles edge cases correctly"
    }
  ],
  "counter_examples": []
}
```'''

        skeptic = SkepticAgent(llm_client=mock_llm)

        proposal = {
            "solution": "Use startswith() for module matching",
            "assumptions": ["All submodules start with parent name"],
            "evidence": [],
            "confidence": 0.7
        }

        critique = skeptic.critique(proposal)

        # Should request discriminating test
        self.assertTrue(any(
            req.get("type") == "discriminating_test"
            for req in critique["evidence_requests"]
        ))

    def test_proposer_includes_discriminating_test_evidence(self):
        """Proposer should include discriminating test results as evidence."""
        from rev.debate.proposer import ProposerAgent

        def mock_llm(**kwargs):
            return '''```json
{
  "solution": "Fix import logic",
  "assumptions": ["Module hierarchy is correct"],
  "evidence": [
    {
      "source": "discriminating_test:test_edge_case",
      "description": "Test passes on solution, fails on naive implementation"
    }
  ],
  "reasoning": ["Generated test", "Validated it discriminates"],
  "confidence": 0.9
}
```'''

        proposer = ProposerAgent(llm_client=mock_llm)
        context = Mock()
        context.request = "Fix bug"
        context.files_read = []
        context.tool_events = []
        context.work_history = []

        proposal = proposer.propose(context)

        # Should have discriminating test in evidence
        self.assertTrue(any(
            "discriminating_test" in ev.get("source", "")
            for ev in proposal["evidence"]
        ))


class TestTestCoverageAnalysis(unittest.TestCase):
    """Test analysis of existing test coverage to find gaps."""

    def test_identify_untested_code_paths(self):
        """Analyzer should identify code paths not covered by tests."""
        from rev.discriminating_tests.coverage import identify_untested_paths

        function_code = """
def process(value):
    if value < 0:
        return "negative"
    elif value == 0:
        return "zero"
    else:
        return "positive"
"""

        existing_tests = [
            "assert process(5) == 'positive'",
            "assert process(-5) == 'negative'"
        ]

        untested = identify_untested_paths(function_code, existing_tests)

        self.assertIsInstance(untested, list)
        # Should identify that value==0 case is not tested
        self.assertTrue(any("0" in str(path) or "zero" in str(path)
                           for path in untested))

    def test_calculate_branch_coverage(self):
        """Analyzer should calculate branch coverage percentage."""
        from rev.discriminating_tests.coverage import calculate_branch_coverage

        function_code = """
def max_of_three(a, b, c):
    if a > b:
        if a > c:
            return a
        return c
    else:
        if b > c:
            return b
        return c
"""

        existing_tests = [
            "assert max_of_three(3, 1, 2) == 3",
            "assert max_of_three(1, 3, 2) == 3"
        ]

        coverage = calculate_branch_coverage(function_code, existing_tests)

        self.assertIsInstance(coverage, float)
        self.assertGreaterEqual(coverage, 0.0)
        self.assertLessEqual(coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
