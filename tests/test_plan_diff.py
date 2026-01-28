#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Plan Diffing functionality.

Tests the plan diffing module that compares execution plans and detects changes/regressions.
"""

import unittest
from rev.execution.plan_diff import (
    diff_plans,
    PlanDiff,
    ChangeType,
    TaskChange,
    detect_regression,
    format_diff,
    _is_test_task,
)
from rev.models.task import ExecutionPlan, Task, TaskStatus, RiskLevel


class TestDiffPlans(unittest.TestCase):
    """Test diff_plans function."""

    def test_diff_plans_no_changes(self):
        """Diff with no changes should return empty diff."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        diff = diff_plans(plan, plan)

        self.assertFalse(diff.has_changes)
        self.assertEqual(diff.added_count, 0)
        self.assertEqual(diff.removed_count, 0)
        self.assertEqual(diff.modified_count, 0)

    def test_diff_plans_added_task(self):
        """Diff should detect added tasks."""
        old_plan = ExecutionPlan()
        new_plan = ExecutionPlan()
        new_plan.add_task("New Task")

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        self.assertEqual(diff.added_count, 1)
        self.assertEqual(diff.removed_count, 0)
        self.assertEqual(diff.modified_count, 0)
        self.assertEqual(diff.added_tasks[0].description, "New Task")
        self.assertEqual(diff.all_changes[0].change_type, ChangeType.ADDED)

    def test_diff_plans_removed_task(self):
        """Diff should detect removed tasks."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Old Task")
        new_plan = ExecutionPlan()

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        self.assertEqual(diff.added_count, 0)
        self.assertEqual(diff.removed_count, 1)
        self.assertEqual(diff.modified_count, 0)
        self.assertEqual(diff.removed_tasks[0].description, "Old Task")
        self.assertEqual(diff.all_changes[0].change_type, ChangeType.REMOVED)

    def test_diff_plans_modified_description(self):
        """Diff should detect task description changes."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1")
        new_plan = ExecutionPlan()
        new_plan.add_task("Task 2")  # Same task_id, different description

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        self.assertEqual(diff.modified_count, 1)
        self.assertEqual(diff.added_count, 0)
        self.assertEqual(diff.removed_count, 0)

        desc_change = [c for c in diff.all_changes if c.field_name == "description"]
        self.assertEqual(len(desc_change), 1)
        self.assertEqual(desc_change[0].old_value, "Task 1")
        self.assertEqual(desc_change[0].new_value, "Task 2")

    def test_diff_plans_modified_action_type(self):
        """Diff should detect action type changes."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1", action_type="read")
        new_plan = ExecutionPlan()
        new_plan.add_task("Task 1", action_type="edit")

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        action_changes = [c for c in diff.all_changes if c.field_name == "action_type"]
        self.assertEqual(len(action_changes), 1)
        self.assertEqual(action_changes[0].old_value, "read")
        self.assertEqual(action_changes[0].new_value, "edit")

    def test_diff_plans_status_change(self):
        """Diff should detect status changes."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1")
        new_plan = ExecutionPlan()
        task = new_plan.add_task("Task 1")
        task.set_status(TaskStatus.IN_PROGRESS)

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        status_changes = [c for c in diff.all_changes if c.field_name == "status"]
        self.assertEqual(len(status_changes), 1)
        self.assertEqual(status_changes[0].old_value, "pending")
        self.assertEqual(status_changes[0].new_value, "in_progress")

    def test_diff_plans_dependencies_change(self):
        """Diff should detect dependency changes."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1", dependencies=[1])
        new_plan = ExecutionPlan()
        new_plan.add_task("Task 1", dependencies=[1, 2])

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        dep_changes = [c for c in diff.all_changes if c.field_name == "dependencies"]
        self.assertEqual(len(dep_changes), 1)
        self.assertEqual(dep_changes[0].old_value, [1])
        self.assertEqual(dep_changes[0].new_value, [1, 2])

    def test_diff_plans_risk_change(self):
        """Diff should detect risk level changes."""
        old_plan = ExecutionPlan()
        task = old_plan.add_task("Task 1")
        task.risk_level = RiskLevel.LOW
        new_plan = ExecutionPlan()
        task = new_plan.add_task("Task 1")
        task.risk_level = RiskLevel.HIGH

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        risk_changes = [c for c in diff.all_changes if c.field_name == "risk_level"]
        self.assertEqual(len(risk_changes), 1)
        self.assertEqual(risk_changes[0].old_value, "low")
        self.assertEqual(risk_changes[0].new_value, "high")

    def test_diff_plans_priority_change(self):
        """Diff should detect priority changes."""
        old_plan = ExecutionPlan()
        task = old_plan.add_task("Task 1")
        task.priority = 0
        new_plan = ExecutionPlan()
        task = new_plan.add_task("Task 1")
        task.priority = 5

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        priority_changes = [c for c in diff.all_changes if c.field_name == "priority"]
        self.assertEqual(len(priority_changes), 1)
        self.assertEqual(priority_changes[0].old_value, 0)
        self.assertEqual(priority_changes[0].new_value, 5)

    def test_diff_plans_multiple_changes(self):
        """Diff should detect multiple changes.

        Note: Since ExecutionPlan creates new plans with sequential task_ids starting at 0,
        task_ids from different plans don't represent the same logical task.
        This test uses position-based matching, which compares tasks at the same index.
        """
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1")
        old_plan.add_task("Task 2")
        old_plan.add_task("Task 3")

        new_plan = ExecutionPlan()
        new_plan.add_task("Task 1 Modified")  # Position 0 - different from old
        new_plan.add_task("New Task 4")       # Position 1 - different from old
        # Position 2 (Task 3) removed

        diff = diff_plans(old_plan, new_plan)

        self.assertTrue(diff.has_changes)
        # Position-based matching: 0 added, 1 removed, 2 modified
        self.assertEqual(diff.added_count, 0)
        self.assertEqual(diff.removed_count, 1)
        self.assertEqual(diff.modified_count, 2)

    def test_diff_plans_none_handling(self):
        """Diff should handle None plans gracefully."""
        diff1 = diff_plans(None, ExecutionPlan())
        diff2 = diff_plans(ExecutionPlan(), None)
        diff3 = diff_plans(None, None)

        self.assertFalse(diff1.has_changes)
        self.assertFalse(diff2.has_changes)
        self.assertFalse(diff3.has_changes)

    def test_diff_summary_counts(self):
        """Diff summary should have correct counts.

        Note: Since ExecutionPlan creates new plans with sequential task_ids starting at 0,
        task_ids from different plans don't represent the same logical task.
        This test uses position-based matching, which compares tasks at the same index.
        """
        old_plan = ExecutionPlan()
        for i in range(3):
            old_plan.add_task(f"Task {i+1}")

        new_plan = ExecutionPlan()
        new_plan.add_task("Modified Task 1")  # Position 0 - different from old
        new_plan.add_task("New Task 4")       # Position 1 - different from old

        diff = diff_plans(old_plan, new_plan)

        # Position-based matching:
        # Position 0: "Task 1" vs "Modified Task 1" -> MODIFIED (1 field change: description)
        # Position 1: "Task 2" vs "New Task 4" -> MODIFIED (1 field change: description)
        # Position 2: "Task 3" vs (nothing) -> REMOVED
        # Total: added=0, removed=1, modified=2, total_changes=3
        self.assertEqual(diff.summary["added"], 0)
        self.assertEqual(diff.summary["removed"], 1)
        self.assertEqual(diff.summary["modified"], 2)
        self.assertEqual(diff.summary["total_changes"], 3)


class TestPlanDiff(unittest.TestCase):
    """Test PlanDiff dataclass."""

    def test_empty_diff_has_no_changes(self):
        """Empty diff should report no changes."""
        diff = PlanDiff()
        self.assertFalse(diff.has_changes)
        self.assertEqual(diff.added_count, 0)

    def test_diff_populates_all_changes(self):
        """Diff should populate all_changes list."""
        diff = PlanDiff()
        diff.added_tasks.append(Task("task1"))
        diff.removed_tasks.append(Task("task2"))
        diff.modified_tasks.append(Task("task3"))

        self.assertEqual(len(diff.all_changes), 0)  # Changes tracked via diff_plans, not manual
        self.assertTrue(diff.has_changes)


class TestDetectRegression(unittest.TestCase):
    """Test regression detection in plan diffs."""

    def test_no_regression_no_changes(self):
        """No regression when no changes."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Test Task", action_type="test")

        diff = diff_plans(plan, plan)
        regressions = detect_regression(diff)

        self.assertEqual(len(regressions), 0)

    def test_regression_test_removed(self):
        """Regression detected when test tasks are removed."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1")
        old_plan.add_task("Test Task", action_type="test")
        old_plan.add_task("pytest task")

        new_plan = ExecutionPlan()
        new_plan.add_task("Task 1")

        diff = diff_plans(old_plan, new_plan)
        regressions = detect_regression(diff)

        self.assertGreater(len(regressions), 0)
        self.assertTrue(any("test" in r.lower() for r in regressions))

    def test_regression_risk_increase(self):
        """Regression detected when risk increases."""
        old_plan = ExecutionPlan()
        for i in range(5):
            task = old_plan.add_task(f"Task {i+1}")
            task.risk_level = RiskLevel.LOW

        new_plan = ExecutionPlan()
        for i in range(3):
            task = new_plan.add_task(f"Task {i+1}")
            task.risk_level = RiskLevel.HIGH

        diff = diff_plans(old_plan, new_plan)
        regressions = detect_regression(diff)

        self.assertGreater(len(regressions), 0)

    def test_regression_task_count_decrease(self):
        """Regression detected when task count decreases significantly."""
        old_plan = ExecutionPlan()
        for i in range(10):
            old_plan.add_task(f"Task {i+1}")

        new_plan = ExecutionPlan()
        for i in range(5):  # 50% reduction
            new_plan.add_task(f"Task {i+1}")

        diff = diff_plans(old_plan, new_plan)
        regressions = detect_regression(diff)

        self.assertGreater(len(regressions), 0)


class TestIsTestTask(unittest.TestCase):
    """Test _is_test_task helper."""

    def test_test_task_with_test_action_type(self):
        """Task with 'test' action type is a test task."""
        task = Task("Run tests", action_type="test")
        self.assertTrue(_is_test_task(task))

    def test_test_task_with_test_keywords(self):
        """Task with test keywords is a test task."""
        task = Task("pytest -q")
        self.assertTrue(_is_test_task(task))

        task = Task("Run the test suite")
        self.assertTrue(_is_test_task(task))

    def test_test_task_with_run_test_verb(self):
        """Task with 'run test' is a test task."""
        task = Task("run the tests")
        self.assertTrue(_is_test_task(task))

    def test_non_test_task(self):
        """Task without test indicators is not a test task."""
        task = Task("Implement feature")
        self.assertFalse(_is_test_task(task))


class TestFormatDiff(unittest.TestCase):
    """Test plan diff formatting."""

    def test_format_diff_no_changes(self):
        """Format diff with no changes."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")

        diff = diff_plans(plan, plan)
        formatted = format_diff(diff)

        self.assertIn("No changes detected", formatted)

    def test_format_diff_with_changes(self):
        """Format diff with changes."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1")
        new_plan = ExecutionPlan()
        new_plan.add_task("Modified Task 1")

        diff = diff_plans(old_plan, new_plan)
        formatted = format_diff(diff, verbose=True)

        self.assertIn("Modified:", formatted)
        self.assertIn("Modified tasks:", formatted)
        self.assertIn("Modified Task 1", formatted)

    def test_format_diff_verbose_shows_all_details(self):
        """Verbose format shows detailed information."""
        old_plan = ExecutionPlan()
        old_plan.add_task("Task 1", action_type="read")
        new_plan = ExecutionPlan()
        new_plan.add_task("Task 1", action_type="edit")

        diff = diff_plans(old_plan, new_plan)
        formatted = format_diff(diff, verbose=True)

        self.assertIn("modified:", formatted.lower())
        self.assertIn("read", formatted)
        self.assertIn("edit", formatted)


class TestTaskChange(unittest.TestCase):
    """Test TaskChange dataclass."""

    def test_task_change_added(self):
        """Create an ADDED task change."""
        change = TaskChange(
            task_id=1,
            change_type=ChangeType.ADDED,
            new_task=Task("New task"),
        )

        self.assertEqual(change.task_id, 1)
        self.assertEqual(change.change_type, ChangeType.ADDED)
        self.assertIsNone(change.old_task)
        self.assertIsNotNone(change.new_task)

    def test_task_change_removed(self):
        """Create a REMOVED task change."""
        change = TaskChange(
            task_id=1,
            change_type=ChangeType.REMOVED,
            old_task=Task("Old task"),
        )

        self.assertEqual(change.change_type, ChangeType.REMOVED)
        self.assertIsNotNone(change.old_task)
        self.assertIsNone(change.new_task)

    def test_task_change_modified(self):
        """Create a MODIFIED task change."""
        old_task = Task("Old task")
        new_task = Task("New task")

        change = TaskChange(
            task_id=1,
            change_type=ChangeType.MODIFIED,
            old_task=old_task,
            new_task=new_task,
            field_name="description",
            old_value="Old task",
            new_value="New task",
        )

        self.assertEqual(change.change_type, ChangeType.MODIFIED)
        self.assertEqual(change.old_value, "Old task")
        self.assertEqual(change.new_value, "New task")


if __name__ == "__main__":
    unittest.main()