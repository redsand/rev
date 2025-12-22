"""Scenario 03: Agent gets empty tool result but pretends success.

Historical failure: Tool returns empty result or error, but agent continues as if
it succeeded. This leads to incomplete implementations based on faulty assumptions.
"""

from tests.agent_scenarios.framework import AgentScenario


scenario = AgentScenario(
    name="empty_tool_pretend_success",
    description="Agent ignores empty/error tool results and continues",
    initial_state={
        "git_enabled": True,
        "files": {
            "README.md": '''# My Project

This is a sample project.
''',
            "src/main.py": '''def main():
    print("Hello World")

if __name__ == "__main__":
    main()
''',
        }
    },
    user_request="Find and fix all TODO comments in the codebase",
    expected_artifacts=[
        # No files should be modified since there are no TODOs
    ],
    expected_dod_checks=[
        "output contains: no TODO",  # Should report no TODOs found
        "no errors",  # Should handle gracefully
    ],
    known_failure_modes=[
        "empty tool result ignored - agent continues despite empty search results"
    ],
    timeout_seconds=120,
    metadata={
        "difficulty": "easy",
        "failure_rate_historical": "18%",
        "tags": ["empty_result", "error_handling", "false_positive"]
    }
)
