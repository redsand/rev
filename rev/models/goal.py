#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Goal and Metrics models for goal-oriented execution.

This module implements the Goal Setting & Monitoring pattern from Agentic Design
Patterns, providing explicit objectives, success criteria, and progress tracking.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class GoalStatus(Enum):
    """Status of a goal."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ACHIEVED = "achieved"
    FAILED = "failed"
    PARTIALLY_ACHIEVED = "partially_achieved"


@dataclass
class GoalMetric:
    """A measurable metric for goal achievement.

    Examples:
        - name="tests_pass", target=True, current=True, passed=True
        - name="coverage_delta", target=0, current=5, passed=True
        - name="security_findings", target="no high severity", current="2 high", passed=False
    """
    name: str
    target: Any
    current: Any = None
    passed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self) -> bool:
        """Evaluate if the metric has passed based on target vs current.

        Returns:
            True if metric passes, False otherwise
        """
        if self.current is None:
            return False

        # Boolean targets
        if isinstance(self.target, bool):
            self.passed = bool(self.current) == self.target
            return self.passed

        # Numeric targets (threshold-based)
        if isinstance(self.target, (int, float)):
            try:
                current_val = float(self.current)
                target_val = float(self.target)
                self.passed = current_val >= target_val
                return self.passed
            except (ValueError, TypeError):
                self.passed = False
                return False

        # String targets (exact match or substring)
        if isinstance(self.target, str):
            self.passed = str(self.target).lower() in str(self.current).lower()
            return self.passed

        # Default: exact equality
        self.passed = self.current == self.target
        return self.passed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "target": self.target,
            "current": self.current,
            "passed": self.passed,
            "details": self.details
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GoalMetric':
        """Create from dictionary."""
        return cls(
            name=data["name"],
            target=data["target"],
            current=data.get("current"),
            passed=data.get("passed", False),
            details=data.get("details", {})
        )


@dataclass
class Goal:
    """A goal with measurable metrics and status tracking.

    Goals make execution plans explicit and testable, aligning with the
    Goal Setting & Monitoring pattern.
    """
    description: str
    metrics: List[GoalMetric] = field(default_factory=list)
    status: GoalStatus = GoalStatus.PENDING
    priority: int = 0  # Higher = more important
    notes: List[str] = field(default_factory=list)

    def add_metric(self, name: str, target: Any, current: Any = None) -> GoalMetric:
        """Add a metric to this goal."""
        metric = GoalMetric(name=name, target=target, current=current)
        self.metrics.append(metric)
        return metric

    def evaluate(self) -> GoalStatus:
        """Evaluate all metrics and determine goal status.

        Returns:
            Updated goal status
        """
        if not self.metrics:
            # No metrics means we can't evaluate
            return self.status

        passed_count = sum(1 for m in self.metrics if m.evaluate())
        total_count = len(self.metrics)

        if passed_count == total_count:
            self.status = GoalStatus.ACHIEVED
        elif passed_count == 0:
            self.status = GoalStatus.FAILED
        else:
            self.status = GoalStatus.PARTIALLY_ACHIEVED

        return self.status

    def evaluate_metrics(self) -> bool:
        """Alias used by validator; returns True only when all metrics pass."""
        status = self.evaluate()
        return status == GoalStatus.ACHIEVED

    def get_metrics_summary(self) -> List[Dict[str, Any]]:
        """Return a summary of metrics for reporting."""
        return [m.to_dict() for m in self.metrics]

    def get_summary(self) -> str:
        """Get a human-readable summary of goal status."""
        passed = sum(1 for m in self.metrics if m.passed)
        total = len(self.metrics)

        status_emoji = {
            GoalStatus.ACHIEVED: "✅",
            GoalStatus.FAILED: "❌",
            GoalStatus.PARTIALLY_ACHIEVED: "",
            GoalStatus.IN_PROGRESS: "🔄",
            GoalStatus.PENDING: "⏳"
        }.get(self.status, "❓")

        return f"{status_emoji} {self.description} ({passed}/{total} metrics passed)"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "description": self.description,
            "metrics": [m.to_dict() for m in self.metrics],
            "status": self.status.value,
            "priority": self.priority,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Goal':
        """Create from dictionary."""
        goal = cls(
            description=data["description"],
            metrics=[GoalMetric.from_dict(m) for m in data.get("metrics", [])],
            status=GoalStatus(data.get("status", "pending")),
            priority=data.get("priority", 0),
            notes=data.get("notes", [])
        )
        return goal


def derive_goals_from_request(user_request: str, task_types: List[str]) -> List[Goal]:
    """Automatically derive goals from a user request and task types.

    This is a helper function that creates sensible default goals for common
    coding workflows.

    Args:
        user_request: The user's task description
        task_types: List of action types from the execution plan

    Returns:
        List of derived goals
    """
    goals = []
    request_lower = user_request.lower()

    # Default goal: successful execution
    completion_goal = Goal(description="Complete all tasks successfully")
    completion_goal.add_metric("all_tasks_completed", True)
    goals.append(completion_goal)

    # If any code changes, add test goal
    has_code_changes = any(t in task_types for t in ["add", "edit"])
    if has_code_changes:
        test_goal = Goal(description="Ensure tests pass after changes")
        test_goal.add_metric("tests_pass", True)
        test_goal.add_metric("coverage_maintained", 0)  # Delta >= 0
        goals.append(test_goal)

    # Security-related goals
    if any(word in request_lower for word in ["security", "auth", "password", "token"]):
        security_goal = Goal(description="Maintain security standards")
        security_goal.add_metric("no_high_severity_findings", True)
        security_goal.add_metric("no_exposed_secrets", True)
        goals.append(security_goal)

    # If database/migration mentioned
    if any(word in request_lower for word in ["database", "migration", "schema"]):
        db_goal = Goal(description="Database changes are safe and reversible")
        db_goal.add_metric("migration_reversible", True)
        db_goal.add_metric("data_integrity_maintained", True)
        goals.append(db_goal)

    # Performance-related
    if any(word in request_lower for word in ["performance", "optimize", "speed", "slow"]):
        perf_goal = Goal(description="Improve performance")
        perf_goal.add_metric("performance_improved", True)
        perf_goal.notes.append("Measure baseline before changes")
        goals.append(perf_goal)

    return goals
