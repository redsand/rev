"""Pytest fixtures for agent scenario tests."""

import pytest
from pathlib import Path

from tests.agent_scenarios.framework import (
    AgentScenario,
    setup_scenario,
    cleanup_scenario,
)


@pytest.fixture
def scenario_workspace(request):
    """Create a temporary workspace for scenario testing.

    This fixture automatically cleans up after the test.
    """
    workspace = None

    def _create_workspace(scenario: AgentScenario) -> Path:
        nonlocal workspace
        workspace = setup_scenario(scenario)
        return workspace

    yield _create_workspace

    # Cleanup
    if workspace is not None:
        cleanup_scenario(workspace)


@pytest.fixture
def scenario_results_dir(tmp_path):
    """Create a directory for storing scenario results."""
    results_dir = tmp_path / "scenario_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir
