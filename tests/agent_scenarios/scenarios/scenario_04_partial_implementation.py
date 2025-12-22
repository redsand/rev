"""Scenario 04: Agent implements only part of the requested feature.

Historical failure: Agent completes some subtasks but reports overall success
without implementing all requested functionality. Common with multi-part requests.
"""

from tests.agent_scenarios.framework import AgentScenario


scenario = AgentScenario(
    name="partial_implementation",
    description="Agent implements partial feature and claims completion",
    initial_state={
        "git_enabled": True,
        "files": {
            "src/user.py": '''class User:
    def __init__(self, username):
        self.username = username
        self.email = None

    def set_email(self, email):
        self.email = email
''',
            "tests/test_user.py": '''import pytest
from src.user import User

def test_create_user():
    user = User("john")
    assert user.username == "john"

def test_set_email():
    user = User("john")
    user.set_email("john@example.com")
    assert user.email == "john@example.com"
''',
        }
    },
    user_request="Add password hashing to User class: (1) add set_password method that hashes the password, (2) add check_password method to verify passwords, (3) add tests for both methods",
    expected_artifacts=[
        "src/user.py",  # Should have both methods
        "tests/test_user.py",  # Should have tests for both
    ],
    expected_dod_checks=[
        "output contains: set_password",
        "output contains: check_password",
        "output contains: test",
        "tests pass",
    ],
    known_failure_modes=[
        "partial implementation - agent completes some requirements but not all"
    ],
    timeout_seconds=240,
    metadata={
        "difficulty": "hard",
        "failure_rate_historical": "35%",
        "tags": ["partial_completion", "multi_part_request", "missing_implementation"]
    }
)
