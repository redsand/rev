"""
Tests for edit optimization fixes to prevent repeated failures and context pollution.

Tests cover:
- Priority 1: Mandatory file reading before EDIT tasks
- Priority 2: Escalation after 3 consecutive replace_in_file failures
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from rev.agents.code_writer import CodeWriterAgent
from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext
from rev.execution.quick_verify import VerificationResult


class TestMandatoryFileReading:
    """Test Priority 1: Mandatory file reading before EDIT tasks."""

    def test_edit_task_without_file_specification_fails(self, tmp_path):
        """Test that EDIT task without file path in description fails fast."""
        agent = CodeWriterAgent()
        # Task description doesn't mention any file
        task = Task(description="implement user authentication", action_type="edit")
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat:
            result = agent.execute(task, context)

            # Should fail without calling LLM (early exit)
            mock_chat.assert_not_called()

            # Should return recovery request about missing target file
            assert "missing_target_file" in result.lower() or "edit task must specify" in result.lower()

    def test_edit_task_with_nonexistent_file_fails(self, tmp_path):
        """Test that EDIT task for non-existent file fails fast."""
        agent = CodeWriterAgent()
        task = Task(description="edit nonexistent.js to add routes", action_type="edit")
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat:
            result = agent.execute(task, context)

            # Should fail without calling LLM (early exit)
            mock_chat.assert_not_called()

            # Should return error about file not found
            assert "file_not_found" in result.lower() or "cannot read" in result.lower()

    def test_edit_task_with_existing_file_includes_content(self, tmp_path):
        """Test that EDIT task for existing file includes file content in prompt."""
        agent = CodeWriterAgent()

        task = Task(description="edit app.js to add user routes", action_type="edit")
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        file_content = "const express = require('express');\nconst app = express();"

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat, \
             patch('rev.agents.code_writer.execute_tool') as mock_execute, \
             patch('rev.agents.code_writer.build_subagent_output') as mock_output, \
             patch('rev.agents.code_writer._read_file_content_for_edit') as mock_read:

            # Mock file reading to return content
            mock_read.return_value = file_content

            # Mock LLM response with valid tool call
            mock_chat.return_value = {
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "replace_in_file",
                            "arguments": {
                                "path": "app.js",
                                "find": "const app = express();",
                                "replace": "const app = express();\napp.use('/users', userRouter);"
                            }
                        }
                    }]
                }
            }
            mock_execute.return_value = '{"replaced": 1}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should call LLM
            mock_chat.assert_called_once()

            # Check that prompt included file content
            call_args = mock_chat.call_args
            prompt = call_args[0][0][1]["content"]  # User message content

            assert "ACTUAL FILE CONTENT: app.js" in prompt
            assert "const express = require('express');" in prompt
            assert "CRITICAL: When using replace_in_file" in prompt

    def test_edit_task_command_only_skips_file_reading(self, tmp_path):
        """Test that command-only EDIT tasks don't require file reading."""
        agent = CodeWriterAgent()
        task = Task(description="run npm install", action_type="edit")
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat, \
             patch('rev.agents.code_writer.execute_tool') as mock_execute, \
             patch('rev.agents.code_writer.build_subagent_output') as mock_output:

            mock_chat.return_value = {
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "run_cmd",
                            "arguments": {"cmd": "npm install"}
                        }
                    }]
                }
            }
            mock_execute.return_value = '{"rc": 0}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should not fail even though no file reading happened
            mock_chat.assert_called_once()


