"""
Tests for TestExecutorAgent command validation fix.

Ensures that qwen3-coder and other models cannot choose wrong test commands
for a project type (e.g., pytest on Node.js projects).

This addresses the regression where qwen3-coder chose pytest even when
the task explicitly said "npm test" on a Node.js project.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from rev.agents.test_executor import TestExecutorAgent
from rev.models.task import Task
from rev.core.context import RevContext


class TestCommandValidation:
    """Test Priority 1: Task description explicit command takes precedence."""

    def test_explicit_npm_test_overrides_pytest_choice(self, tmp_path):
        """Test that explicit 'npm test' in task overrides LLM choosing pytest."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run npm test to validate the changes to app.js",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # Create package.json to indicate Node.js project
        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        # LLM chooses pytest (WRONG)
        corrected = agent._validate_and_correct_test_command("pytest", task, context)

        # Should correct to npm test
        assert corrected == "npm test"

    def test_explicit_pytest_overrides_npm_choice(self, tmp_path):
        """Test that explicit 'pytest' in task overrides LLM choosing npm test."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run pytest to validate the changes to auth.py",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # LLM chooses npm test (WRONG for Python)
        corrected = agent._validate_and_correct_test_command("npm test", task, context)

        # Should correct to pytest
        assert corrected == "pytest"

    def test_yarn_test_explicit_command(self, tmp_path):
        """Test that explicit 'yarn test' is respected."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run yarn test to validate the changes",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        corrected = agent._validate_and_correct_test_command("pytest", task, context)
        assert corrected == "yarn test"


class TestFileExtensionDetection:
    """Test Priority 2: File extension detection corrects wrong commands."""

    def test_js_file_triggers_npm_test(self, tmp_path):
        """Test that .js file in task triggers npm test, not pytest."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run tests to validate changes to app.js",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # Create package.json
        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        # LLM chooses pytest (WRONG)
        corrected = agent._validate_and_correct_test_command("pytest", task, context)

        # Should correct to npm test
        assert corrected == "npm test"

    def test_ts_file_triggers_npm_test(self, tmp_path):
        """Test that .ts file in task triggers npm test, not pytest."""
        agent = TestExecutorAgent()
        task = Task(
            description="Validate changes to index.ts",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        corrected = agent._validate_and_correct_test_command("pytest", task, context)
        assert corrected == "npm test"

    def test_py_file_triggers_pytest(self, tmp_path):
        """Test that .py file in task triggers pytest, not npm test."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run tests to validate changes to auth.py",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # LLM chooses npm test (WRONG)
        corrected = agent._validate_and_correct_test_command("npm test", task, context)

        # Should correct to pytest
        assert corrected == "pytest"

    def test_go_file_triggers_go_test(self, tmp_path):
        """Test that .go file in task triggers go test, not pytest."""
        agent = TestExecutorAgent()
        task = Task(
            description="Validate changes to main.go",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        corrected = agent._validate_and_correct_test_command("pytest", task, context)
        assert corrected == "go test ./..."


class TestWorkspaceDetection:
    """Test Priority 3: Workspace project type markers correct commands."""

    def test_package_json_triggers_npm_test(self, tmp_path):
        """Test that package.json presence triggers npm test for generic task."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run tests to validate the changes",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # Create package.json
        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        # LLM chooses pytest (WRONG)
        corrected = agent._validate_and_correct_test_command("pytest", task, context)

        # Should correct to npm test
        assert corrected == "npm test"

    def test_yarn_lock_triggers_yarn_test(self, tmp_path):
        """Test that yarn.lock presence triggers yarn test."""
        agent = TestExecutorAgent()
        task = Task(
            description="Validate changes to app.js",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        (tmp_path / "yarn.lock").write_text('')

        corrected = agent._validate_and_correct_test_command("pytest", task, context)
        assert corrected == "yarn test"

    def test_mixed_project_prefers_python_when_markers_exist(self, tmp_path):
        """Test that projects with both Node.js and Python keep pytest if Python markers exist."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run tests",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        # Create both package.json and requirements.txt (mixed project)
        (tmp_path / "package.json").write_text('{"name": "test-app"}')
        (tmp_path / "requirements.txt").write_text('pytest\nflask')

        # LLM chooses pytest (CORRECT for mixed project)
        corrected = agent._validate_and_correct_test_command("pytest", task, context)

        # Should NOT correct - pytest is valid for mixed projects
        assert corrected == "pytest"


class TestIntegrationWithLLM:
    """Integration tests with LLM response validation."""

    def test_llm_pytest_choice_gets_corrected(self, tmp_path):
        """Test that LLM choosing pytest on Node.js project gets corrected before execution."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run npm test to validate changes to app.js",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            # Mock LLM response with WRONG command (pytest)
            mock_chat.return_value = {
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "run_tests",
                            "arguments": {"cmd": "pytest"}
                        }
                    }]
                }
            }
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Verify execute_tool was called with CORRECTED command
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][0] == "run_tests"
            # The command should have been corrected to npm test
            assert call_args[0][1]["cmd"] == "npm test"

    def test_llm_correct_choice_not_modified(self, tmp_path):
        """Test that LLM choosing correct command is not modified."""
        agent = TestExecutorAgent()
        task = Task(
            description="Run npm test to validate changes to app.js",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            # Mock LLM response with CORRECT command
            mock_chat.return_value = {
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "run_tests",
                            "arguments": {"cmd": "npm test"}
                        }
                    }]
                }
            }
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Verify execute_tool was called with unchanged command
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][1]["cmd"] == "npm test"


class TestRecoveryPathValidation:
    """Test that command validation works in recovery path too."""

    def test_recovery_path_corrects_pytest_to_npm(self, tmp_path):
        """Test that recovered tool calls also get command validation."""
        from rev.core.tool_call_recovery import RecoveredToolCall

        agent = TestExecutorAgent()
        task = Task(
            description="Run npm test to validate app.js changes",
            action_type="test"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        (tmp_path / "package.json").write_text('{"name": "test-app"}')

        with patch('rev.agents.test_executor.ollama_chat') as mock_chat, \
             patch('rev.core.tool_call_recovery.recover_tool_call_from_text') as mock_recover, \
             patch('rev.agents.test_executor.execute_tool') as mock_execute, \
             patch('rev.agents.test_executor.build_subagent_output') as mock_output:

            # Mock LLM response with no tool calls (triggers recovery)
            mock_chat.return_value = {
                "message": {
                    "content": "I'll run the tests using pytest"
                }
            }

            # Mock recovery returning WRONG command
            mock_recover.return_value = RecoveredToolCall(
                name="run_tests",
                arguments={"cmd": "pytest"}
            )
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Verify execute_tool was called with CORRECTED command
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][1]["cmd"] == "npm test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
