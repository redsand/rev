#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plan Diffing Module.

Provides functionality to compare execution plans and detect changes/regressions.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from collections import Counter

from rev.models.task import ExecutionPlan, Task, TaskStatus


class ChangeType(Enum):
    """Types of changes in a plan."""
    ADDED = "added"      # New task added
    REMOVED = "removed"  # Task removed
    MODIFIED = "modified"  # Task description or action changed
    STATUS_CHANGED = "status_changed"  # Task status changed (different iterations)
    DEPENDENCY_CHANGED = "dependency_changed"  # Task dependencies changed
    RISK_CHANGED = "risk_changed"  # Task risk level changed
    PRIORITY_CHANGED = "priority_changed"  # Task priority changed


@dataclass
class TaskChange:
    """Represents a change to a task between plans.

    Attributes:
        task_id: ID of the task that changed
        change_type: The type of change that occurred
        old_task: The task from the old plan (None for added tasks)
        new_task: The task from the new plan (None for removed tasks)
        field_name: The field that changed (for MODIFIED/STATUS_CHANGED/etc.)
        old_value: The old value of the changed field
        new_value: The new value of the changed field
        metadata: Additional information about the change
    """

    task_id: int
    change_type: ChangeType
    old_task: Optional[Task] = None
    new_task: Optional[Task] = None
    field_name: str = ""
    old_value: Any = None
    new_value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanDiff:
    """Represents the difference between two execution plans.

    Attributes:
        old_plan: The original plan
        new_plan: The new plan
        added_tasks: List of tasks that were added
        removed_tasks: List of tasks that were removed
        modified_tasks: List of tasks that were modified
        all_changes: List of all TaskChange objects
        summary: Summary statistics about the diff
    """

    old_plan: Optional[ExecutionPlan] = None
    new_plan: Optional[ExecutionPlan] = None
    added_tasks: List[Task] = field(default_factory=list)
    removed_tasks: List[Task] = field(default_factory=list)
    modified_tasks: List[Task] = field(default_factory=list)
    all_changes: List[TaskChange] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        """Whether there are any changes between the plans."""
        return (
            len(self.added_tasks) > 0
            or len(self.removed_tasks) > 0
            or len(self.modified_tasks) > 0
        )

    @property
    def added_count(self) -> int:
        """Number of tasks added."""
        return len(self.added_tasks)

    @property
    def removed_count(self) -> int:
        """Number of tasks removed."""
        return len(self.removed_tasks)

    @property
    def modified_count(self) -> int:
        """Number of tasks modified."""
        return len(self.modified_tasks)


