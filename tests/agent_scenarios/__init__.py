"""Agent scenario testing framework for REV.

This package contains a testing harness for capturing and verifying
historical agent failure modes to ensure they don't regress.
"""

from tests.agent_scenarios.framework import (
    AgentScenario,
    ScenarioResult,
    setup_scenario,
    run_scenario,
    verify_scenario,
    cleanup_scenario,
)

__all__ = [
    "AgentScenario",
    "ScenarioResult",
    "setup_scenario",
    "run_scenario",
    "verify_scenario",
    "cleanup_scenario",
]
