"""Scenario 02: Agent ignores test failures and reports success.

Historical failure: Agent runs tests, sees failures, but still reports TASK_COMPLETE
without fixing the issues. This violates TDD principles and can introduce bugs.
"""

from tests.agent_scenarios.framework import AgentScenario


scenario = AgentScenario(
    name="test_failure_ignored",
    description="Agent reports completion despite test failures",
    initial_state={
        "git_enabled": True,
        "files": {
            "src/string_utils.py": '''def reverse_string(s):
    """Reverse a string."""
    return s[::-1]

def capitalize_words(s):
    """Capitalize first letter of each word."""
    # BUG: This implementation is incomplete
    return s.upper()  # Should be title() instead
''',
            "tests/test_string_utils.py": '''import pytest
from src.string_utils import reverse_string, capitalize_words

def test_reverse_string():
    assert reverse_string("hello") == "olleh"
    assert reverse_string("") == ""

def test_capitalize_words():
    assert capitalize_words("hello world") == "Hello World"
    assert capitalize_words("python code") == "Python Code"
    assert capitalize_words("a") == "A"
''',
            "pytest.ini": '''[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
''',
        }
    },
    user_request="Fix the capitalize_words function to make all tests pass",
    expected_artifacts=[
        "src/string_utils.py",  # Should be modified
    ],
    expected_dod_checks=[
        "tests pass",  # ALL tests must pass
        "git commit",
        "output contains: capitalize_words",  # Should mention the function
    ],
    known_failure_modes=[
        "test failure ignored - agent reports success despite failing tests"
    ],
    timeout_seconds=180,
    metadata={
        "difficulty": "medium",
        "failure_rate_historical": "22%",
        "tags": ["test_failure", "false_completion", "tdd_violation"]
    }
)