def diff_plans(old_plan: Optional[ExecutionPlan], new_plan: Optional[ExecutionPlan]) -> PlanDiff:
    """Compare two execution plans and detect differences.

    Note: This implementation matches tasks by position rather than task_id or description.
    Since ExecutionPlan creates new plans with sequential task_ids starting at 0,
    task_ids from different plans don't represent the same logical task.

    Args:
        old_plan: The original plan (before changes)
        new_plan: The new plan (after changes)

    Returns:
        PlanDiff containing all detected changes
    """
    diff = PlanDiff(old_plan=old_plan, new_plan=new_plan)

    if not old_plan or not new_plan:
        return diff

    # Match tasks by position (not by task_id or description)
    # This compares the i-th task in the old plan with the i-th task in the new plan
    max_len = max(len(old_plan.tasks), len(new_plan.tasks))

    for i in range(max_len):
        old_task = old_plan.tasks[i] if i < len(old_plan.tasks) else None
        new_task = new_plan.tasks[i] if i < len(new_plan.tasks) else None

        if old_task is None and new_task is not None:
            # Task added at this position
            diff.added_tasks.append(new_task)
            diff.all_changes.append(TaskChange(
                task_id=new_task.task_id,
                change_type=ChangeType.ADDED,
                new_task=new_task,
                metadata={"description": new_task.description, "action_type": new_task.action_type}
            ))

        elif old_task is not None and new_task is None:
            # Task removed at this position
            diff.removed_tasks.append(old_task)
            diff.all_changes.append(TaskChange(
                task_id=old_task.task_id,
                change_type=ChangeType.REMOVED,
                old_task=old_task,
                metadata={"description": old_task.description, "action_type": old_task.action_type}
            ))

        elif old_task is not None and new_task is not None:
            # Both tasks exist at this position - check for changes
            if _tasks_different(old_task, new_task):
                diff.modified_tasks.append(new_task)

                # Track what changed
                if old_task.description != new_task.description:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.MODIFIED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="description",
                        old_value=old_task.description,
                        new_value=new_task.description,
                    ))

                if old_task.action_type != new_task.action_type:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.MODIFIED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="action_type",
                        old_value=old_task.action_type,
                        new_value=new_task.action_type,
                    ))

                if old_task.status != new_task.status:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.STATUS_CHANGED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="status",
                        old_value=old_task.status.value,
                        new_value=new_task.status.value,
                    ))

                if old_task.dependencies != new_task.dependencies:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.DEPENDENCY_CHANGED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="dependencies",
                        old_value=old_task.dependencies,
                        new_value=new_task.dependencies,
                    ))

                if old_task.risk_level != new_task.risk_level:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.RISK_CHANGED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="risk_level",
                        old_value=old_task.risk_level.value,
                        new_value=new_task.risk_level.value,
                    ))

                if old_task.priority != new_task.priority:
                    diff.all_changes.append(TaskChange(
                        task_id=new_task.task_id,
                        change_type=ChangeType.PRIORITY_CHANGED,
                        old_task=old_task,
                        new_task=new_task,
                        field_name="priority",
                        old_value=old_task.priority,
                        new_value=new_task.priority,
                    ))

    # Build summary
    diff.summary = {
        "total_changes": len(diff.all_changes),
        "added": diff.added_count,
        "removed": diff.removed_count,
        "modified": diff.modified_count,
        "changes_by_type": Counter(c.change_type.value for c in diff.all_changes),
    }

    return diff


def _tasks_different(old_task: Task, new_task: Task) -> bool:
    """Check if two tasks are meaningfully different.

    Args:
        old_task: The old task
        new_task: The new task

    Returns:
        True if tasks are different, False otherwise
    """
    # Quick comparison of key fields
    if (
        old_task.description != new_task.description
        or old_task.action_type != new_task.action_type
        or old_task.status != new_task.status
        or old_task.dependencies != new_task.dependencies
        or old_task.risk_level != new_task.risk_level
        or old_task.priority != new_task.priority
    ):
        return True

    # Deep comparison of result and error
    if old_task.result != new_task.result:
        return True

    if old_task.error != new_task.error:
        return True

    return False


def detect_regression(diff: PlanDiff) -> List[str]:
    """Detect potential regressions in a plan diff.

    A regression is when the new plan is worse than the old plan in some way,
    such as removing tests, increasing risk, or reducing test coverage.

    Args:
        diff: The plan diff to analyze

    Returns:
        List of regression descriptions
    """
    regressions = []

    # Check if tests were removed
    test_tasks_removed = [
        t for t in diff.removed_tasks
        if _is_test_task(t)
    ]
    if test_tasks_removed:
        regressions.append(
            f"Regression: {len(test_tasks_removed)} test task(s) removed: "
            f"{', '.join(t.description for t in test_tasks_removed[:3])}"
        )

    # Check if risk increased significantly
    old_high_risk_count = _count_tasks_by_risk_level(diff.old_plan, "high") if diff.old_plan else 0
    old_critical_risk_count = _count_tasks_by_risk_level(diff.old_plan, "critical") if diff.old_plan else 0
    new_high_risk_count = _count_tasks_by_risk_level(diff.new_plan, "high") if diff.new_plan else 0
    new_critical_risk_count = _count_tasks_by_risk_level(diff.new_plan, "critical") if diff.new_plan else 0

    old_high_critical = old_high_risk_count + old_critical_risk_count
    new_high_critical = new_high_risk_count + new_critical_risk_count

    if new_high_critical > old_high_critical:
        regressions.append(
            f"Regression: High/critical risk tasks increased from {old_high_critical} to {new_high_critical}"
        )

    # Check if total task count decreased significantly
    old_task_count = len(diff.old_plan.tasks) if diff.old_plan else 0
    new_task_count = len(diff.new_plan.tasks) if diff.new_plan else 0

    if new_task_count < old_task_count * 0.8:  # More than 20% reduction
        regressions.append(
            f"Regression: Task count decreased from {old_task_count} to {new_task_count} (>20% reduction)"
        )

    return regressions


