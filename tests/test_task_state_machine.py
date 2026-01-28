#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Task State Machine.

Tests the state machine that enforces valid task status transitions.
"""

import unittest
from time import sleep
from rev.models.task import (
    TaskStatus,
    Task,
    TaskStateMachine,
    InvalidTransitionError,
    ExecutionPlan,
)


class TestTaskStateMachine(unittest.TestCase):
    """Test TaskStateMachine class."""

    def test_initial_state(self):
        """State machine starts in PENDING state by default."""
        sm = TaskStateMachine()
        self.assertEqual(sm.current_state, TaskStatus.PENDING)

    def test_initial_state_custom(self):
        """State machine can start with custom initial state."""
        sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertEqual(sm.current_state, TaskStatus.IN_PROGRESS)

    def test_valid_transition_pending_to_in_progress(self):
        """PENDING -> IN_PROGRESS is valid."""
        sm = TaskStateMachine()
        self.assertTrue(sm.can_transition(TaskStatus.IN_PROGRESS))
        transition = sm.transition(TaskStatus.IN_PROGRESS)
        self.assertEqual(sm.current_state, TaskStatus.IN_PROGRESS)
        self.assertEqual(transition.from_state, TaskStatus.PENDING)
        self.assertEqual(transition.to_state, TaskStatus.IN_PROGRESS)

    def test_valid_transition_pending_to_stopped(self):
        """PENDING -> STOPPED is valid."""
        sm = TaskStateMachine()
        self.assertTrue(sm.can_transition(TaskStatus.STOPPED))
        sm.transition(TaskStatus.STOPPED)
        self.assertEqual(sm.current_state, TaskStatus.STOPPED)

    def test_valid_transition_in_progress_to_completed(self):
        """IN_PROGRESS -> COMPLETED is valid."""
        sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertTrue(sm.can_transition(TaskStatus.COMPLETED))
        sm.transition(TaskStatus.COMPLETED)
        self.assertEqual(sm.current_state, TaskStatus.COMPLETED)

    def test_valid_transition_in_progress_to_failed(self):
        """IN_PROGRESS -> FAILED is valid."""
        sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertTrue(sm.can_transition(TaskStatus.FAILED))
        sm.transition(TaskStatus.FAILED)
        self.assertEqual(sm.current_state, TaskStatus.FAILED)

    def test_valid_transition_in_progress_to_stopped(self):
        """IN_PROGRESS -> STOPPED is valid."""
        sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertTrue(sm.can_transition(TaskStatus.STOPPED))
        sm.transition(TaskStatus.STOPPED)
        self.assertEqual(sm.current_state, TaskStatus.STOPPED)

    def test_valid_transition_failed_to_in_progress(self):
        """FAILED -> IN_PROGRESS is valid (retry)."""
        sm = TaskStateMachine(TaskStatus.FAILED)
        self.assertTrue(sm.can_transition(TaskStatus.IN_PROGRESS))
        sm.transition(TaskStatus.IN_PROGRESS)
        self.assertEqual(sm.current_state, TaskStatus.IN_PROGRESS)

    def test_valid_transition_stopped_to_pending(self):
        """STOPPED -> PENDING is valid (replan/resume)."""
        sm = TaskStateMachine(TaskStatus.STOPPED)
        self.assertTrue(sm.can_transition(TaskStatus.PENDING))
        sm.transition(TaskStatus.PENDING)
        self.assertEqual(sm.current_state, TaskStatus.PENDING)

    def test_invalid_transition_completed_to_in_progress(self):
        """COMPLETED -> IN_PROGRESS is invalid."""
        sm = TaskStateMachine(TaskStatus.COMPLETED)
        self.assertFalse(sm.can_transition(TaskStatus.IN_PROGRESS))
        with self.assertRaises(InvalidTransitionError):
            sm.transition(TaskStatus.IN_PROGRESS)

    def test_invalid_transition_in_progress_to_pending(self):
        """IN_PROGRESS -> PENDING is invalid."""
        sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertFalse(sm.can_transition(TaskStatus.PENDING))
        with self.assertRaises(InvalidTransitionError):
            sm.transition(TaskStatus.PENDING)

    def test_invalid_transition_pending_to_completed(self):
        """PENDING -> COMPLETED is invalid (must go through IN_PROGRESS first)."""
        sm = TaskStateMachine()
        self.assertFalse(sm.can_transition(TaskStatus.COMPLETED))
        with self.assertRaises(InvalidTransitionError):
            sm.transition(TaskStatus.COMPLETED)

    def test_transition_history_tracking(self):
        """State machine tracks all transitions."""
        sm = TaskStateMachine()
        sm.transition(TaskStatus.IN_PROGRESS, reason="Started")
        sm.transition(TaskStatus.COMPLETED, reason="Done")

        history = sm.get_transition_history()
        self.assertEqual(len(history), 3)  # Initial + 2 transitions

        # First transition is initial state
        self.assertIsNone(history[0].from_state)
        self.assertEqual(history[0].to_state, TaskStatus.PENDING)

        # Second transition
        self.assertEqual(history[1].from_state, TaskStatus.PENDING)
        self.assertEqual(history[1].to_state, TaskStatus.IN_PROGRESS)
        self.assertEqual(history[1].reason, "Started")

        # Third transition
        self.assertEqual(history[2].from_state, TaskStatus.IN_PROGRESS)
        self.assertEqual(history[2].to_state, TaskStatus.COMPLETED)
        self.assertEqual(history[2].reason, "Done")

    def test_transition_metadata(self):
        """Transitions can include metadata."""
        sm = TaskStateMachine()
        sm.transition(TaskStatus.IN_PROGRESS, metadata={"attempt": 1})
        sm.transition(TaskStatus.FAILED, reason="Error occurred", metadata={"error_code": 500})

        history = sm.get_transition_history()
        self.assertEqual(history[1].metadata, {"attempt": 1})
        self.assertEqual(history[2].metadata, {"error_code": 500})
        self.assertEqual(history[2].reason, "Error occurred")

    def test_is_terminal(self):
        """Terminal states are correctly identified."""
        completed_sm = TaskStateMachine(TaskStatus.COMPLETED)
        self.assertTrue(completed_sm.is_terminal())

        in_progress_sm = TaskStateMachine(TaskStatus.IN_PROGRESS)
        self.assertFalse(in_progress_sm.is_terminal())

        pending_sm = TaskStateMachine()
        self.assertFalse(pending_sm.is_terminal())

    def test_is_recoverable(self):
        """Recoverable states are correctly identified."""
        failed_sm = TaskStateMachine(TaskStatus.FAILED)
        self.assertTrue(failed_sm.is_recoverable())

        stopped_sm = TaskStateMachine(TaskStatus.STOPPED)
        self.assertTrue(stopped_sm.is_recoverable())

        completed_sm = TaskStateMachine(TaskStatus.COMPLETED)
        self.assertFalse(completed_sm.is_recoverable())

    def test_get_valid_transitions(self):
        """Can get list of valid transitions from current state."""
        sm = TaskStateMachine()
        valid = sm.get_valid_transitions()
        self.assertIn(TaskStatus.IN_PROGRESS, valid)
        self.assertIn(TaskStatus.STOPPED, valid)
        self.assertNotIn(TaskStatus.COMPLETED, valid)

        sm.transition(TaskStatus.IN_PROGRESS)
        valid = sm.get_valid_transitions()
        self.assertIn(TaskStatus.COMPLETED, valid)
        self.assertIn(TaskStatus.FAILED, valid)
        self.assertIn(TaskStatus.STOPPED, valid)

    def test_static_validate_transition(self):
        """Static method can validate transitions without instance."""
        self.assertTrue(TaskStateMachine.validate_transition(
            TaskStatus.PENDING, TaskStatus.IN_PROGRESS
        ))
        self.assertFalse(TaskStateMachine.validate_transition(
            TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS
        ))

    def test_state_duration(self):
        """Can calculate duration spent in each state."""
        sm = TaskStateMachine()
        sleep(0.01)  # Small delay

        sm.transition(TaskStatus.IN_PROGRESS)
        sleep(0.01)

        sm.transition(TaskStatus.COMPLETED)

        pending_duration = sm.get_state_duration(TaskStatus.PENDING)
        in_progress_duration = sm.get_state_duration(TaskStatus.IN_PROGRESS)
        completed_duration = sm.get_state_duration(TaskStatus.COMPLETED)

        # Should have spent time in PENDING and IN_PROGRESS
        self.assertIsNotNone(pending_duration)
        self.assertGreater(pending_duration, 0)

        self.assertIsNotNone(in_progress_duration)
        self.assertGreater(in_progress_duration, 0)

        # COMPLETED is current state, duration should be tracked
        self.assertIsNotNone(completed_duration)
        self.assertGreaterEqual(completed_duration, 0)

    def test_to_dict(self):
        """State machine can be serialized to dict."""
        sm = TaskStateMachine()
        sm.transition(TaskStatus.IN_PROGRESS, reason="Test")
        sm.transition(TaskStatus.COMPLETED)

        data = sm.to_dict()
        self.assertEqual(data["current_state"], "completed")
        self.assertTrue(data["is_terminal"])
        self.assertFalse(data["is_recoverable"])
        self.assertEqual(data["transition_count"], 3)
        self.assertEqual(len(data["transitions"]), 3)

    def test_full_workflow_transitions(self):
        """Simulate full task lifecycle with valid transitions."""
        sm = TaskStateMachine()
        self.assertEqual(sm.current_state, TaskStatus.PENDING)

        sm.transition(TaskStatus.IN_PROGRESS, reason="Task started")
        self.assertEqual(sm.current_state, TaskStatus.IN_PROGRESS)

        sm.transition(TaskStatus.FAILED, reason="Task failed")
        self.assertEqual(sm.current_state, TaskStatus.FAILED)

        sm.transition(TaskStatus.IN_PROGRESS, reason="Retrying task")
        self.assertEqual(sm.current_state, TaskStatus.IN_PROGRESS)

        sm.transition(TaskStatus.COMPLETED, reason="Task completed on retry")
        self.assertEqual(sm.current_state, TaskStatus.COMPLETED)

        # Should have 5 transitions (initial + 4 state changes)
        self.assertEqual(len(sm.get_transition_history()), 5)
        self.assertTrue(sm.is_terminal())
        self.assertFalse(sm.is_recoverable())


class TestTaskWithStateMachine(unittest.TestCase):
    """Test Task class with integrated state machine."""

    def test_task_initial_state(self):
        """Task starts in PENDING state."""
        task = Task("Test task")
        self.assertEqual(task.status, TaskStatus.PENDING)

    def test_task_status_property(self):
        """Task status property works correctly."""
        task = Task("Test task")
        self.assertEqual(task.status, TaskStatus.PENDING)
        task.set_status(TaskStatus.IN_PROGRESS)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_task_set_status_valid_transition(self):
        """set_status() validates transitions."""
        task = Task("Test task")
        task.set_status(TaskStatus.IN_PROGRESS, reason="Starting")
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        task.set_status(TaskStatus.COMPLETED, reason="Done")
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_task_set_status_invalid_transition_raises(self):
        """set_status() raises InvalidTransitionError for invalid transition."""
        task = Task("Test task")
        task.set_status(TaskStatus.IN_PROGRESS)
        task.set_status(TaskStatus.COMPLETED)

        with self.assertRaises(InvalidTransitionError):
            task.set_status(TaskStatus.IN_PROGRESS)

    def test_task_status_setter_backwards_compat(self):
        """Direct status assignment still works (backwards compatible)."""
        task = Task("Test task")
        # Old code that directly sets status
        task.status = TaskStatus.IN_PROGRESS
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        # Even invalid transitions work for backwards compat (log but don't raise)
        task.status = TaskStatus.PENDING
        self.assertEqual(task.status, TaskStatus.PENDING)

    def test_task_can_transition_to(self):
        """can_transition_to() checks if transition is valid."""
        task = Task("Test task")
        self.assertTrue(task.can_transition_to(TaskStatus.IN_PROGRESS))
        self.assertFalse(task.can_transition_to(TaskStatus.COMPLETED))

    def test_task_is_terminal(self):
        """is_terminal() works correctly."""
        task = Task("Test task")
        self.assertFalse(task.is_terminal())

        task.set_status(TaskStatus.IN_PROGRESS)
        self.assertFalse(task.is_terminal())

        task.set_status(TaskStatus.COMPLETED)
        self.assertTrue(task.is_terminal())

    def test_task_is_recoverable(self):
        """is_recoverable() works correctly."""
        task = Task("Test task")
        task.set_status(TaskStatus.IN_PROGRESS)
        self.assertFalse(task.is_recoverable())

        task.set_status(TaskStatus.FAILED)
        self.assertTrue(task.is_recoverable())

    def test_task_get_state_history(self):
        """get_state_history() returns transition history."""
        task = Task("Test task")
        task.set_status(TaskStatus.IN_PROGRESS, reason="Start")
        task.set_status(TaskStatus.FAILED, reason="Failed")

        history = task.get_state_history()
        self.assertGreaterEqual(len(history), 3)  # Initial + 2 transitions

    def test_task_to_dict_includes_state_machine(self):
        """Task.to_dict() includes state machine info."""
        task = Task("Test task")
        task.set_status(TaskStatus.IN_PROGRESS, reason="Test")

        data = task.to_dict()
        self.assertIn("state_machine", data)
        self.assertEqual(data["state_machine"]["current_state"], "in_progress")
        self.assertIn("transitions", data["state_machine"])

    def test_task_from_dict_restores_state(self):
        """Task.from_dict() restores task state properly."""
        original = Task("Test task", action_type="edit")
        original.set_status(TaskStatus.IN_PROGRESS, reason="Test")
        original.task_id = 42
        original.result = "Partial result"

        data = original.to_dict()
        restored = Task.from_dict(data)

        self.assertEqual(restored.description, "Test task")
        self.assertEqual(restored.action_type, "edit")
        self.assertEqual(restored.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(restored.task_id, 42)

    def test_task_from_dict_unknown_status_defaults(self):
        """Unknown status defaults to PENDING."""
        data = {
            "description": "Test",
            "action_type": "general",
            "status": "invalid_status",
            "dependencies": [],
        }
        task = Task.from_dict(data)
        self.assertEqual(task.status, TaskStatus.PENDING)


class TestExecutionPlanWithStateMachine(unittest.TestCase):
    """Test ExecutionPlan methods with state machine integration."""

    def test_mark_task_in_progress_valid(self):
        """mark_task_in_progress() performs valid transition."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        self.assertEqual(task.status, TaskStatus.PENDING)

        plan.mark_task_in_progress(task)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_mark_task_completed_valid(self):
        """mark_task_completed() performs valid transition."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        plan.mark_task_in_progress(task)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        plan.mark_task_completed(task, result="Success")
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.result, "Success")

    def test_mark_task_failed_valid(self):
        """mark_task_failed() performs valid transition."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        plan.mark_task_in_progress(task)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        plan.mark_task_failed(task, error="Something went wrong")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.error, "Something went wrong")

    def test_mark_task_stopped_valid(self):
        """mark_task_stopped() performs valid transition."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        self.assertEqual(task.status, TaskStatus.PENDING)

        plan.mark_task_stopped(task)
        self.assertEqual(task.status, TaskStatus.STOPPED)

    def test_mark_task_stopped_after_in_progress(self):
        """Can stop a task that's in progress."""
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        plan.mark_task_in_progress(task)

        plan.mark_task_stopped(task, reason="User stopped")
        self.assertEqual(task.status, TaskStatus.STOPPED)

    def test_mark_completed_legacy_method(self):
        """Legacy mark_completed() method still works."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        plan.mark_completed("Done with first")
        self.assertEqual(plan.current_index, 1)
        self.assertEqual(plan.tasks[0].status, TaskStatus.COMPLETED)

    def test_mark_failed_legacy_method(self):
        """Legacy mark_failed() method still works."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        plan.mark_failed("First task failed")
        self.assertEqual(plan.current_index, 1)
        self.assertEqual(plan.tasks[0].status, TaskStatus.FAILED)
        self.assertEqual(plan.tasks[0].error, "First task failed")


if __name__ == "__main__":
    unittest.main()