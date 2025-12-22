"""Scenario definitions for agent failure mode testing."""

from tests.agent_scenarios.scenarios.scenario_01_reports_done_but_no_changes import scenario as scenario_01
from tests.agent_scenarios.scenarios.scenario_02_test_failure_ignored import scenario as scenario_02
from tests.agent_scenarios.scenarios.scenario_03_empty_tool_pretend_success import scenario as scenario_03
from tests.agent_scenarios.scenarios.scenario_04_partial_implementation import scenario as scenario_04
from tests.agent_scenarios.scenarios.scenario_05_infinite_retry_loop import scenario as scenario_05


ALL_SCENARIOS = [
    scenario_01,
    scenario_02,
    scenario_03,
    scenario_04,
    scenario_05,
]


__all__ = ["ALL_SCENARIOS"]
