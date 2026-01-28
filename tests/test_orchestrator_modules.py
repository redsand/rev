#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the refactored orchestrator modules.

These tests verify that TaskRunner, RecoveryManager, and VerificationCoordinator
work correctly after splitting from orchestrator.py.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from rev.execution.task_runner import TaskRunner
from rev.execution.recovery_manager import RecoveryManager, RecoveryBudget
from rev.execution.verification_coordinator import VerificationCoordinator, TestSignature, CodeStateSnapshot
from rev.models.task import Task, TaskStatus, ExecutionPlan
from rev.tools.errors import ToolErrorType


class TestTaskRunner(unittest.TestCase):
    """Test TaskRunner functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_orchestrator = Mock()
        self.mock_orchestrator._apply_read_only_constraints = lambda t: t
        self.mock_orchestrator._dispatch_to_sub_agents = Mock(return_value=True)
        self.mock_orchestrator.debug_logger = Mock()

        from rev.core.context import RevContext, RevConfig
        self.config = RevConfig()
        self.context = RevContext(self.config, Path.cwd())
        self.runner = TaskRunner(self.mock_orchestrator)

    def test_task_runner_initialization(self):
        """Test TaskRunner initializes correctly."""
        self.assertIsNotNone(self.runner)
        self.assertEqual(self.runner.orchestrator, self.mock_orchestrator)

    def test_dispatch_completed_task(self):
        """Test that completed tasks are skipped."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task", action_type="test")
        plan.mark_task_in_progress(task)
        plan.mark_task_completed(task)
        self.context.plan = plan

        result = self.runner.dispatch_task(self.context)
        self.assertTrue(result)

    def test_dispatch_in_read_only_mode_rejects_writes(self):
        """Test that write actions are rejected in read-only mode."""
        from rev.execution.tool_constraints import WRITE_ACTIONS

        self.config.read_only = True
        plan = ExecutionPlan()
        task = plan.add_task("Write file", action_type="add")
        self.context.plan = plan

        result = self.runner.dispatch_task(self.context)
        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.STOPPED)


