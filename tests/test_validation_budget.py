"""Validation budget/regression tests."""

import types
from unittest.mock import patch

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.execution.reviewer import PlanReview, ReviewDecision
from rev.execution.researcher import ResearchFindings
from rev.models.task import ExecutionPlan, TaskStatus
from rev.execution.validator import ValidationStatus


def _stub_plan():
    plan = ExecutionPlan()
    plan.add_task("do something", "edit")
    return plan


def test_validation_none_does_not_crash_validation_phase(monkeypatch):
    """If validate_execution returns None, orchestrator should mark validation as skipped, not crash."""

    # Stub TaskRouter.route to avoid touching real routing logic
    class FakeRoute:
        mode = "focused_feature"
        enable_learning = False
        enable_research = False
        enable_review = False
        enable_validation = True
        review_strictness = "moderate"
        enable_action_review = False
        auto_approve = True
        parallel_workers = 1
        max_retries = 0
        research_depth = "medium"
        validation_mode = "targeted"
        max_plan_tasks = None

        reasoning = "stub"

    class FakeRouter:
        def route(self, *_args, **_kwargs):
            return FakeRoute()

    monkeypatch.setattr("rev.execution.router.TaskRouter", FakeRouter)
    monkeypatch.setattr("rev.execution.orchestrator.get_available_tools", lambda: [])
    monkeypatch.setattr("rev.execution.orchestrator.Orchestrator._collect_repo_stats", lambda self: {})
    monkeypatch.setattr("rev.execution.researcher.research_codebase", lambda *a, **k: ResearchFindings())
    monkeypatch.setattr("rev.execution.planner.planning_mode", lambda *a, **k: _stub_plan())
    monkeypatch.setattr("rev.execution.orchestrator.planning_mode", lambda *a, **k: _stub_plan())
    monkeypatch.setattr(
        "rev.execution.reviewer.review_execution_plan",
        lambda *a, **k: PlanReview(decision=ReviewDecision.APPROVED),
    )

    def fake_execution_mode(plan, *args, **kwargs):
        # Mark all tasks completed
        for task in plan.tasks:
            task.status = TaskStatus.COMPLETED
        return True

    monkeypatch.setattr("rev.execution.executor.execution_mode", fake_execution_mode)
    monkeypatch.setattr("rev.execution.executor.concurrent_execution_mode", fake_execution_mode)
    monkeypatch.setattr("rev.execution.orchestrator.execution_mode", fake_execution_mode)
    monkeypatch.setattr("rev.execution.orchestrator.concurrent_execution_mode", fake_execution_mode)
    monkeypatch.setattr("rev.execution.orchestrator.validate_execution", lambda *a, **k: None)

    # Force validate_execution to return None to hit the regression path
    monkeypatch.setattr("rev.execution.validator.validate_execution", lambda *a, **k: None)

    config = OrchestratorConfig(
        enable_learning=False,
        enable_research=False,
        enable_review=False,
        enable_validation=True,
        auto_approve=True,
        parallel_workers=1,
    )

    orch = Orchestrator(project_root=types.SimpleNamespace(), config=config)
    result = orch._run_single_attempt("test task")

    assert result.validation_status == ValidationStatus.SKIPPED
    assert result.success is True
