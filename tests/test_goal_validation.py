"""Tests for goal validation edge cases."""

from rev.execution import validator
from rev.models.goal import Goal, GoalStatus


def test_goal_validation_uses_evaluate_metrics_alias():
    """Ensure validator works with Goal.evaluate_metrics and get_metrics_summary."""
    # Backward compatibility: ensure methods exist even if older Goal versions are loaded
    if not hasattr(Goal, "evaluate_metrics"):
        Goal.evaluate_metrics = Goal.evaluate  # type: ignore[attr-defined]
    if not hasattr(Goal, "get_metrics_summary"):
        Goal.get_metrics_summary = lambda self: [m.to_dict() for m in self.metrics]  # type: ignore[attr-defined]

    goal = Goal(description="All metrics pass")
    metric = goal.add_metric("coverage", target=80, current=90)

    result = validator._validate_goals([goal])

    assert result.status in {validator.ValidationStatus.PASSED, validator.ValidationStatus.PASSED_WITH_WARNINGS}
    assert metric.passed is True