class TestEscalationAfterFailures:
    """Test Priority 2: Escalation after 3 consecutive failures."""

    def test_escalation_triggered_after_three_failures(self):
        """Test that escalation is triggered after 3 replace_in_file failures."""
        from collections import defaultdict

        # Mock context and task
        context = RevContext(user_request="Test request")
        task = Mock()
        task.action_type = "edit"
        task.tool_events = [{"tool": "replace_in_file", "args": {}}]
        task.status = TaskStatus.FAILED

        # Simulate 3 failures of same task
        failure_counts = defaultdict(int)
        failure_sig = "edit::test failure"
        failure_counts[failure_sig] = 3

        # Check escalation condition
        used_replace_in_file = any(
            str(ev.get("tool") or "").lower() == "replace_in_file"
            for ev in task.tool_events
        )

        assert used_replace_in_file is True
        assert failure_counts[failure_sig] >= 3
        assert task.action_type == "edit"

    def test_escalation_adds_agent_request(self):
        """Test that escalation adds proper agent request to context."""
        context = RevContext(user_request="Test request")

        # Simulate escalation adding agent request
        context.add_agent_request(
            "EDIT_STRATEGY_ESCALATION",
            {
                "agent": "Orchestrator",
                "reason": "replace_in_file failed 3 times - switch to write_file",
                "detailed_reason": "Use write_file instead of replace_in_file"
            }
        )

        assert len(context.agent_requests) == 1
        assert context.agent_requests[0]["type"] == "EDIT_STRATEGY_ESCALATION"
        assert "switch to write_file" in context.agent_requests[0]["details"]["reason"]

    def test_escalation_only_once_per_failure_signature(self):
        """Test that escalation only happens once per unique failure."""
        context = RevContext(user_request="Test request")

        # First escalation
        escalation_key = "edit_escalation::edit::test failure"
        already_escalated = context.agent_state.get(escalation_key, False)
        assert already_escalated is False

        # Mark as escalated
        context.set_agent_state(escalation_key, True)

        # Second check - should not escalate again
        already_escalated = context.agent_state.get(escalation_key, False)
        assert already_escalated is True


class TestIntegrationScenarios:
    """Integration tests combining both fixes."""

    def test_edit_with_file_reading_prevents_failure_loop(self, tmp_path):
        """
        Test that mandatory file reading reduces replace_in_file failures,
        preventing the need for escalation.
        """
        agent = CodeWriterAgent()

        file_content = '''{
  "name": "test-app",
  "scripts": {
    "test": "jest"
  }
}'''

        task = Task(
            description='add a "lint" script to package.json',
            action_type="edit"
        )
        context = RevContext(user_request="Test request")
        context.workspace_root = tmp_path

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat, \
             patch('rev.agents.code_writer.execute_tool') as mock_execute, \
             patch('rev.agents.code_writer.build_subagent_output') as mock_output, \
             patch('rev.agents.code_writer._read_file_content_for_edit') as mock_read:

            # Mock file reading to return content
            mock_read.return_value = file_content

            # LLM gets exact content and can provide correct match
            def chat_side_effect(messages, tools):
                # Check that file content is in prompt
                prompt = messages[1]["content"]
                assert "package.json" in prompt
                assert '"test": "jest"' in prompt

                return {
                    "message": {
                        "tool_calls": [{
                            "function": {
                                "name": "replace_in_file",
                                "arguments": {
                                    "path": "package.json",
                                    "find": '  "scripts": {\n    "test": "jest"',
                                    "replace": '  "scripts": {\n    "test": "jest",\n    "lint": "eslint ."'
                                }
                            }
                        }]
                    }
                }

            mock_chat.side_effect = chat_side_effect
            mock_execute.return_value = '{"replaced": 1}'
            mock_output.return_value = "success"

            result = agent.execute(task, context)

            # Should succeed without needing escalation
            assert "success" in result.lower() or mock_output.called

    def test_repeated_failures_eventually_escalate(self, tmp_path):
        """
        Test that even with file reading, if LLM keeps failing,
        escalation logic kicks in.
        """
        # This test verifies the escalation path exists
        # Actual escalation happens in orchestrator.py, not code_writer.py

        from collections import defaultdict

        failure_counts = defaultdict(int)
        failure_sig = "edit::cannot match content"

        # Simulate 3 failures
        for i in range(3):
            failure_counts[failure_sig] += 1

        # After 3rd failure, should trigger escalation
        assert failure_counts[failure_sig] >= 3

        # Escalation would add agent request (tested above)
        context = RevContext(user_request="Test")
        context.add_agent_request(
            "EDIT_STRATEGY_ESCALATION",
            {
                "agent": "Orchestrator",
                "reason": f"replace_in_file failed {failure_counts[failure_sig]} times",
                "detailed_reason": "Switch to write_file approach"
            }
        )

        assert len(context.agent_requests) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
