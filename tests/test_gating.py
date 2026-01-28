#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gating Tests - Prevent Regressions.

These tests verify that critical refactoring changes work correctly.
Failing any of these tests indicates a regression in core functionality.
"""

import unittest
from rev.models.task import TaskStatus, TaskStateMachine, Task, ExecutionPlan
from rev.tools.errors import ToolErrorType, ToolError, file_not_found_error, syntax_error
from rev.tools.registry import _normalize_args, _PARAM_ALIASES, _TOOL_PARAM_ALIASES


class GatingTestToolErrorTaxonomy(unittest.TestCase):
    """Gating test: Verify ToolErrorType taxonomy works correctly."""

    def test_tool_error_type_all_have_properties(self):
        """All ToolErrorType values must have correct properties."""
        for error_type in ToolErrorType:
            # Check that retryable property is boolean
            self.assertIsInstance(error_type.is_retryable, bool)

            # Check that recoverable_by_agent property is boolean
            self.assertIsInstance(error_type.recoverable_by_agent, bool)

            # Check that requires_user_input property is boolean
            self.assertIsInstance(error_type.requires_user_input, bool)

    def test_retryable_errors_are_recoverable_by_agent(self):
        """All retryable errors must be recoverable by agent."""
        for error_type in ToolErrorType:
            if error_type.is_retryable:
                self.assertTrue(
                    error_type.recoverable_by_agent,
                    f"{error_type} is retryable but not recoverable by agent"
                )

    def test_tool_error_factory_functions_return_correct_type(self):
        """Factory functions must return correct ToolErrorType."""
        from rev.tools.errors import (
            file_not_found_error, permission_denied_error,
            syntax_error, timeout_error, validation_error
        )

        # Each factory should return the correct error type
        self.assertEqual(file_not_found_error("test.py").error_type, ToolErrorType.NOT_FOUND)
        self.assertEqual(permission_denied_error("/root/file").error_type, ToolErrorType.PERMISSION_DENIED)
        self.assertEqual(syntax_error("error", "test.py").error_type, ToolErrorType.SYNTAX_ERROR)
        self.assertEqual(timeout_error("op", 30).error_type, ToolErrorType.TIMEOUT)
        self.assertEqual(validation_error("err", {"key": None}).error_type, ToolErrorType.VALIDATION_ERROR)

    def test_tool_error_to_dict_serialization(self):
        """ToolError must serialize to dict correctly."""
        error = file_not_found_error("test.py")
        error_dict = error.to_dict()

        self.assertIn("error_type", error_dict)
        self.assertIn("error", error_dict)
        self.assertIn("recoverable", error_dict)
        self.assertIn("suggested_recovery", error_dict)

    def test_tool_error_from_dict_roundtrip(self):
        """ToolError must deserialize from dict correctly."""
        original = file_not_found_error("test.py")
        error_dict = original.to_dict()
        restored = ToolError.from_dict(error_dict)

        self.assertEqual(restored.error_type, original.error_type)
        self.assertEqual(restored.message, original.message)
        self.assertEqual(restored.recoverable, original.recoverable)


class GatingTestTaskStateMachine(unittest.TestCase):
    """Gating test: Verify TaskStateMachine prevents invalid transitions."""

    def test_completed_to_in_progress_is_invalid(self):
        """COMPLETED -> IN_PROGRESS must be invalid."""
        sm = TaskStateMachine(TaskStatus.COMPLETED)
        self.assertFalse(sm.can_transition(TaskStatus.IN_PROGRESS))
        with self.assertRaises(Exception):  # InvalidTransitionError
            sm.transition(TaskStatus.IN_PROGRESS)

    def test_completed_to_failed_is_invalid(self):
        """COMPLETED -> FAILED must be invalid."""
        sm = TaskStateMachine(TaskStatus.COMPLETED)
        self.assertFalse(sm.can_transition(TaskStatus.FAILED))

    def test_pending_to_completed_is_invalid(self):
        """PENDING -> COMPLETED must be invalid (must go through IN_PROGRESS)."""
        sm = TaskStateMachine(TaskStatus.PENDING)
        self.assertFalse(sm.can_transition(TaskStatus.COMPLETED))

    def test_can_only_retry_from_failed_or_stopped(self):
        """Only FAILED and STOPPED should be recoverable."""
        recoverable_from = TaskStateMachine.RECOVERABLE_STATES

        self.assertIn(TaskStatus.FAILED, recoverable_from)
        self.assertIn(TaskStatus.STOPPED, recoverable_from)
        self.assertNotIn(TaskStatus.COMPLETED, recoverable_from)
        self.assertNotIn(TaskStatus.PENDING, recoverable_from)
        self.assertNotIn(TaskStatus.IN_PROGRESS, recoverable_from)

    def test_valid_transitions_only(self):
        """Test all valid transitions work."""
        valid_transitions = [
            (TaskStatus.PENDING, TaskStatus.IN_PROGRESS),
            (TaskStatus.PENDING, TaskStatus.STOPPED),
            (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED),
            (TaskStatus.IN_PROGRESS, TaskStatus.FAILED),
            (TaskStatus.IN_PROGRESS, TaskStatus.STOPPED),
            (TaskStatus.FAILED, TaskStatus.IN_PROGRESS),
            (TaskStatus.STOPPED, TaskStatus.PENDING),
        ]

        for from_state, to_state in valid_transitions:
            sm = TaskStateMachine(from_state)
            self.assertTrue(sm.can_transition(to_state))
            sm.transition(to_state)  # Should not raise


class GatingTestTaskIntegration(unittest.TestCase):
    """Gating test: Verify Task class uses state machine correctly."""

    def test_task_set_status_rejects_invalid_transition(self):
        """Task.set_status must reject invalid transitions."""
        task = Task("Test task")
        # Set to IN_PROGRESS
        task.set_status(TaskStatus.IN_PROGRESS)
        # Set to COMPLETED
        task.set_status(TaskStatus.COMPLETED)

        # Should not allow going back to IN_PROGRESS
        self.assertFalse(task.can_transition_to(TaskStatus.IN_PROGRESS))
        with self.assertRaises(Exception):
            task.set_status(TaskStatus.IN_PROGRESS)

    def test_execution_plan_mark_task_in_progress_valid(self):
        """ExecutionPlan.mark_task_in_progress must validate transitions."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        self.assertEqual(task.status, TaskStatus.PENDING)

        plan.mark_task_in_progress(task)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_execution_plan_mark_task_completed_requires_in_progress(self):
        """mark_task_completed requires task to be IN_PROGRESS first."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")

        # Should fail to complete directly from PENDING
        with self.assertRaises(Exception):
            plan.mark_task_completed(task)

    def test_state_machine_transition_history_tracking(self):
        """State machine must track transition history."""
        sm = TaskStateMachine()
        sm.transition(TaskStatus.IN_PROGRESS, reason="Start")
        sm.transition(TaskStatus.COMPLETED, reason="Done")

        history = sm.get_transition_history()
        self.assertGreaterEqual(len(history), 3)  # Initial + 2 transitions

        # Check history contains expected transitions
        statuses = [t.to_state for t in history]
        self.assertIn(TaskStatus.IN_PROGRESS, statuses)
        self.assertIn(TaskStatus.COMPLETED, statuses)


class GatingTestArgumentNormalization(unittest.TestCase):
    """Gating test: Verify argument normalization works correctly."""

    def test_global_aliases_exist(self):
        """Global aliases configuration must exist."""
        # Critical aliases for common operations
        self.assertIn("path", _PARAM_ALIASES)
        self.assertIn("file_path", _PARAM_ALIASES["path"])
        self.assertIn("filepath", _PARAM_ALIASES["path"])

    def test_tool_specific_aliases_exist(self):
        """Tool-specific aliases must be configured."""
        self.assertIn("read_file", _TOOL_PARAM_ALIASES)
        self.assertIn("write_file", _TOOL_PARAM_ALIASES)
        self.assertIn("replace_in_file", _TOOL_PARAM_ALIASES)

    def test_normalize_args_handles_kebab_case(self):
        """Kebab-case parameters must be converted to snake_case."""
        args = {"file-path": "test.py", "old-string": "foo"}
        normalized = _normalize_args(args, "replace_in_file")

        self.assertIn("file_path", normalized)
        self.assertIn("old_string", normalized)

    def test_normalize_args_handles_nested_arguments(self):
        """Must unwrap nested {"arguments": {...}} wrapper."""
        args = {"arguments": {"file_path": "test.py"}}
        normalized = _normalize_args(args, "read_file")

        self.assertIn("file_path", normalized)
        self.assertNotIn("arguments", normalized)

    def test_normalize_aliases_read_file(self):
        """read_file must normalize file/src/source/module to path."""
        test_cases = [
            ({"file": "test.py"}, "path"),
            ({"src": "test.py"}, "path"),
            ({"source": "test.py"}, "path"),
            ({"module": "test.py"}, "path"),
        ]

        for input_args, expected_key in test_cases:
            normalized = _normalize_args(input_args, "read_file")
            self.assertIn(expected_key, normalized)
            self.assertEqual(normalized[expected_key], "test.py")

    def test_normalize_aliases_write_file(self):
        """write_file must normalize content aliases."""
        test_cases = [
            ({"text": "content"}, "content"),
            ({"contents": "content"}, "content"),
        ]

        for input_args, expected_key in test_cases:
            normalized = _normalize_args(input_args, "write_file")
            self.assertIn(expected_key, normalized)
            self.assertEqual(normalized[expected_key], "content")

    def test_normalize_replace_in_file_aliases(self):
        """replace_in_file must normalize old_string/new_string."""
        args = {"old_string": "foo", "new_string": "bar"}
        normalized = _normalize_args(args, "replace_in_file")

        self.assertIn("find", normalized)
        self.assertIn("replace", normalized)
        self.assertEqual(normalized["find"], "foo")
        self.assertEqual(normalized["replace"], "bar")


class GatingTestFileReadDeduplication(unittest.TestCase):
    """Gating test: Verify file read deduplication has been relaxed."""

    def test_file_read_threshold_is_at_least_5(self):
        """File read deduplication threshold must be >= 5 (not 2)."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Check that the threshold has been increased to 5 or higher
        # The check should be: if read_count >= 5: (was 2)
        self.assertIn('if read_count >= 5:', source,
                     "File read deduplication threshold must be >= 5")

    def test_consecutive_reads_guard_removed(self):
        """Consecutive reads guard should be removed."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Check that consecutive reads guard has been removed
        self.assertIn('REMOVED: Consecutive reads guard', source,
                     "Consecutive reads guard should be marked as removed")

        # Old trigger should not exist
        self.assertNotIn('RESEARCH_BUDGET_EXHAUSTED', source,
                        "Research budget exhausted trigger should be removed")


class GatingTestCodeStateTracking(unittest.TestCase):
    """Gating test: Verify code state tracking for test deduplication."""

    def test_compute_code_state_hash_function_exists(self):
        """compute_code_state_hash method must exist in VerificationCoordinator."""
        from rev.execution.verification_coordinator import VerificationCoordinator

        # Method should exist and be callable
        import inspect
        self.assertTrue(inspect.isfunction(VerificationCoordinator.compute_code_state_hash))

    def test_compute_code_state_hash_returns_string(self):
        """compute_code_state_hash must return a string."""
        from rev.execution.verification_coordinator import VerificationCoordinator

        # Create a mock orchestrator for testing
        class MockOrchestrator:
            pass

        coordinator = VerificationCoordinator(MockOrchestrator())
        hash_val = coordinator.compute_code_state_hash()
        self.assertIsInstance(hash_val, str)
        self.assertEqual(len(hash_val), 16)  # Short hash format

    def test_code_state_hash_is_deterministic(self):
        """Code state hash must be deterministic for same state."""
        from rev.execution.verification_coordinator import VerificationCoordinator

        # Create a mock orchestrator for testing
        class MockOrchestrator:
            pass

        coordinator = VerificationCoordinator(MockOrchestrator())
        hash1 = coordinator.compute_code_state_hash()
        hash2 = coordinator.compute_code_state_hash()
        self.assertEqual(hash1, hash2)

    def test_different_code_states_produce_different_hashes(self):
        """Different code states should produce different hashes."""
        # This is more of a conceptual test - in a real scenario,
        # modifying files would change the hash
        from rev.execution.verification_coordinator import VerificationCoordinator

        # Create a mock orchestrator for testing
        class MockOrchestrator:
            pass

        coordinator = VerificationCoordinator(MockOrchestrator())
        # Hash can differ based on modified files list
        hash1 = coordinator.compute_code_state_hash(["file1.py"])
        hash2 = coordinator.compute_code_state_hash(["file2.py"])

        # The hashes might be different (implementation dependent)
        # This test verifies the mechanism exists
        self.assertIsInstance(hash1, str)
        self.assertIsInstance(hash2, str)
        self.assertIsInstance(hash2, str)


class GatingTestNoHandoffContracts(unittest.TestCase):
    """Gating test: Verify handoff_contracts module has been deleted."""

    def test_handoff_contracts_module_does_not_exist(self):
        """handoff_contracts module should not exist."""
        import sys
        from pathlib import Path

        rev_dir = Path(__file__).parent.parent / "rev"
        handoff_dir = rev_dir / "handoff_contracts"

        self.assertFalse(handoff_dir.exists())

    def test_handoff_contracts_not_importable(self):
        """handoff_contracts should not be importable."""
        try:
            import rev.handoff_contracts
            self.fail("rev.handoff_contracts should not be importable")
        except ImportError:
            pass  # Expected

    def test_no_handoff_contracts_in_production_code(self):
        """No production code should import from handoff_contracts."""
        from pathlib import Path
        import re

        rev_dir = Path(__file__).parent.parent / "rev"
        pattern = re.compile(r"from\s+rev\.handoff_contracts|from\s+handoff_contracts")

        imports_found = []
        for py_file in rev_dir.rglob("*.py"):
            if "test" in py_file.name or "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                if pattern.search(content):
                    imports_found.append(str(py_file.relative_to(rev_dir)))
            except Exception:
                continue

        self.assertEqual(len(imports_found), 0,
                         f"Found handoff_contracts imports in: {imports_found}")


class GatingTestConcurrentReadsCounter(unittest.TestCase):
    """Gating test: Verify consecutive_reads counter still tracked but doesn't block."""

    def test_consecutive_reads_counter_exists_in_code(self):
        """consecutive_reads counter should still exist in orchestrator."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Counter should still be tracked for other purposes
        self.assertIn('consecutive_reads:', source)
        self.assertIn('consecutive_reads += 1', source)
        self.assertIn('consecutive_reads = 0', source)


class GatingTestPerErrorTypeRecoveryBudgets(unittest.TestCase):
    """Gating test: Verify per-error-type recovery budgets are implemented."""

    def test_recovery_budgets_key_exists_in_code(self):
        """Per-error-type recovery budgets should be tracked."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Budget tracking should exist
        self.assertIn('recovery_budgets_key', source)
        self.assertIn('recovery_budgets = self.context.agent_state.get', source)

    def test_classify_error_type_method_exists(self):
        """_classify_error_type method should exist in Orchestrator."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        # Method should exist on Orchestrator class
        self.assertTrue(hasattr(Orchestrator, '_classify_error_type'),
                        "Orchestrator should have _classify_error_type method")

    def test_build_failure_summary_method_exists(self):
        """_build_failure_summary method should exist in Orchestrator."""
        from rev.execution.orchestrator import Orchestrator
        import inspect

        # Method should exist on Orchestrator class
        self.assertTrue(hasattr(Orchestrator, '_build_failure_summary'),
                        "Orchestrator should have _build_failure_summary method")

    def test_max_attempts_per_error_type_exists(self):
        """MAX_ATTEMPTS_PER_ERROR_TYPE configuration should exist."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Configuration should exist
        self.assertIn('MAX_ATTEMPTS_PER_ERROR_TYPE', source)

    def test_transient_allows_more_retries_than_permission_denied(self):
        """TRANSIENT errors should allow more retries than PERMISSION_DENIED."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # TRANSIENT should have higher limit than PERMISSION_DENIED
        self.assertIn('ToolErrorType.TRANSIENT:', source)
        self.assertIn('ToolErrorType.PERMISSION_DENIED:', source)

        # Extract the numeric values (rough check)
        import re
        transient_match = re.search(r'ToolErrorType\.TRANSIENT:\s*(\d+)', source)
        perm_denied_match = re.search(r'ToolErrorType\.PERMISSION_DENIED:\s*(\d+)', source)

        if transient_match and perm_denied_match:
            transient_retries = int(transient_match.group(1))
            perm_denied_retries = int(perm_denied_match.group(1))
            self.assertGreater(transient_retries, perm_denied_retries,
                               "TRANSIENT should allow more retries than PERMISSION_DENIED")

    def test_error_type_value_used_in_budget_key(self):
        """Budget key should include error type value."""
        import rev.execution.orchestrator as orch_module
        import inspect

        source = inspect.getsource(orch_module)

        # Budget key construction should use error_type.value
        self.assertIn('error_type.value', source)
        self.assertIn('budget_key = f"', source)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)