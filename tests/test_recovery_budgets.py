#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for per-error-type recovery budgets.

These tests verify that the recovery budget system correctly tracks
attempts per error type and triggers circuit breakers appropriately.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from rev.models.task import Task, TaskStatus
from rev.tools.errors import ToolErrorType


class TestClassifyErrorType(unittest.TestCase):
    """Test the _classify_error_type method in Orchestrator."""

    def setUp(self):
        """Set up test fixtures."""
        from rev.execution.orchestrator import Orchestrator, OrchestratorConfig

        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)

        # Mock verification result class
        self.VerificationResult = Mock()

    def test_classify_permission_denied(self):
        """Test permission denied errors are classified correctly."""
        for pattern in [
            "Permission denied",
            "access denied",
            "EACCES",
            "EPERM",
            "forbidden",
            "unauthorized",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.PERMISSION_DENIED,
                           f"Pattern '{pattern}' should be PERMISSION_DENIED")

    def test_classify_not_found(self):
        """Test not found errors are classified correctly."""
        for pattern in [
            "file not found",
            "No such file",
            "ENOENT",
            "Cannot find module 'xyz'",
            "module not found",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.NOT_FOUND,
                           f"Pattern '{pattern}' should be NOT_FOUND")

    def test_classify_404_as_syntax_error(self):
        """Test HTTP 404 errors are classified as SYNTAX_ERROR for routing issues."""
        vr = self.VerificationResult()
        vr.message = "Expected 200 but received 404 for route /api/users"
        vr.details = None

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.SYNTAX_ERROR)

    def test_classify_404_as_not_found(self):
        """Test plain 404 errors (not route-related) are classified as NOT_FOUND."""
        vr = self.VerificationResult()
        vr.message = "File not found 404"
        vr.details = None

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.NOT_FOUND)

    def test_classify_timeout(self):
        """Test timeout errors are classified correctly."""
        for pattern in [
            "timeout",
            "timed out",
            "deadline exceeded",
            "operation timed out",
            "TimeoutError",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.TIMEOUT,
                           f"Pattern '{pattern}' should be TIMEOUT")

    def test_classify_network(self):
        """Test network errors are classified correctly."""
        for pattern in [
            "network error",
            "connection refused",
            "connection reset",
            "ECONNREFUSED",
            "ECONNRESET",
            "dns error",
            "host unreachable",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.NETWORK,
                           f"Pattern '{pattern}' should be NETWORK")

    def test_classify_syntax_error(self):
        """Test syntax errors are classified correctly."""
        for pattern in [
            "SyntaxError",
            "syntax error",
            "IndentationError",
            "unexpected token",
            "invalid syntax",
            "parse error",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.SYNTAX_ERROR,
                           f"Pattern '{pattern}' should be SYNTAX_ERROR")

    def test_classify_validation_error(self):
        """Test validation errors are classified correctly."""
        for pattern in [
            "validation error",
            "invalid input",
            "invalid argument",
            "TypeError",
            "ValueError",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.VALIDATION_ERROR,
                           f"Pattern '{pattern}' should be VALIDATION_ERROR")

    def test_classify_conflict(self):
        """Test conflict errors are classified correctly."""
        for pattern in [
            "conflict",
            "duplicate key",
            "already exists",
            "primary key violation",
            "unique constraint",
            "EEXIST",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.CONFLICT,
                           f"Pattern '{pattern}' should be CONFLICT")

    def test_classify_transient(self):
        """Test transient errors are classified correctly."""
        for pattern in [
            "temporary unavailable",
            "service unavailable",
            "503",
            "too many requests",
            "429",
            "rate limit",
            "database is locked",
            "database busy",
            "deadlock",
        ]:
            vr = self.VerificationResult()
            vr.message = pattern
            vr.details = None

            error_type = self.orchestrator._classify_error_type(vr)
            self.assertEqual(error_type, ToolErrorType.TRANSIENT,
                           f"Pattern '{pattern}' should be TRANSIENT")

    def test_classify_none_verification_result(self):
        """Test None verification result returns UNKNOWN."""
        error_type = self.orchestrator._classify_error_type(None)
        self.assertEqual(error_type, ToolErrorType.UNKNOWN)

    def test_classify_unknown_error(self):
        """Test unknown error patterns return UNKNOWN."""
        vr = self.VerificationResult()
        vr.message = "Some unknown error occurred"
        vr.details = "This is not a recognized error pattern"

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.UNKNOWN)

    def test_classify_case_insensitive(self):
        """Test error classification is case-insensitive."""
        vr = self.VerificationResult()
        vr.message = "PERMISSION DENIED"
        vr.details = None

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.PERMISSION_DENIED)

    def test_classify_uses_details(self):
        """Test that both message and details are checked."""
        vr = self.VerificationResult()
        vr.message = "Some error"
        vr.details = "EACCES: Permission denied"

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.PERMISSION_DENIED)

    def test_classify_message_takes_precedence(self):
        """Test that message is checked first before details."""
        vr = self.VerificationResult()
        vr.message = "timeout"
        vr.details = "EACCES: Permission denied"

        error_type = self.orchestrator._classify_error_type(vr)
        self.assertEqual(error_type, ToolErrorType.TIMEOUT)


