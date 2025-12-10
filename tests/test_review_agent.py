#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the review agent functionality.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from rev.models.task import ExecutionPlan, Task, RiskLevel
from rev.execution.reviewer import (
    review_execution_plan,
    review_action,
    ReviewStrictness,
    ReviewDecision,
    PlanReview,
    ActionReview,
    _quick_security_check,
    format_review_feedback_for_llm
)


class TestQuickSecurityCheck(unittest.TestCase):
    """Test the quick security check functionality."""

    def test_command_injection_detection(self):
        """Test detection of command injection patterns."""
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "ls; rm -rf /"},
            "Execute system command"
        )
        self.assertTrue(len(warnings) > 0)
        # Should detect command chaining
        self.assertIn("command", warnings[0].lower())

    def test_hardcoded_secret_detection(self):
        """Test detection of hardcoded secrets."""
        warnings = _quick_security_check(
            "write_file",
            {"content": 'API_KEY = "sk-1234567890abcdef"'},
            "Write configuration file"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("secret", warnings[0].lower())

    def test_sql_injection_warning(self):
        """Test SQL injection warnings."""
        warnings = _quick_security_check(
            "execute_query",
            {"query": "SELECT * FROM users WHERE id = '1'"},
            "Execute SQL query to fetch user data"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("sql", warnings[0].lower())

    def test_path_traversal_detection(self):
        """Test detection of path traversal attempts."""
        warnings = _quick_security_check(
            "read_file",
            {"file_path": "../../../etc/passwd"},
            "Read configuration file"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("path", warnings[0].lower())

    def test_safe_operation(self):
        """Test that safe operations don't trigger warnings."""
        warnings = _quick_security_check(
            "read_file",
            {"file_path": "/home/user/project/src/main.py"},
            "Read source file"
        )
        self.assertEqual(len(warnings), 0)

    def test_trusted_compiler_not_flagged(self):
        """Test that trusted compiler commands are not flagged as security issues."""
        # Test cl.exe (Microsoft C/C++ Compiler)
        warnings = _quick_security_check(
            "run_cmd",
            {"command": 'cl.exe /I"C:\\Program Files\\Windows Kits\\10\\Include" /c driver.c'},
            "Compile driver code"
        )
        self.assertEqual(len(warnings), 0)

        # Test gcc
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "gcc -o output main.c -I/usr/include"},
            "Compile with GCC"
        )
        self.assertEqual(len(warnings), 0)

        # Test cmake
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "cmake -DCMAKE_BUILD_TYPE=Release .."},
            "Run CMake build"
        )
        self.assertEqual(len(warnings), 0)

    def test_trusted_build_tools_not_flagged(self):
        """Test that trusted build tools are not flagged."""
        # Test npm
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "npm install && npm run build"},
            "Build Node.js project"
        )
        self.assertEqual(len(warnings), 0)

        # Test cargo
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "cargo build --release"},
            "Build Rust project"
        )
        self.assertEqual(len(warnings), 0)

        # Test pytest
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "pytest tests/ -v"},
            "Run Python tests"
        )
        self.assertEqual(len(warnings), 0)

    def test_code_with_command_injection_flagged(self):
        """Test that code with command injection is flagged."""
        code_with_injection = '''
import os
user_input = request.args.get("filename")
os.system("cat " + user_input)
'''
        warnings = _quick_security_check(
            "write_file",
            {"content": code_with_injection},
            "Write file handler"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("command injection", warnings[0].lower())

    def test_code_with_sql_injection_flagged(self):
        """Test that code with SQL injection is flagged."""
        code_with_sql_injection = '''
def get_user(user_id):
    query = "SELECT * FROM users WHERE id = " + user_id
    return db.execute(query)
'''
        warnings = _quick_security_check(
            "write_file",
            {"content": code_with_sql_injection},
            "Write database handler"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("sql injection", warnings[0].lower())

    def test_non_trusted_command_with_substitution_flagged(self):
        """Test that non-trusted commands with substitution are flagged."""
        warnings = _quick_security_check(
            "run_cmd",
            {"command": "echo $(whoami)"},
            "Execute custom script"
        )
        self.assertTrue(len(warnings) > 0)
        self.assertIn("substitution", warnings[0].lower())


class TestActionReview(unittest.TestCase):
    """Test the action review functionality."""

    @patch('rev.execution.reviewer.ollama_chat')
    def test_action_approved(self, mock_ollama):
        """Test that safe actions are approved."""
        mock_ollama.return_value = {
            "message": {
                "content": '{"approved": true, "recommendation": "Action looks good"}'
            }
        }

        review = review_action(
            action_type="edit",
            action_description="Update logging configuration",
            tool_name="write_file",
            tool_args={"file_path": "config/logging.yaml", "content": "level: INFO"},
            context="Improve logging verbosity"
        )

        self.assertTrue(review.approved)
        self.assertEqual(review.recommendation, "Action looks good")

    @patch('rev.execution.reviewer.ollama_chat')
    def test_action_with_security_warning(self, mock_ollama):
        """Test that actions with security issues are flagged."""
        mock_ollama.return_value = {
            "message": {
                "content": '{"approved": true, "security_warnings": ["Hardcoded credentials detected"], "recommendation": "Use environment variables"}'
            }
        }

        review = review_action(
            action_type="edit",
            action_description="Update API configuration",
            tool_name="write_file",
            tool_args={"file_path": "config.py", "content": 'API_KEY = "secret123"'},
            context="Configure API access"
        )

        self.assertTrue(review.approved)
        self.assertTrue(len(review.security_warnings) > 0)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_action_blocked(self, mock_ollama):
        """Test that dangerous actions are blocked."""
        mock_ollama.return_value = {
            "message": {
                "content": '{"approved": false, "concerns": ["This will delete production data"], "recommendation": "Do not execute"}'
            }
        }

        review = review_action(
            action_type="delete",
            action_description="Delete all user data",
            tool_name="run_cmd",
            tool_args={"command": "rm -rf /var/lib/database/*"},
            context="Clean up database"
        )

        self.assertFalse(review.approved)
        self.assertTrue(len(review.concerns) > 0)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_llm_error_defaults_to_approved(self, mock_ollama):
        """Test that LLM errors default to approved with warning."""
        mock_ollama.return_value = {"error": "Connection timeout"}

        review = review_action(
            action_type="edit",
            action_description="Update configuration",
            tool_name="write_file",
            tool_args={},
            context="Test task"
        )

        self.assertTrue(review.approved)
        self.assertTrue(len(review.concerns) > 0)


class TestPlanReview(unittest.TestCase):
    """Test the plan review functionality."""

    def test_auto_approve_low_risk_plan(self):
        """Test that low-risk plans are auto-approved."""
        plan = ExecutionPlan()
        plan.add_task("Review current code structure", "review")
        plan.add_task("Read configuration file", "review")
        plan.tasks[0].risk_level = RiskLevel.LOW
        plan.tasks[1].risk_level = RiskLevel.LOW

        review = review_execution_plan(
            plan,
            "Analyze the codebase",
            strictness=ReviewStrictness.MODERATE,
            auto_approve_low_risk=True
        )

        self.assertEqual(review.decision, ReviewDecision.APPROVED)
        self.assertGreaterEqual(review.confidence_score, 0.9)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_plan_approved_with_suggestions(self, mock_ollama):
        """Test plan approved with suggestions."""
        mock_ollama.return_value = {
            "message": {
                "content": '''
                {
                    "decision": "approved_with_suggestions",
                    "overall_assessment": "Plan is generally good but could be improved",
                    "confidence_score": 0.8,
                    "issues": [],
                    "suggestions": ["Consider adding error handling", "Add integration tests"],
                    "security_concerns": [],
                    "missing_tasks": [],
                    "unnecessary_tasks": []
                }
                '''
            }
        }

        plan = ExecutionPlan()
        plan.add_task("Implement new API endpoint", "add")
        plan.tasks[0].risk_level = RiskLevel.MEDIUM

        review = review_execution_plan(
            plan,
            "Add new API endpoint",
            strictness=ReviewStrictness.MODERATE,
            auto_approve_low_risk=False
        )

        self.assertEqual(review.decision, ReviewDecision.APPROVED_WITH_SUGGESTIONS)
        self.assertTrue(len(review.suggestions) > 0)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_plan_rejected(self, mock_ollama):
        """Test plan rejection."""
        mock_ollama.return_value = {
            "message": {
                "content": '''
                {
                    "decision": "rejected",
                    "overall_assessment": "This plan has critical security issues",
                    "confidence_score": 0.95,
                    "issues": [
                        {
                            "severity": "critical",
                            "task_id": 0,
                            "description": "Hardcoded credentials",
                            "impact": "Security breach"
                        }
                    ],
                    "suggestions": [],
                    "security_concerns": ["Hardcoded API keys in source code"],
                    "missing_tasks": [],
                    "unnecessary_tasks": []
                }
                '''
            }
        }

        plan = ExecutionPlan()
        plan.add_task("Add API key to config file", "add")
        plan.tasks[0].risk_level = RiskLevel.HIGH

        review = review_execution_plan(
            plan,
            "Configure API access",
            strictness=ReviewStrictness.STRICT,
            auto_approve_low_risk=False
        )

        self.assertEqual(review.decision, ReviewDecision.REJECTED)
        self.assertTrue(len(review.security_concerns) > 0)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_plan_requires_changes(self, mock_ollama):
        """Test plan that requires changes."""
        mock_ollama.return_value = {
            "message": {
                "content": '''
                {
                    "decision": "requires_changes",
                    "overall_assessment": "Plan needs improvements before execution",
                    "confidence_score": 0.75,
                    "issues": [
                        {
                            "severity": "high",
                            "task_id": 1,
                            "description": "Missing validation step",
                            "impact": "Potential data corruption"
                        }
                    ],
                    "suggestions": ["Add input validation"],
                    "security_concerns": [],
                    "missing_tasks": ["Add unit tests for validation"],
                    "unnecessary_tasks": []
                }
                '''
            }
        }

        plan = ExecutionPlan()
        plan.add_task("Add user registration endpoint", "add")
        plan.add_task("Store user data in database", "edit")
        plan.tasks[0].risk_level = RiskLevel.MEDIUM
        plan.tasks[1].risk_level = RiskLevel.HIGH

        review = review_execution_plan(
            plan,
            "Implement user registration",
            strictness=ReviewStrictness.MODERATE,
            auto_approve_low_risk=False
        )

        self.assertEqual(review.decision, ReviewDecision.REQUIRES_CHANGES)
        self.assertTrue(len(review.missing_tasks) > 0)

    @patch('rev.execution.reviewer.ollama_chat')
    def test_llm_error_defaults_to_approved(self, mock_ollama):
        """Test that LLM errors default to approved with suggestions."""
        mock_ollama.return_value = {"error": "Connection failed"}

        plan = ExecutionPlan()
        plan.add_task("Update documentation", "edit")
        plan.tasks[0].risk_level = RiskLevel.LOW

        review = review_execution_plan(
            plan,
            "Update docs",
            strictness=ReviewStrictness.MODERATE,
            auto_approve_low_risk=False
        )

        self.assertEqual(review.decision, ReviewDecision.APPROVED_WITH_SUGGESTIONS)
        self.assertIn("unavailable", review.suggestions[0].lower())


class TestReviewStrictness(unittest.TestCase):
    """Test review strictness levels."""

    def test_strictness_enum_values(self):
        """Test that strictness enum has expected values."""
        self.assertEqual(ReviewStrictness.LENIENT.value, "lenient")
        self.assertEqual(ReviewStrictness.MODERATE.value, "moderate")
        self.assertEqual(ReviewStrictness.STRICT.value, "strict")


class TestReviewDecision(unittest.TestCase):
    """Test review decision enum."""

    def test_decision_enum_values(self):
        """Test that decision enum has expected values."""
        self.assertEqual(ReviewDecision.APPROVED.value, "approved")
        self.assertEqual(ReviewDecision.APPROVED_WITH_SUGGESTIONS.value, "approved_with_suggestions")
        self.assertEqual(ReviewDecision.REQUIRES_CHANGES.value, "requires_changes")
        self.assertEqual(ReviewDecision.REJECTED.value, "rejected")


class TestPlanReviewDataClass(unittest.TestCase):
    """Test PlanReview data class."""

    def test_plan_review_initialization(self):
        """Test PlanReview default initialization."""
        review = PlanReview()
        self.assertEqual(review.decision, ReviewDecision.APPROVED)
        self.assertEqual(len(review.issues), 0)
        self.assertEqual(len(review.suggestions), 0)
        self.assertEqual(review.confidence_score, 0.7)  # Default is 0.7 per reviewer.py:44

    def test_plan_review_to_dict(self):
        """Test PlanReview serialization."""
        review = PlanReview()
        review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
        review.suggestions = ["Add tests"]
        review.confidence_score = 0.85

        data = review.to_dict()
        self.assertEqual(data["decision"], "approved_with_suggestions")
        self.assertEqual(len(data["suggestions"]), 1)
        self.assertEqual(data["confidence_score"], 0.85)


class TestActionReviewDataClass(unittest.TestCase):
    """Test ActionReview data class."""

    def test_action_review_initialization(self):
        """Test ActionReview default initialization."""
        review = ActionReview()
        self.assertTrue(review.approved)
        self.assertEqual(len(review.concerns), 0)
        self.assertEqual(len(review.security_warnings), 0)

    def test_action_review_to_dict(self):
        """Test ActionReview serialization."""
        review = ActionReview()
        review.approved = False
        review.concerns = ["Data loss risk"]
        review.recommendation = "Do not proceed"

        data = review.to_dict()
        self.assertFalse(data["approved"])
        self.assertEqual(len(data["concerns"]), 1)
        self.assertEqual(data["recommendation"], "Do not proceed")


class TestFeedbackFormatting(unittest.TestCase):
    """Test feedback formatting for LLM consumption."""

    def test_format_feedback_with_concerns(self):
        """Test formatting feedback with concerns and warnings."""
        review = ActionReview()
        review.approved = True
        review.concerns = ["Pattern may have false positives", "Could miss some variants"]
        review.security_warnings = ["Potential regex DoS with complex patterns"]
        review.alternative_approaches = [
            "Use static analysis tools like AddressSanitizer",
            "Consider combining with manual code review"
        ]
        review.recommendation = "Approve with caution"

        feedback = format_review_feedback_for_llm(
            review,
            "search_code for use-after-free patterns",
            "search_code"
        )

        self.assertIsNotNone(feedback)
        self.assertIn("REVIEW FEEDBACK", feedback)
        self.assertIn("search_code", feedback)
        self.assertIn("Pattern may have false positives", feedback)
        self.assertIn("AddressSanitizer", feedback)
        self.assertIn("Approve with caution", feedback)

    def test_format_feedback_blocked_action(self):
        """Test formatting feedback for blocked actions."""
        review = ActionReview()
        review.approved = False
        review.concerns = ["This will delete production data"]
        review.recommendation = "Do not execute"

        feedback = format_review_feedback_for_llm(
            review,
            "delete production database",
            "run_cmd"
        )

        self.assertIsNotNone(feedback)
        self.assertIn("BLOCKED", feedback)
        self.assertIn("choose a different approach", feedback)

    def test_format_feedback_no_concerns(self):
        """Test that no feedback is returned when there are no concerns."""
        review = ActionReview()
        review.approved = True
        review.recommendation = "Looks good"

        feedback = format_review_feedback_for_llm(
            review,
            "read configuration file",
            "read_file"
        )

        self.assertIsNone(feedback)

    def test_format_feedback_with_alternatives_only(self):
        """Test formatting with only alternative approaches."""
        review = ActionReview()
        review.approved = True
        review.alternative_approaches = [
            "Consider using pytest instead of unittest",
            "Could add integration tests as well"
        ]

        feedback = format_review_feedback_for_llm(
            review,
            "run unit tests",
            "run_tests"
        )

        self.assertIsNotNone(feedback)
        self.assertIn("ALTERNATIVE APPROACHES", feedback)
        self.assertIn("pytest", feedback)

    def test_format_feedback_without_tool_name(self):
        """Test formatting feedback without tool name specified."""
        review = ActionReview()
        review.approved = True
        review.concerns = ["May cause issues"]

        feedback = format_review_feedback_for_llm(
            review,
            "some action"
        )

        self.assertIsNotNone(feedback)
        self.assertIn("some action", feedback)
        # Should not include "Tool:" line
        self.assertNotIn("Tool: None", feedback)


if __name__ == "__main__":
    unittest.main()
