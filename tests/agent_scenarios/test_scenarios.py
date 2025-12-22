"""Test runner for agent failure scenarios.

This module runs all defined agent scenarios and verifies that historical
failure modes have been addressed.
"""

import pytest

from tests.agent_scenarios.framework import (
    run_scenario,
    verify_scenario,
    save_scenario_result,
)
from tests.agent_scenarios.scenarios import ALL_SCENARIOS


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_agent_scenario(scenario, scenario_workspace, scenario_results_dir):
    """Test an agent scenario to ensure failure mode is prevented.

    Args:
        scenario: The scenario to test
        scenario_workspace: Fixture that creates workspace
        scenario_results_dir: Directory for saving results
    """
    # Setup workspace
    workspace = scenario_workspace(scenario)

    # Run the scenario
    result = run_scenario(scenario, workspace)

    # Save result for analysis
    save_scenario_result(result, scenario_results_dir)

    # Verify the result
    assert verify_scenario(result, scenario), (
        f"Scenario '{scenario.name}' failed verification:\n"
        f"  Artifacts missing: {result.artifacts_missing}\n"
        f"  DoD checks failed: {result.dod_checks_failed}\n"
        f"  Failure mode avoided: {result.failure_mode_avoided}\n"
        f"  Error: {result.error_message}"
    )


class TestScenarioFramework:
    """Tests for the scenario framework itself."""

    def test_all_scenarios_have_names(self):
        """Verify all scenarios have unique names."""
        names = [s.name for s in ALL_SCENARIOS]
        assert len(names) == len(set(names)), "Scenario names must be unique"

    def test_all_scenarios_have_descriptions(self):
        """Verify all scenarios have descriptions."""
        for scenario in ALL_SCENARIOS:
            assert scenario.description, f"Scenario {scenario.name} missing description"

    def test_all_scenarios_have_user_requests(self):
        """Verify all scenarios have user requests."""
        for scenario in ALL_SCENARIOS:
            assert scenario.user_request, f"Scenario {scenario.name} missing user request"

    def test_all_scenarios_have_failure_modes(self):
        """Verify all scenarios define failure modes."""
        for scenario in ALL_SCENARIOS:
            assert len(scenario.known_failure_modes) > 0, (
                f"Scenario {scenario.name} must define at least one failure mode"
            )

    def test_all_scenarios_have_initial_state(self):
        """Verify all scenarios have initial state."""
        for scenario in ALL_SCENARIOS:
            assert scenario.initial_state, f"Scenario {scenario.name} missing initial state"

    def test_scenario_timeout_reasonable(self):
        """Verify all scenarios have reasonable timeouts."""
        for scenario in ALL_SCENARIOS:
            assert 0 < scenario.timeout_seconds <= 600, (
                f"Scenario {scenario.name} timeout should be between 1-600 seconds"
            )


class TestScenarioCategories:
    """Tests for scenario categorization and coverage."""

    def test_scenarios_cover_false_completion(self):
        """Verify we test for false completion scenarios."""
        false_completion_scenarios = [
            s for s in ALL_SCENARIOS
            if "false_completion" in s.metadata.get("tags", [])
            or "reports done" in s.name.lower()
        ]
        assert len(false_completion_scenarios) > 0, "Need scenarios for false completion"

    def test_scenarios_cover_test_failures(self):
        """Verify we test for test failure handling."""
        test_failure_scenarios = [
            s for s in ALL_SCENARIOS
            if "test_failure" in s.metadata.get("tags", [])
            or "test" in " ".join(s.known_failure_modes).lower()
        ]
        assert len(test_failure_scenarios) > 0, "Need scenarios for test failures"

    def test_scenarios_cover_partial_implementation(self):
        """Verify we test for partial implementations."""
        partial_impl_scenarios = [
            s for s in ALL_SCENARIOS
            if "partial" in s.name.lower() or "partial" in " ".join(s.known_failure_modes).lower()
        ]
        assert len(partial_impl_scenarios) > 0, "Need scenarios for partial implementations"

    def test_scenarios_have_difficulty_ratings(self):
        """Verify scenarios have difficulty ratings."""
        difficulties = {"easy", "medium", "hard"}
        for scenario in ALL_SCENARIOS:
            difficulty = scenario.metadata.get("difficulty")
            assert difficulty in difficulties, (
                f"Scenario {scenario.name} must have difficulty: easy, medium, or hard"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
