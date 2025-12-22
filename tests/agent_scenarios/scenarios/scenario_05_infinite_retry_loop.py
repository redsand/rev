"""Scenario 05: Agent gets stuck in infinite retry loop.

Historical failure: Agent encounters an error, retries the same operation
repeatedly without changing approach, leading to timeout or excessive resource use.
"""

from tests.agent_scenarios.framework import AgentScenario


scenario = AgentScenario(
    name="infinite_retry_loop",
    description="Agent retries failed operation infinitely without changing approach",
    initial_state={
        "git_enabled": True,
        "files": {
            "src/config.py": '''import os

# This file intentionally has a syntax error on line 5
# to trigger retry behavior
def load_config()
    return {"debug": True}  # Missing colon
''',
            "tests/test_config.py": '''import pytest
from src.config import load_config

def test_load_config():
    config = load_config()
    assert isinstance(config, dict)
    assert "debug" in config
''',
        }
    },
    user_request="Fix any syntax errors in the codebase and ensure all tests pass",
    expected_artifacts=[
        "src/config.py",  # Should be fixed
    ],
    expected_dod_checks=[
        "tests pass",
        "no errors",
        "git commit",
    ],
    known_failure_modes=[
        "infinite retry loop - agent retries same failing operation without learning"
    ],
    timeout_seconds=120,  # Should complete quickly or timeout
    metadata={
        "difficulty": "medium",
        "failure_rate_historical": "28%",
        "tags": ["retry_loop", "stuck", "resource_waste"]
    }
)
