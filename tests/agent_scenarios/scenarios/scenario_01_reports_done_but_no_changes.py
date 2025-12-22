"""Scenario 01: Agent reports done but makes no changes.

Historical failure: Agent claims TASK_COMPLETE but actually made no modifications
to the codebase. This happens when the agent misunderstands the task or gets
stuck but still reports success.
"""

from tests.agent_scenarios.framework import AgentScenario


scenario = AgentScenario(
    name="reports_done_but_no_changes",
    description="Agent claims completion but makes no actual changes to code",
    initial_state={
        "git_enabled": True,
        "files": {
            "src/calculator.py": '''def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    # BUG: No check for division by zero
    return a / b
''',
            "tests/test_calculator.py": '''import pytest
from src.calculator import add, subtract, multiply, divide

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 3) == 2

def test_multiply():
    assert multiply(4, 3) == 12

def test_divide():
    assert divide(10, 2) == 5
    # TODO: Add test for division by zero
''',
        }
    },
    user_request="Add a check for division by zero in the divide function and raise ValueError with a clear message",
    expected_artifacts=[
        "src/calculator.py",  # Should be modified
    ],
    expected_dod_checks=[
        "git commit",  # Changes should be committed
        "file exists: src/calculator.py",
        "output contains: ValueError",  # Should mention the fix
    ],
    known_failure_modes=[
        "reports done but no changes - agent claims success without modifying files"
    ],
    timeout_seconds=180,
    metadata={
        "difficulty": "easy",
        "failure_rate_historical": "15%",
        "tags": ["false_completion", "no_action"]
    }
)
