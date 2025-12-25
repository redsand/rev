"""Tests for resume-plan behavior in sub-agent execution."""

from pathlib import Path
from unittest.mock import patch

from rev import config
from rev.core.context import RevContext
from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.execution.state_manager import StateManager


def test_resume_plan_skips_checkpoint_load(monkeypatch):
    """Resuming without resume_plan should not load or search checkpoints."""
    monkeypatch.setattr(config, "UCCT_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "TDD_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "PREFLIGHT_ENABLED", False, raising=False)
    monkeypatch.setattr(RevContext, "load_history", lambda self: ["[COMPLETED] tree_view"])
    monkeypatch.setattr(
        "rev.execution.orchestrator.get_token_usage",
        lambda: {"total": 0},
    )

    orchestrator = Orchestrator(
        Path.cwd(),
        OrchestratorConfig(
            enable_research=False,
            enable_review=False,
            enable_validation=False,
        ),
    )
    orchestrator.context = RevContext(
        user_request="noop",
        resume=True,
        resume_plan=False,
    )

    with patch.object(
        StateManager,
        "find_latest_checkpoint",
        side_effect=AssertionError("checkpoint lookup should be skipped"),
    ) as find_latest, patch.object(
        StateManager,
        "load_from_checkpoint",
        side_effect=AssertionError("checkpoint load should be skipped"),
    ), patch.object(
        Orchestrator,
        "_determine_next_action",
        return_value=None,
    ):
        success = orchestrator._continuous_sub_agent_execution("noop", coding_mode=False)

    assert success is True
    assert orchestrator.context.plan is not None
    assert orchestrator.context.plan.tasks == []
    find_latest.assert_not_called()