class TestRecoveryManager(unittest.TestCase):
    """Test RecoveryManager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_orchestrator = Mock()
        self.manager = RecoveryManager(self.mock_orchestrator)

        # Mock verification result
        self.VerificationResult = Mock()

    def test_recovery_manager_initialization(self):
        """Test RecoveryManager initializes correctly."""
        self.assertIsNotNone(self.manager)
        self.assertEqual(self.manager.orchestrator, self.mock_orchestrator)

    def test_classify_permission_denied(self):
        """Test permission denied errors are classified correctly."""
        vr = self.VerificationResult()
        vr.message = "Permission denied"
        vr.details = None

        error_type = self.manager.classify_error(vr)
        self.assertEqual(error_type, ToolErrorType.PERMISSION_DENIED)

    def test_classify_timeout(self):
        """Test timeout errors are classified correctly."""
        vr = self.VerificationResult()
        vr.message = "timeout"
        vr.details = None

        error_type = self.manager.classify_error(vr)
        self.assertEqual(error_type, ToolErrorType.TIMEOUT)

    def test_classify_unknown_error(self):
        """Test unknown errors are classified as UNKNOWN."""
        vr = self.VerificationResult()
        vr.message = "Some unknown error"
        vr.details = None

        error_type = self.manager.classify_error(vr)
        self.assertEqual(error_type, ToolErrorType.UNKNOWN)

    def test_max_attempts_per_error_type(self):
        """Test that max attempts are defined for each error type."""
        for error_type in ToolErrorType:
            self.assertIn(error_type, RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE)
            self.assertIsInstance(RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE[error_type], int)
            self.assertGreater(RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE[error_type], 0)

    def test_transient_allows_more_retries_than_permission_denied(self):
        """Test TRANSIENT allows more retries than PERMISSION_DENIED."""
        transient_retries = RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE[ToolErrorType.TRANSIENT]
        perm_denied_retries = RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE[ToolErrorType.PERMISSION_DENIED]

        self.assertGreater(transient_retries, perm_denied_retries)

    def test_build_failure_summary(self):
        """Test failure summary building."""
        task = Task("Test task", action_type="write")
        vr = self.VerificationResult()
        vr.message = "Test failed"
        vr.details = None

        summary = self.manager.build_failure_summary(task, vr, "sig", 3)

        self.assertIn("Task: Test task", summary)
        self.assertIn("Action Type: write", summary)
        self.assertIn("Error Signature: sig", summary)
        self.assertIn("Failure Count: 3", summary)
        self.assertIn("Error: Test failed", summary)

    def test_get_recovery_budget(self):
        """Test getting recovery budget."""
        from rev.core.context import RevContext

        context = RevContext(user_request="test")

        budget = self.manager.get_recovery_budget(
            context,
            "timeout::test_sig",
            ToolErrorType.TIMEOUT
        )

        self.assertIsInstance(budget, RecoveryBudget)
        self.assertEqual(budget.budget_key, "timeout::test_sig")
        self.assertEqual(budget.error_type, ToolErrorType.TIMEOUT)
        self.assertEqual(budget.current_attempts, 0)
        self.assertEqual(budget.max_attempts, RecoveryManager.MAX_ATTEMPTS_PER_ERROR_TYPE[ToolErrorType.TIMEOUT])

    def test_increment_recovery_budget(self):
        """Test incrementing recovery budget."""
        from rev.core.context import RevContext

        context = RevContext(user_request="test")

        new_attempts = self.manager.increment_recovery_budget(context, "test_key")

        self.assertEqual(new_attempts, 1)

        # Increment again
        new_attempts = self.manager.increment_recovery_budget(context, "test_key")
        self.assertEqual(new_attempts, 2)

    def test_should_trigger_circuit_breaker_when_exhausted(self):
        """Test circuit breaker triggers when budget exhausted."""
        budget = RecoveryBudget(
            budget_key="test_key",
            error_type=ToolErrorType.PERMISSION_DENIED,
            current_attempts=1,
            max_attempts=1
        )

        self.assertTrue(self.manager.should_trigger_circuit_breaker(budget))

    def test_should_not_trigger_circuit_breaker_when_not_exhausted(self):
        """Test circuit breaker does not trigger when budget not exhausted."""
        budget = RecoveryBudget(
            budget_key="test_key",
            error_type=ToolErrorType.TRANSIENT,
            current_attempts=2,
            max_attempts=8
        )

        self.assertFalse(self.manager.should_trigger_circuit_breaker(budget))

    def test_recovery_budget_exhausted_property(self):
        """Test RecoveryBudget.exhausted property."""
        budget = RecoveryBudget(
            budget_key="test",
            error_type=ToolErrorType.PERMISSION_DENIED,
            current_attempts=1,
            max_attempts=1
        )
        self.assertTrue(budget.exhausted)

        budget.current_attempts = 0
        self.assertFalse(budget.exhausted)

    def test_recovery_budget_remaining_property(self):
        """Test RecoveryBudget.remaining property."""
        budget = RecoveryBudget(
            budget_key="test",
            error_type=ToolErrorType.TRANSIENT,
            current_attempts=3,
            max_attempts=8
        )
        self.assertEqual(budget.remaining, 5)


class TestVerificationCoordinator(unittest.TestCase):
    """Test VerificationCoordinator functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_orchestrator = Mock()
        self.coordinator = VerificationCoordinator(self.mock_orchestrator)

    def test_verification_coordinator_initialization(self):
        """Test VerificationCoordinator initializes correctly."""
        self.assertIsNotNone(self.coordinator)
        self.assertEqual(self.coordinator.orchestrator, self.mock_orchestrator)

    def test_compute_code_state_hash(self):
        """Test code state hash computation."""
        hash_val = self.coordinator.compute_code_state_hash()

        self.assertIsInstance(hash_val, str)
        self.assertEqual(len(hash_val), 16)

    def test_compute_code_state_hash_is_deterministic(self):
        """Test code state hash is deterministic for same state."""
        hash1 = self.coordinator.compute_code_state_hash()
        hash2 = self.coordinator.compute_code_state_hash()

        self.assertEqual(hash1, hash2)

    def test_get_test_signature_for_test_task(self):
        """Test getting signature for test task."""
        task = Task("Test my function", action_type="test")

        signature = self.coordinator.get_test_signature(task)

        self.assertIsNotNone(signature)
        self.assertIn("Test my function", signature)
        self.assertIn("test", signature)

    def test_get_test_signature_for_non_test_task(self):
        """Test getting signature for non-test task returns None."""
        task = Task("Write code", action_type="write")

        signature = self.coordinator.get_test_signature(task)

        self.assertIsNone(signature)

    def test_get_failing_test_file(self):
        """Test extracting failing test file from verification result."""
        vr = Mock()
        vr.details = {
            "output": "FAILED tests/test_my_function.py::test_case_one"
        }

        test_file = self.coordinator.get_failing_test_file(vr)

        self.assertIsNotNone(test_file)
        self.assertIn("test_my_function.py", test_file)

    def test_get_failing_test_file_from_stderr(self):
        """Test extracting failing test file from stderr."""
        vr = Mock()
        vr.details = {
            "stderr": "tests/unit/test_example.py:5: AssertionError"
        }

        test_file = self.coordinator.get_failing_test_file(vr)

        self.assertIsNotNone(test_file)
        self.assertIn("test_example.py", test_file)

    def test_record_code_change(self):
        """Test recording code change."""
        from rev.core.context import RevContext

        context = RevContext(user_request="test")
        context.set_agent_state("current_iteration", 5)

        self.coordinator.record_code_change(context, ["test.py"])

        self.assertEqual(context.agent_state.get("last_code_change_iteration"), 5)
        self.assertIn("current_code_hash", context.agent_state)

    def test_should_skip_test_without_signature(self):
        """Test non-test tasks are not skipped."""
        from rev.core.context import RevContext

        context = RevContext(user_request="test")
        task = Task("Write code", action_type="write")

        should_skip = self.coordinator.should_skip_test(context, task)

        self.assertFalse(should_skip)

    def test_test_signature_dataclass(self):
        """Test TestSignature dataclass."""
        sig = TestSignature(
            signature="test_sig",
            seen_at=1,
            last_result="pass",
            code_hash="abc123"
        )

        self.assertEqual(sig.signature, "test_sig")
        self.assertEqual(sig.seen_at, 1)
        self.assertEqual(sig.last_result, "pass")
        self.assertEqual(sig.code_hash, "abc123")
        self.assertFalse(sig.blocked)

    def test_code_state_snapshot_dataclass(self):
        """Test CodeStateSnapshot dataclass."""
        import time
        snapshot = CodeStateSnapshot(
            hash_value="abc123",
            modified_files=["test.py"],
            timestamp=time.time()
        )

        self.assertEqual(snapshot.hash_value, "abc123")
        self.assertEqual(snapshot.modified_files, ["test.py"])


class TestModuleIntegration(unittest.TestCase):
    """Test integration between the refactored modules."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_orchestrator = Mock()
        self.mock_orchestrator._apply_read_only_constraints = lambda t: t
        self.mock_orchestrator._dispatch_to_sub_agents = Mock(return_value=True)

        from rev.core.context import RevContext, RevConfig
        self.config = RevConfig()
        self.context = RevContext(self.config, Path.cwd())

        self.runner = TaskRunner(self.mock_orchestrator)
        self.recovery = RecoveryManager(self.mock_orchestrator)
        self.verification = VerificationCoordinator(self.mock_orchestrator)

    def test_modules_share_orchestrator_reference(self):
        """Test all modules share the same orchestrator reference."""
        self.assertEqual(self.runner.orchestrator, self.mock_orchestrator)
        self.assertEqual(self.recovery.orchestrator, self.mock_orchestrator)
        self.assertEqual(self.verification.orchestrator, self.mock_orchestrator)

    def test_recovery_classify_error_works_independently(self):
        """Test RecoveryManager can classify errors independently."""
        vr = Mock()
        vr.message = "timeout"
        vr.details = None

        error_type = self.recovery.classify_error(vr)

        self.assertEqual(error_type, ToolErrorType.TIMEOUT)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)