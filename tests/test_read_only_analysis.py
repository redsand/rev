"""Read-only enforcement tests for analyze requests."""

from pathlib import Path

from rev.core.context import RevContext
from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import Task


def test_read_only_coerces_write_actions():
    orchestrator = Orchestrator(Path.cwd(), OrchestratorConfig())
    orchestrator.context = RevContext(user_request="Analyze", read_only=True)

    task = Task(description="Edit src/app.py to add logging", action_type="edit")
    updated = orchestrator._apply_read_only_constraints(task)

    assert updated.action_type == "review"
    assert updated.description.lower().startswith("read-only analysis")


def test_read_only_allows_analyze_actions():
    orchestrator = Orchestrator(Path.cwd(), OrchestratorConfig())
    orchestrator.context = RevContext(user_request="Analyze", read_only=True)

    task = Task(description="Analyze src/app.py for issues", action_type="analyze")
    updated = orchestrator._apply_read_only_constraints(task)

    assert updated.action_type == "analyze"
    assert updated.description == "Analyze src/app.py for issues"
