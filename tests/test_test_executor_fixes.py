"""
Tests for TestExecutorAgent fixes to prevent wrong test framework selection.

Tests cover:
- Tool call recovery before falling back to heuristics
- Project type detection (package.json → npm test, not pytest)
- Test skip logic respecting failed test results
"""

import pytest
from pathlib import Path
import uuid
from unittest.mock import Mock, MagicMock, patch
from rev.agents.test_executor import TestExecutorAgent
from rev.models.task import Task
from rev.core.context import RevContext


def _cmd_str(cmd):
    if isinstance(cmd, list):
        return " ".join(cmd)
    return cmd


def _make_root() -> Path:
    root = Path("tmp_test") / "test_executor" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


class TestToolCallRecovery:
    """Test that TestExecutorAgent recovers tool calls from text before falling back."""

    def test_recovers_tool_call_from_text_response(self):
        """Test that text responses with JSON are recovered before falling back to heuristics."""
        agent = TestExecutorAgent()
        task = Task(description="Run the test suite", action_type="test")
        context = RevContext(user_request="Test request")

        # Simulate LLM returning text with JSON instead of proper tool call
        mock_response = {
            "message": {
                "content": '{"tool_name": "run_tests", "arguments": {"cmd": "npm test"}}'
            }
        }

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = mock_response
            mock_execute.return_value = '{"rc": 0, "stdout": "tests passed"}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should have recovered the tool call and executed run_tests
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][0] == "run_tests"
            assert call_args[0][1]["cmd"] == "npm test"

    def test_falls_back_only_when_recovery_fails(self):
        """Test that fallback heuristic is only used when recovery also fails."""
        agent = TestExecutorAgent()
        task = Task(description="Run tests", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        # Create package.json to make it a Node.js project
        (root / "package.json").write_text('{"name": "test", "scripts": {"test": "jest"}}')

        # Simulate LLM returning unusable content
        mock_response = {
            "message": {
                "content": "I will run the tests now."  # No JSON
            }
        }

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = mock_response
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should fall back to heuristic: npm test (detected from package.json)
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][0] == "run_cmd"
            cmd_value = call_args[0][1].get("cmd")
            cmd_str = _cmd_str(cmd_value)
            assert "npm test" in cmd_str


