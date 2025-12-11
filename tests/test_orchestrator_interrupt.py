"""Interrupt handling for orchestrated execution."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import rev.execution.orchestrator as orchestrator
from rev.models.task import ExecutionPlan
from rev.execution.validator import ValidationStatus


def test_orchestrator_interrupt_shows_resume(monkeypatch, capsys):
    """Keyboard interrupts in orchestrated mode should surface resume info."""

    calls = {"on_interrupt": False, "created": False}

    class DummyStateManager:
        def __init__(self, plan):
            calls["created"] = isinstance(plan, ExecutionPlan)

        def on_interrupt(self, token_usage=None):  # pragma: no cover - trivial wiring
            calls["on_interrupt"] = True
            print("rev --resume dummy-checkpoint")

    def raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    plan = ExecutionPlan()
    plan.add_task("demo", action_type="general")

    monkeypatch.setattr(orchestrator, "StateManager", DummyStateManager)
    monkeypatch.setattr(orchestrator, "planning_mode", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(orchestrator, "execution_mode", raise_interrupt)
    monkeypatch.setattr(
        orchestrator,
        "validate_execution",
        lambda *_args, **_kwargs: MagicMock(overall_status=ValidationStatus.PASSED, results=[], auto_fixed=False),
    )

    config = orchestrator.OrchestratorConfig(
        enable_learning=False,
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        parallel_workers=1,
        max_retries=0,
    )

    runner = orchestrator.Orchestrator(Path.cwd(), config)

    with pytest.raises(KeyboardInterrupt):
        runner.execute("demo task")

    output = capsys.readouterr().out
    assert calls["created"] is True
    assert calls["on_interrupt"] is True
    assert "rev --resume" in output