def _is_test_task(task: Task) -> bool:
    """Check if a task is a test task.

    Args:
        task: The task to check

    Returns:
        True if the task is a test task
    """
    from rev.models.task import _EXPLICIT_VERB_PATTERN, _TEST_KEYWORD_PATTERN

    desc_lower = task.description.lower()
    action_lower = (task.action_type or "").lower()

    # Check for test keywords in description
    if _TEST_KEYWORD_PATTERN.search(desc_lower):
        return True

    # Check for test action type
    if action_lower == "test":
        return True

    # Check for test verbs
    if _EXPLICIT_VERB_PATTERN.search(desc_lower):
        return True

    return False


def _count_tasks_by_risk_level(plan: ExecutionPlan, risk_level: str) -> int:
    """Count tasks with a specific risk level.

    Args:
        plan: The execution plan
        risk_level: The risk level to count ("low", "medium", "high", "critical")

    Returns:
        Count of tasks with the specified risk level
    """
    if not plan:
        return 0

    from rev.models.task import RiskLevel

    risk_map = {
        "low": RiskLevel.LOW,
        "medium": RiskLevel.MEDIUM,
        "high": RiskLevel.HIGH,
        "critical": RiskLevel.CRITICAL,
    }

    target_risk = risk_map.get(risk_level.lower())
    if target_risk is None:
        return 0

    return sum(1 for task in plan.tasks if task.risk_level == target_risk)


def format_diff(diff: PlanDiff, verbose: bool = False) -> str:
    """Format a plan diff for human readability.

    Args:
        diff: The plan diff to format
        verbose: Whether to include detailed information

    Returns:
        Formatted string representation
    """
    if not diff.has_changes:
        return "No changes detected."

    lines = [f"Plan Diff Summary:", f"  Added: {diff.added_count}", f"  Removed: {diff.removed_count}", f"  Modified: {diff.modified_count}"]

    if verbose:
        lines.append("\nChanges by type:")
        for change_type, count in diff.summary.get("changes_by_type", {}).items():
            lines.append(f"  {change_type}: {count}")

        if diff.added_tasks:
            lines.append("\nAdded tasks:")
            for task in diff.added_tasks[:3]:  # Show first 3
                lines.append(f"  [{task.task_id}] {task.description}")
            if len(diff.added_tasks) > 3:
                lines.append(f"  ... and {len(diff.added_tasks) - 3} more")

        if diff.removed_tasks:
            lines.append("\nRemoved tasks:")
            for task in diff.removed_tasks[:3]:  # Show first 3
                lines.append(f"  [{task.task_id}] {task.description}")
            if len(diff.removed_tasks) > 3:
                lines.append(f"  ... and {len(diff.removed_tasks) - 3} more")

        if diff.modified_tasks:
            lines.append("\nModified tasks:")
            for task in diff.modified_tasks[:3]:  # Show first 3
                lines.append(f"  [{task.task_id}] {task.description}")
            if len(diff.modified_tasks) > 3:
                lines.append(f"  ... and {len(diff.modified_tasks) - 3} more")

        # Show detailed field changes for modified tasks
        field_changes = [c for c in diff.all_changes if c.change_type != ChangeType.ADDED and c.change_type != ChangeType.REMOVED]
        if field_changes:
            lines.append("\nField changes:")
            for change in field_changes[:5]:  # Show first 5 field changes
                lines.append(f"  {change.field_name}: {change.old_value} -> {change.new_value}")
            if len(field_changes) > 5:
                lines.append(f"  ... and {len(field_changes) - 5} more")

    return "\n".join(lines)