class TestProjectTypeDetection:
    """Test that fallback heuristic detects project type correctly."""

    def _cmd_str(self, cmd):
        if isinstance(cmd, list):
            return " ".join(cmd)
        return cmd

    def test_detects_nodejs_project_with_package_json(self):
        """Test that package.json → npm test, not pytest."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        # Create package.json to make it a Node.js project
        (root / "package.json").write_text('{"name": "test-app", "scripts": {"test": "jest"}}')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            # LLM fails to provide tool call
            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should use npm test, NOT pytest
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "npm test" in cmd
            assert "pytest" not in cmd

    def test_detects_yarn_project(self):
        """Test that yarn.lock → yarn test."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        (root / "package.json").write_text('{"name": "test-app", "scripts": {"test": "jest"}}')
        (root / "yarn.lock").write_text('')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "yarn test" in cmd

    def test_detects_pnpm_project(self):
        """Test that pnpm-lock.yaml → pnpm test."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        (root / "package.json").write_text('{"name": "test-app", "scripts": {"test": "jest"}}')
        (root / "pnpm-lock.yaml").write_text('')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "pnpm test" in cmd

    def test_detects_go_project(self):
        """Test that go.mod → go test ./..."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        (root / "go.mod").write_text('module test')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "go test" in cmd

    def test_detects_rust_project(self):
        """Test that Cargo.toml → cargo test."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        (root / "Cargo.toml").write_text('[package]\nname = "test"')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "cargo test" in cmd

    def test_uses_pytest_when_python_markers_present(self):
        """Test that pytest is used when Python project markers are present."""
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root

        (root / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            call_args = mock_execute.call_args
            cmd = self._cmd_str(call_args[0][1]["cmd"])
            assert "pytest" in cmd

    def test_unknown_project_skips_with_sentinel(self, monkeypatch):
        agent = TestExecutorAgent()
        task = Task(description="Run test suite", action_type="test")
        context = RevContext(user_request="Test request")
        root = _make_root()
        context.workspace_root = root
        import rev.config as rev_config
        monkeypatch.setattr(rev_config, "ROOT", root)

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = None
            mock_execute.return_value = '{"rc": 0, "stdout": "REV_NO_TEST_RUNNER"}'
            mock_output.return_value = "success"

            agent.execute(task, context)

            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            cmd = call_args[0][1]["cmd"]
            if isinstance(cmd, list):
                assert "REV_NO_TEST_RUNNER" in " ".join(cmd)
            else:
                assert "REV_NO_TEST_RUNNER" in cmd


class TestNoTestsFoundRetry:
    """Test retry behavior when test runner finds no tests."""

    def test_reruns_jest_with_run_tests_by_path(self):
        agent = TestExecutorAgent()
        task = Task(description="Run jest on tests/api/users.test.js", action_type="test")
        context = RevContext(user_request="Test request")

        mock_response = {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_tests",
                            "arguments": {
                                "cmd": "npx jest tests/api/users.test.js"
                            },
                        }
                    }
                ]
            }
        }

        results = [
            '{"rc": 1, "stdout": "No tests found"}',
            '{"rc": 0, "stdout": "1 passed"}',
        ]

        def fake_execute(_tool, _args, agent_name=None):
            return results.pop(0)

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = mock_response
            mock_execute.side_effect = fake_execute
            mock_output.return_value = "success"

            agent.execute(task, context)

            assert mock_execute.call_count == 2
            first_call = mock_execute.call_args_list[0][0]
            second_call = mock_execute.call_args_list[1][0]
            assert first_call[0] == "run_tests"
            assert second_call[0] == "run_tests"
            assert "--runTestsByPath" in second_call[1]["cmd"]

    def test_reruns_npm_test_with_double_dash(self):
        agent = TestExecutorAgent()
        task = Task(description="Run tests to validate tests/user_api.test.js", action_type="test")
        context = RevContext(user_request="Test request")

        mock_response = {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_tests",
                            "arguments": {
                                "cmd": "npm test tests/user_api.test.js"
                            },
                        }
                    }
                ]
            }
        }

        results = [
            '{"rc": 1, "stdout": "No tests found, exiting with code 1"}',
            '{"rc": 0, "stdout": "1 passed"}',
        ]

        def fake_execute(_tool, _args, agent_name=None):
            return results.pop(0)

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            mock_chat.return_value = mock_response
            mock_execute.side_effect = fake_execute
            mock_output.return_value = "success"

            agent.execute(task, context)

            assert mock_execute.call_count == 2
            second_call = mock_execute.call_args_list[1][0]
            rerun_cmd = second_call[1]["cmd"]
            if isinstance(rerun_cmd, list):
                normalized = [str(part).replace("\\", "/") for part in rerun_cmd]
                assert "--" in rerun_cmd
                assert "tests/user_api.test.js" in normalized
            else:
                assert "npm test -- tests/user_api.test.js" in rerun_cmd


class TestSkipLogicRespectsFailures:
    """Test that test skip logic doesn't block retries after failures."""

    def test_does_not_skip_after_failed_test(self):
        """Test that tests are re-run if previous test failed (rc != 0)."""
        agent = TestExecutorAgent()
        task = Task(description="Run the test suite", action_type="test")
        context = RevContext(user_request="Test request")

        # Simulate previous test run that failed
        context.set_agent_state("last_test_iteration", 5)
        context.set_agent_state("last_code_change_iteration", 3)
        context.set_agent_state("last_test_rc", 5)  # pytest rc=5 (no tests collected)
        context.set_agent_state("current_iteration", 6)

        # Should NOT skip because last test failed (rc=5)
        should_skip = agent._should_skip_pytest(task, context)
        assert should_skip is False

    def test_skips_after_successful_test_with_no_changes(self):
        """Test that tests are skipped if previous test passed and no code changes."""
        agent = TestExecutorAgent()
        task = Task(description="Run the test suite", action_type="test")
        context = RevContext(user_request="Test request")

        # Simulate previous test run that succeeded
        context.set_agent_state("last_test_iteration", 5)
        context.set_agent_state("last_code_change_iteration", 3)
        context.set_agent_state("last_test_rc", 0)  # Success
        context.set_agent_state("current_iteration", 6)

        # Should skip because last test passed and no changes since
        should_skip = agent._should_skip_pytest(task, context)
        assert should_skip is True

    def test_does_not_skip_after_code_changes(self):
        """Test that tests are re-run if code changed after last test."""
        agent = TestExecutorAgent()
        task = Task(description="Run the test suite", action_type="test")
        context = RevContext(user_request="Test request")

        # Simulate code change after last test
        context.set_agent_state("last_test_iteration", 3)
        context.set_agent_state("last_code_change_iteration", 5)
        context.set_agent_state("last_test_rc", 0)
        context.set_agent_state("current_iteration", 6)

        # Should NOT skip because code changed after last test
        should_skip = agent._should_skip_pytest(task, context)
        assert should_skip is False


class TestIntegrationScenario:
    """Integration test simulating the bug from the user's log."""

    def test_nodejs_project_does_not_run_pytest(self):
        """
        Simulate the bug: TestExecutorAgent runs pytest on a Node.js project.
        After fix: Should run npm test instead.
        """
        agent = TestExecutorAgent()
        task = Task(description="Run the test suite to verify the new feature (TDD green must pass).", action_type="test")
        context = RevContext(user_request="Create test app")
        root = _make_root()
        context.workspace_root = root

        # Create Node.js project structure
        (root / "package.json").write_text('{"name": "test-app", "scripts": {"test": "jest"}}')
        (root / "routes").mkdir()
        (root / "routes" / "users.js").write_text('module.exports = {};')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            # LLM fails to provide proper tool call (simulating the log issue)
            mock_chat.return_value = {
                "message": {
                    "content": "Running tests..."
                }
            }
            mock_execute.return_value = '{"rc": 0, "stdout": "All tests passed"}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Verify npm test was called, NOT pytest
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            cmd = _cmd_str(call_args[0][1]["cmd"])

            # The critical assertion: must use npm test for Node.js project
            assert "npm test" in cmd, f"Expected 'npm test' but got '{cmd}'"
            assert "pytest" not in cmd, f"Should NOT use pytest on Node.js project, but got '{cmd}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