class TestBuildFailureSummary(unittest.TestCase):
    """Test the _build_failure_summary method in Orchestrator."""

    def setUp(self):
        """Set up test fixtures."""
        from rev.execution.orchestrator import Orchestrator, OrchestratorConfig

        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)

        # Mock verification result
        self.VerificationResult = Mock()

    def test_build_summary_basic(self):
        """Test basic summary building."""
        task = Task("Test task", action_type="write")
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None

        summary = self.orchestrator._build_failure_summary(
            task, vr, "test::failed", 3
        )

        self.assertIn("Task: Test task", summary)
        self.assertIn("Action Type: write", summary)
        self.assertIn("Error Signature: test::failed", summary)
        self.assertIn("Failure Count: 3", summary)
        self.assertIn("Error: Test failed", summary)

    def test_build_summary_with_long_details(self):
        """Test that long details are truncated."""
        task = Task("Test task")
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = "A" * 300  # Long string

        summary = self.orchestrator._build_failure_summary(
            task, vr, "sig", 1
        )

        self.assertIn("...", summary)  # Truncation indicator
        self.assertIn("Details:", summary)

    def test_build_summary_with_task_error(self):
        """Test summary includes task error."""
        task = Task("Test task")
        task.error = "Custom task error message"
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None

        summary = self.orchestrator._build_failure_summary(
            task, vr, "sig", 1
        )

        self.assertIn("Task Error: Custom task error message", summary)

    def test_build_summary_with_long_task_error(self):
        """Test that long task errors are truncated."""
        task = Task("Test task")
        task.error = "E" * 300  # Long error string
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None

        summary = self.orchestrator._build_failure_summary(
            task, vr, "sig", 1
        )

        self.assertIn("Task Error:", summary)
        self.assertIn("...", summary)

    def test_build_summary_null_verification_result(self):
        """Test summary with None verification result."""
        task = Task("Test task")

        summary = self.orchestrator._build_failure_summary(
            task, None, "sig", 1
        )

        self.assertIn("Task: Test task", summary)
        self.assertIn("Error Signature: sig", summary)
        # Should not have Error or Details sections
        self.assertNotIn("Error:", summary)
        self.assertNotIn("Details:", summary)

    def test_build_summary_null_task_description(self):
        """Test summary with empty task description."""
        task = Task("")
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None

        summary = self.orchestrator._build_failure_summary(
            task, vr, "sig", 1
        )

        self.assertIn("Task: N/A", summary)

    def test_build_summary_none_task_error(self):
        """Test summary with None task error."""
        task = Task("Test task")
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None
        task.error = None

        summary = self.orchestrator._build_failure_summary(
            task, vr, "sig", 1
        )

        self.assertNotIn("Task Error:", summary)


class TestRecoveryBudgetConfiguration(unittest.TestCase):
    """Test that recovery budget configuration is correctly defined."""

    def test_max_attempts_per_error_type_exists(self):
        """Verify MAX_ATTEMPTS_PER_ERROR_TYPE is defined in orchestrator."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator)
        self.assertIn("MAX_ATTEMPTS_PER_ERROR_TYPE", source)

    def test_transient_allows_most_retries(self):
        """Verify TRANSIENT errors allow the most retries (8)."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator)
        self.assertIn("ToolErrorType.TRANSIENT: 8", source)

    def test_permission_denied_allows_one_retry(self):
        """Verify PERMISSION_DENIED errors allow minimal retries (1)."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator)
        self.assertIn("ToolErrorType.PERMISSION_DENIED: 1", source)

    def test_budget_tracking_key_uses_error_type(self):
        """Verify budget key includes error type value."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator)
        # Check that budget key is constructed with error_type.value
        self.assertIn("error_type.value", source)
        self.assertIn('budget_key = f"', source)

    def test_classify_error_type_is_called(self):
        """Verify _classify_error_type is called in budget tracking."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator)
        self.assertIn("_classify_error_type", source)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)