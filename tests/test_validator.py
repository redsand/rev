#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the validation agent functionality.
"""

import unittest
from rev.models.task import ExecutionPlan
from rev.execution.validator import (
    ValidationResult,
    ValidationReport,
    ValidationStatus,
    format_validation_feedback_for_llm
)


class TestValidationFeedbackFormatting(unittest.TestCase):
    """Test validation feedback formatting for LLM consumption."""

    def test_format_feedback_with_test_failures(self):
        """Test formatting feedback with test failures."""
        report = ValidationReport()

        # Add a failed test result
        test_result = ValidationResult(
            name="test_suite",
            status=ValidationStatus.FAILED,
            message="Tests failed (rc=1)",
            details={
                "return_code": 1,
                "failures": [
                    "tests/test_auth.py::test_login - AssertionError",
                    "tests/test_auth.py::test_logout - KeyError: 'session'"
                ],
                "output": "FAILED tests/test_auth.py::test_login - AssertionError: expected True, got False"
            }
        )
        report.add_result(test_result)

        feedback = format_validation_feedback_for_llm(report, "Add user authentication")

        self.assertIsNotNone(feedback)
        self.assertIn("VALIDATION FEEDBACK", feedback)
        self.assertIn("FAILED", feedback)
        self.assertIn("test_suite", feedback)
        self.assertIn("Failed tests:", feedback)
        self.assertIn("test_login", feedback)
        self.assertIn("REQUIRED ACTIONS", feedback)
        self.assertIn("Fix the failing tests", feedback)

    def test_format_feedback_with_linting_errors(self):
        """Test formatting feedback with linting errors."""
        report = ValidationReport()

        lint_result = ValidationResult(
            name="linter",
            status=ValidationStatus.FAILED,
            message="5 linting issues found",
            details={
                "issues": [
                    {
                        "code": "F401",
                        "message": "unused import 'sys'",
                        "location": {"row": 10, "column": 1}
                    },
                    {
                        "code": "E501",
                        "message": "line too long (120 > 88 characters)",
                        "location": {"row": 25, "column": 89}
                    }
                ]
            }
        )
        report.add_result(lint_result)

        feedback = format_validation_feedback_for_llm(report, "Refactor code")

        self.assertIsNotNone(feedback)
        self.assertIn("linter", feedback)
        self.assertIn("Linting issues:", feedback)
        self.assertIn("F401", feedback)
        self.assertIn("unused import", feedback)
        self.assertIn("Fix linting errors", feedback)
        self.assertIn("ruff check --fix", feedback)

    def test_format_feedback_with_syntax_errors(self):
        """Test formatting feedback with syntax errors."""
        report = ValidationReport()

        syntax_result = ValidationResult(
            name="syntax_check",
            status=ValidationStatus.FAILED,
            message="Syntax errors detected",
            details={
                "output": "SyntaxError: invalid syntax at line 42"
            }
        )
        report.add_result(syntax_result)

        feedback = format_validation_feedback_for_llm(report, "Fix code")

        self.assertIsNotNone(feedback)
        self.assertIn("syntax_check", feedback)
        self.assertIn("Syntax errors detected", feedback)
        self.assertIn("Fix syntax errors", feedback)
        self.assertIn("missing colons, parentheses", feedback)

    def test_format_feedback_with_warnings_only(self):
        """Test formatting feedback with warnings but no failures."""
        report = ValidationReport()

        warning_result = ValidationResult(
            name="linter",
            status=ValidationStatus.PASSED_WITH_WARNINGS,
            message="2 minor linting issues",
            details={"issues": ["W291: trailing whitespace"]}
        )
        report.add_result(warning_result)

        feedback = format_validation_feedback_for_llm(report, "Update code")

        self.assertIsNotNone(feedback)
        self.assertIn("WARNINGS", feedback)
        self.assertIn("linter", feedback)
        self.assertIn("minor linting issues", feedback)
        self.assertIn("warnings but no critical failures", feedback)

    def test_format_feedback_all_passed(self):
        """Test that no feedback is returned when all checks pass."""
        report = ValidationReport()

        passed_result = ValidationResult(
            name="test_suite",
            status=ValidationStatus.PASSED,
            message="All tests passed"
        )
        report.add_result(passed_result)

        feedback = format_validation_feedback_for_llm(report, "Test request")

        self.assertIsNone(feedback)

    def test_format_feedback_semantic_validation_failed(self):
        """Test formatting feedback for semantic validation failures."""
        report = ValidationReport()

        semantic_result = ValidationResult(
            name="semantic_validation",
            status=ValidationStatus.FAILED,
            message="Changes may not match request (confidence: 40%)",
            details={
                "confidence": 0.4,
                "issues": ["Missing authentication middleware"],
                "warnings": []
            }
        )
        report.add_result(semantic_result)

        feedback = format_validation_feedback_for_llm(report, "Add authentication")

        self.assertIsNotNone(feedback)
        self.assertIn("semantic_validation", feedback)
        self.assertIn("Changes may not match request", feedback)
        self.assertIn("Review if the changes actually fulfill", feedback)

    def test_format_feedback_multiple_failures(self):
        """Test formatting feedback with multiple types of failures."""
        report = ValidationReport()

        # Test failure
        test_result = ValidationResult(
            name="test_suite",
            status=ValidationStatus.FAILED,
            message="Tests failed",
            details={"failures": ["test_foo"]}
        )
        report.add_result(test_result)

        # Lint failure
        lint_result = ValidationResult(
            name="linter",
            status=ValidationStatus.FAILED,
            message="Linting issues",
            details={"issues": [{"code": "E501", "message": "line too long"}]}
        )
        report.add_result(lint_result)

        feedback = format_validation_feedback_for_llm(report, "Fix code")

        self.assertIsNotNone(feedback)
        # Should contain both test and lint failures
        self.assertIn("test_suite", feedback)
        self.assertIn("linter", feedback)
        self.assertIn("FAILED CHECKS", feedback)
        # Count the number of "Check:" occurrences - should be 2
        self.assertEqual(feedback.count("Check:"), 2)


class TestValidationResult(unittest.TestCase):
    """Test ValidationResult data class."""

    def test_validation_result_to_dict(self):
        """Test ValidationResult serialization."""
        result = ValidationResult(
            name="test_check",
            status=ValidationStatus.PASSED,
            message="Check passed",
            details={"count": 5},
            duration_ms=123.45
        )

        data = result.to_dict()
        self.assertEqual(data["name"], "test_check")
        self.assertEqual(data["status"], "passed")
        self.assertEqual(data["message"], "Check passed")
        self.assertEqual(data["details"]["count"], 5)
        self.assertEqual(data["duration_ms"], 123.45)


class TestValidationReport(unittest.TestCase):
    """Test ValidationReport data class."""

    def test_add_result_updates_overall_status(self):
        """Test that adding results updates overall status."""
        report = ValidationReport()
        self.assertEqual(report.overall_status, ValidationStatus.PASSED)

        # Add passed result - should stay PASSED
        report.add_result(ValidationResult("check1", ValidationStatus.PASSED))
        self.assertEqual(report.overall_status, ValidationStatus.PASSED)

        # Add warning - should become PASSED_WITH_WARNINGS
        report.add_result(ValidationResult("check2", ValidationStatus.PASSED_WITH_WARNINGS))
        self.assertEqual(report.overall_status, ValidationStatus.PASSED_WITH_WARNINGS)

        # Add failure - should become FAILED
        report.add_result(ValidationResult("check3", ValidationStatus.FAILED))
        self.assertEqual(report.overall_status, ValidationStatus.FAILED)
        self.assertTrue(report.rollback_recommended)

    def test_validation_report_to_dict(self):
        """Test ValidationReport serialization."""
        report = ValidationReport()
        report.add_result(ValidationResult("check1", ValidationStatus.PASSED))
        report.summary = "All checks passed"
        report.auto_fixed = ["linting"]

        data = report.to_dict()
        self.assertEqual(data["overall_status"], "passed")
        self.assertEqual(data["summary"], "All checks passed")
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["auto_fixed"], ["linting"])


if __name__ == "__main__":
    unittest.main()
