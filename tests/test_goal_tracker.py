#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for GoalTracker functionality.

Tests the goal tracking module that provides traceability by mapping
changes to goals and tracking goal progress.
"""

import unittest
from rev.execution.goal_tracker import (
    GoalTracker,
    Goal,
    GoalStatus,
    GoalPriority,
    GoalChange,
)
from rev.models.task import Task, ExecutionPlan


class TestGoalStatus(unittest.TestCase):
    """Test GoalStatus enum."""

    def test_goal_status_values(self):
        """GoalStatus enum should have correct values."""
        self.assertEqual(GoalStatus.NOT_STARTED.value, "not_started")
        self.assertEqual(GoalStatus.IN_PROGRESS.value, "in_progress")
        self.assertEqual(GoalStatus.COMPLETED.value, "completed")
        self.assertEqual(GoalStatus.FAILED.value, "failed")
        self.assertEqual(GoalStatus.BLOCKED.value, "blocked")
        self.assertEqual(GoalStatus.CANCELLED.value, "cancelled")

    def test_goal_priority_values(self):
        """GoalPriority enum should have correct values."""
        self.assertEqual(GoalPriority.LOW.value, 1)
        self.assertEqual(GoalPriority.MEDIUM.value, 2)
        self.assertEqual(GoalPriority.HIGH.value, 3)
        self.assertEqual(GoalPriority.CRITICAL.value, 4)


class TestGoalChange(unittest.TestCase):
    """Test GoalChange dataclass."""

    def test_goal_change_creation(self):
        """GoalChange should be created with correct attributes."""
        task = Task("Test task")
        change = GoalChange(
            change_id="change_1",
            goal_id="goal_1",
            task=task,
            file_path="test.py",
            change_type="modify",
            description="Modified test.py",
        )

        self.assertEqual(change.change_id, "change_1")
        self.assertEqual(change.goal_id, "goal_1")
        self.assertEqual(change.task, task)
        self.assertEqual(change.file_path, "test.py")
        self.assertEqual(change.change_type, "modify")
        self.assertEqual(change.description, "Modified test.py")

    def test_goal_change_to_dict(self):
        """GoalChange.to_dict should return correct dictionary."""
        task = Task("Test task")
        change = GoalChange(
            change_id="change_1",
            goal_id="goal_1",
            task=task,
            file_path="test.py",
            change_type="modify",
        )

        change_dict = change.to_dict()

        self.assertEqual(change_dict["change_id"], "change_1")
        self.assertEqual(change_dict["goal_id"], "goal_1")
        self.assertEqual(change_dict["task_id"], task.task_id)
        self.assertEqual(change_dict["file_path"], "test.py")
        self.assertEqual(change_dict["change_type"], "modify")


class TestGoal(unittest.TestCase):
    """Test Goal dataclass."""

    def test_goal_creation(self):
        """Goal should be created with correct attributes."""
        goal = Goal(
            goal_id="goal_1",
            description="Test goal",
            status=GoalStatus.NOT_STARTED,
            priority=GoalPriority.MEDIUM,
        )

        self.assertEqual(goal.goal_id, "goal_1")
        self.assertEqual(goal.description, "Test goal")
        self.assertEqual(goal.status, GoalStatus.NOT_STARTED)
        self.assertEqual(goal.priority, GoalPriority.MEDIUM)
        self.assertEqual(len(goal.changes), 0)
        self.assertIsNone(goal.parent_goal_id)
        self.assertEqual(goal.child_goal_ids, [])

    def test_goal_add_change(self):
        """Goal.add_change should add a change and update timestamp."""
        goal = Goal(goal_id="goal_1", description="Test goal")
        initial_updated = goal.updated_at

        change = GoalChange(
            change_id="change_1",
            goal_id="goal_1",
            change_type="modify",
        )

        goal.add_change(change)

        self.assertEqual(len(goal.changes), 1)
        self.assertEqual(goal.changes[0], change)
        self.assertGreater(goal.updated_at, initial_updated)

    def test_goal_mark_started(self):
        """Goal.mark_started should update status and timestamp."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.NOT_STARTED)

        goal.mark_started()

        self.assertEqual(goal.status, GoalStatus.IN_PROGRESS)

    def test_goal_mark_completed(self):
        """Goal.mark_completed should update status and set completion time."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.IN_PROGRESS)

        goal.mark_completed()

        self.assertEqual(goal.status, GoalStatus.COMPLETED)
        self.assertIsNotNone(goal.completed_at)

    def test_goal_mark_failed(self):
        """Goal.mark_failed should update status and timestamp."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.IN_PROGRESS)

        goal.mark_failed()

        self.assertEqual(goal.status, GoalStatus.FAILED)

    def test_goal_mark_blocked(self):
        """Goal.mark_blocked should update status and timestamp."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.IN_PROGRESS)

        goal.mark_blocked()

        self.assertEqual(goal.status, GoalStatus.BLOCKED)

    def test_goal_add_child_goal(self):
        """Goal.add_child_goal should add child goal ID."""
        goal = Goal(goal_id="goal_1", description="Test goal")

        goal.add_child_goal("goal_2")
        goal.add_child_goal("goal_3")

        self.assertEqual(len(goal.child_goal_ids), 2)
        self.assertIn("goal_2", goal.child_goal_ids)
        self.assertIn("goal_3", goal.child_goal_ids)

    def test_goal_add_child_goal_duplicate(self):
        """Goal.add_child_goal should not add duplicate child goal IDs."""
        goal = Goal(goal_id="goal_1", description="Test goal")

        goal.add_child_goal("goal_2")
        goal.add_child_goal("goal_2")

        self.assertEqual(len(goal.child_goal_ids), 1)
        self.assertIn("goal_2", goal.child_goal_ids)

    def test_goal_get_progress_leaf_goal_not_started(self):
        """Goal.get_progress should return 0.0 for NOT_STARTED leaf goal."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.NOT_STARTED)
        self.assertEqual(goal.get_progress(), 0.0)

    def test_goal_get_progress_leaf_goal_in_progress(self):
        """Goal.get_progress should return 0.5 for IN_PROGRESS leaf goal."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.IN_PROGRESS)
        self.assertEqual(goal.get_progress(), 0.5)

    def test_goal_get_progress_leaf_goal_completed(self):
        """Goal.get_progress should return 1.0 for COMPLETED leaf goal."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.COMPLETED)
        self.assertEqual(goal.get_progress(), 1.0)

    def test_goal_get_progress_leaf_goal_failed(self):
        """Goal.get_progress should return 0.0 for FAILED leaf goal."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.FAILED)
        self.assertEqual(goal.get_progress(), 0.0)

    def test_goal_get_progress_leaf_goal_blocked(self):
        """Goal.get_progress should return 0.0 for BLOCKED leaf goal."""
        goal = Goal(goal_id="goal_1", description="Test goal", status=GoalStatus.BLOCKED)
        self.assertEqual(goal.get_progress(), 0.0)

    def test_goal_to_dict(self):
        """Goal.to_dict should return correct dictionary."""
        goal = Goal(
            goal_id="goal_1",
            description="Test goal",
            status=GoalStatus.COMPLETED,
            priority=GoalPriority.HIGH,
        )

        goal_dict = goal.to_dict()

        self.assertEqual(goal_dict["goal_id"], "goal_1")
        self.assertEqual(goal_dict["description"], "Test goal")
        self.assertEqual(goal_dict["status"], "completed")
        self.assertEqual(goal_dict["priority"], 3)
        self.assertEqual(goal_dict["progress"], 1.0)


class TestGoalTracker(unittest.TestCase):
    """Test GoalTracker class."""

    def test_goal_tracker_initialization(self):
        """GoalTracker should initialize with empty state."""
        tracker = GoalTracker()

        self.assertEqual(len(tracker._goals), 0)
        self.assertEqual(tracker._goal_counter, 0)

    def test_create_goal_basic(self):
        """GoalTracker.create_goal should create a goal with correct attributes."""
        tracker = GoalTracker()

        goal = tracker.create_goal(
            description="Test goal",
            priority=GoalPriority.HIGH,
        )

        self.assertEqual(goal.description, "Test goal")
        self.assertEqual(goal.priority, GoalPriority.HIGH)
        self.assertEqual(goal.status, GoalStatus.NOT_STARTED)
        self.assertEqual(goal.goal_id, "goal_1")
        self.assertIn(goal.goal_id, tracker._goals)

    def test_create_goal_with_parent(self):
        """GoalTracker.create_goal should create child goal linked to parent."""
        tracker = GoalTracker()

        parent_goal = tracker.create_goal(description="Parent goal")
        child_goal = tracker.create_goal(
            description="Child goal",
            parent_goal_id=parent_goal.goal_id,
        )

        self.assertEqual(child_goal.parent_goal_id, parent_goal.goal_id)
        self.assertIn(child_goal.goal_id, parent_goal.child_goal_ids)

    def test_create_goal_multiple_goals(self):
        """GoalTracker.create_goal should create multiple goals with unique IDs."""
        tracker = GoalTracker()

        goal1 = tracker.create_goal(description="Goal 1")
        goal2 = tracker.create_goal(description="Goal 2")
        goal3 = tracker.create_goal(description="Goal 3")

        self.assertEqual(goal1.goal_id, "goal_1")
        self.assertEqual(goal2.goal_id, "goal_2")
        self.assertEqual(goal3.goal_id, "goal_3")
        self.assertEqual(tracker._goal_counter, 3)

    def test_get_goal_existing(self):
        """GoalTracker.get_goal should return goal if it exists."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        retrieved = tracker.get_goal(goal.goal_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.goal_id, goal.goal_id)

    def test_get_goal_nonexistent(self):
        """GoalTracker.get_goal should return None for nonexistent goal."""
        tracker = GoalTracker()

        retrieved = tracker.get_goal("goal_999")

        self.assertIsNone(retrieved)

    def test_get_all_goals(self):
        """GoalTracker.get_all_goals should return all goals."""
        tracker = GoalTracker()

        tracker.create_goal(description="Goal 1")
        tracker.create_goal(description="Goal 2")
        tracker.create_goal(description="Goal 3")

        goals = tracker.get_all_goals()

        self.assertEqual(len(goals), 3)

    def test_get_root_goals(self):
        """GoalTracker.get_root_goals should return only goals without parents."""
        tracker = GoalTracker()

        parent = tracker.create_goal(description="Parent goal")
        child = tracker.create_goal(description="Child goal", parent_goal_id=parent.goal_id)
        root = tracker.create_goal(description="Another root goal")

        root_goals = tracker.get_root_goals()

        self.assertEqual(len(root_goals), 2)
        self.assertIn(parent.goal_id, [g.goal_id for g in root_goals])
        self.assertIn(root.goal_id, [g.goal_id for g in root_goals])
        self.assertNotIn(child.goal_id, [g.goal_id for g in root_goals])

    def test_get_child_goals(self):
        """GoalTracker.get_child_goals should return children of parent goal."""
        tracker = GoalTracker()

        parent = tracker.create_goal(description="Parent goal")
        child1 = tracker.create_goal(description="Child 1", parent_goal_id=parent.goal_id)
        child2 = tracker.create_goal(description="Child 2", parent_goal_id=parent.goal_id)

        child_goals = tracker.get_child_goals(parent.goal_id)

        self.assertEqual(len(child_goals), 2)
        self.assertIn(child1.goal_id, [g.goal_id for g in child_goals])
        self.assertIn(child2.goal_id, [g.goal_id for g in child_goals])

    def test_update_goal_status(self):
        """GoalTracker.update_goal_status should update goal status."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        tracker.update_goal_status(goal.goal_id, GoalStatus.IN_PROGRESS)

        self.assertEqual(tracker.get_goal(goal.goal_id).status, GoalStatus.IN_PROGRESS)

    def test_update_goal_status_to_completed(self):
        """GoalTracker.update_goal_status should set completed_at when marking completed."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        self.assertIsNone(tracker.get_goal(goal.goal_id).completed_at)

        tracker.update_goal_status(goal.goal_id, GoalStatus.COMPLETED)

        self.assertIsNotNone(tracker.get_goal(goal.goal_id).completed_at)

    def test_map_task_to_goal(self):
        """GoalTracker.map_task_to_goal should create and add change to goal."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        plan = ExecutionPlan()
        task = plan.add_task("Test task")

        change = tracker.map_task_to_goal(task, goal.goal_id, change_type="modify")

        self.assertEqual(change.goal_id, goal.goal_id)
        self.assertEqual(change.task, task)
        self.assertEqual(change.change_type, "modify")
        self.assertEqual(len(tracker.get_changes_for_goal(goal.goal_id)), 1)

    def test_map_task_to_goal_marks_in_progress(self):
        """GoalTracker.map_task_to_goal should mark goal as in progress if not started."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        plan = ExecutionPlan()
        task = plan.add_task("Test task")

        self.assertEqual(goal.status, GoalStatus.NOT_STARTED)

        tracker.map_task_to_goal(task, goal.goal_id)

        self.assertEqual(tracker.get_goal(goal.goal_id).status, GoalStatus.IN_PROGRESS)

    def test_get_changes_for_goal(self):
        """GoalTracker.get_changes_for_goal should return all changes for goal."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        plan = ExecutionPlan()

        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")

        tracker.map_task_to_goal(task1, goal.goal_id, change_type="create")
        tracker.map_task_to_goal(task2, goal.goal_id, change_type="modify")

        changes = tracker.get_changes_for_goal(goal.goal_id)

        self.assertEqual(len(changes), 2)

    def test_get_goal_progress_leaf_goal(self):
        """GoalTracker.get_goal_progress should calculate progress for leaf goal."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        tracker.update_goal_status(goal.goal_id, GoalStatus.IN_PROGRESS)

        progress = tracker.get_goal_progress(goal.goal_id)

        self.assertEqual(progress, 0.5)

    def test_get_goal_progress_parent_goal(self):
        """GoalTracker.get_goal_progress should calculate average progress for parent."""
        tracker = GoalTracker()

        parent = tracker.create_goal(description="Parent goal")
        child1 = tracker.create_goal(description="Child 1", parent_goal_id=parent.goal_id)
        child2 = tracker.create_goal(description="Child 2", parent_goal_id=parent.goal_id)

        tracker.update_goal_status(child1.goal_id, GoalStatus.COMPLETED)
        tracker.update_goal_status(child2.goal_id, GoalStatus.NOT_STARTED)

        # (1.0 + 0.0) / 2 = 0.5
        progress = tracker.get_goal_progress(parent.goal_id)

        self.assertEqual(progress, 0.5)

    def test_get_goals_by_status(self):
        """GoalTracker.get_goals_by_status should filter by status."""
        tracker = GoalTracker()

        goal1 = tracker.create_goal(description="Goal 1")
        goal2 = tracker.create_goal(description="Goal 2")
        goal3 = tracker.create_goal(description="Goal 3")

        tracker.update_goal_status(goal1.goal_id, GoalStatus.COMPLETED)
        tracker.update_goal_status(goal2.goal_id, GoalStatus.COMPLETED)
        tracker.update_goal_status(goal3.goal_id, GoalStatus.IN_PROGRESS)

        completed = tracker.get_goals_by_status(GoalStatus.COMPLETED)
        in_progress = tracker.get_goals_by_status(GoalStatus.IN_PROGRESS)

        self.assertEqual(len(completed), 2)
        self.assertEqual(len(in_progress), 1)

    def test_get_goals_by_priority(self):
        """GoalTracker.get_goals_by_priority should filter by priority."""
        tracker = GoalTracker()

        goal1 = tracker.create_goal(description="Goal 1", priority=GoalPriority.HIGH)
        goal2 = tracker.create_goal(description="Goal 2", priority=GoalPriority.HIGH)
        goal3 = tracker.create_goal(description="Goal 3", priority=GoalPriority.LOW)

        high_priority = tracker.get_goals_by_priority(GoalPriority.HIGH)
        low_priority = tracker.get_goals_by_priority(GoalPriority.LOW)

        self.assertEqual(len(high_priority), 2)
        self.assertEqual(len(low_priority), 1)

    def test_generate_traceability_report(self):
        """GoalTracker.generate_traceability_report should generate report."""
        tracker = GoalTracker()

        goal = tracker.create_goal(description="Test goal")
        plan = ExecutionPlan()
        task = plan.add_task("Test task")

        tracker.map_task_to_goal(task, goal.goal_id, change_type="modify")
        tracker.update_goal_status(goal.goal_id, GoalStatus.COMPLETED)

        report = tracker.generate_traceability_report(goal.goal_id)

        self.assertIn("goal", report)
        self.assertIn("changes", report)
        self.assertIn("progress", report)
        self.assertEqual(report["goal"]["goal_id"], goal.goal_id)
        self.assertEqual(len(report["changes"]), 1)
        self.assertEqual(report["progress"], 1.0)

    def test_generate_traceability_report_nonexistent(self):
        """GoalTracker.generate_traceability_report should return error for nonexistent goal."""
        tracker = GoalTracker()

        report = tracker.generate_traceability_report("goal_999")

        self.assertIn("error", report)

    def test_get_summary(self):
        """GoalTracker.get_summary should return summary statistics."""
        tracker = GoalTracker()

        goal1 = tracker.create_goal(description="Goal 1")
        goal2 = tracker.create_goal(description="Goal 2")
        goal3 = tracker.create_goal(description="Goal 3")

        tracker.update_goal_status(goal1.goal_id, GoalStatus.COMPLETED)
        tracker.update_goal_status(goal2.goal_id, GoalStatus.IN_PROGRESS)

        plan = ExecutionPlan()
        task = plan.add_task("Task")
        tracker.map_task_to_goal(task, goal1.goal_id)

        summary = tracker.get_summary()

        self.assertEqual(summary["total_goals"], 3)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["in_progress"], 1)
        self.assertEqual(summary["not_started"], 1)
        self.assertEqual(summary["total_changes"], 1)
        self.assertAlmostEqual(summary["completion_rate"], 1/3, places=5)

    def test_get_summary_empty(self):
        """GoalTracker.get_summary should return zeros for empty tracker."""
        tracker = GoalTracker()

        summary = tracker.get_summary()

        self.assertEqual(summary["total_goals"], 0)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["in_progress"], 0)
        self.assertEqual(summary["not_started"], 0)
        self.assertEqual(summary["total_changes"], 0)
        self.assertEqual(summary["completion_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()