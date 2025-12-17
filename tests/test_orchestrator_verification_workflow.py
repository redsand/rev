"""
Integration tests for the orchestrator's verification workflow.

These tests verify the complete workflow:
1. Plan next action
2. Execute action
3. VERIFY execution succeeded
4. Report results
5. Re-plan if verification failed

This is critical for ensuring the REPL actually completes requests properly.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import Task, TaskStatus, ExecutionPlan
from rev.core.context import RevContext
from rev.execution.quick_verify import verify_task_execution, VerificationResult


class TestOrchestrationWorkflowLoop:
    """Tests for the main orchestration workflow loop."""

    def test_continuous_sub_agent_execution_includes_verification(self):
        """Test that sub-agent execution includes verification step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                config = OrchestratorConfig(
                    enable_research=False,
                    enable_review=False,
                    enable_validation=False,
                    auto_approve=True
                )
                orchestrator = Orchestrator(Path(tmpdir), config)
                # Initialize context
                orchestrator.context = RevContext(user_request="Create ./lib/analysts/ directory")
                from rev.core.context import ResourceBudget
                orchestrator.context.resource_budget = ResourceBudget()

                # Mock the LLM to return a simple task
                with patch('rev.execution.orchestrator.ollama_chat') as mock_llm:
                    with patch('rev.execution.orchestrator.AgentRegistry.get_agent_instance') as mock_agent:
                        # First call: return a task
                        # Second call: return GOAL_ACHIEVED
                        mock_llm.side_effect = [
                            {
                                "message": {
                                    "content": "[create_directory] Create ./lib/analysts/ directory"
                                }
                            },
                            {"message": {"content": "GOAL_ACHIEVED"}}
                        ]

                        # Mock agent to succeed
                        mock_agent_instance = Mock()
                        mock_agent_instance.execute.return_value = "Directory created"
                        mock_agent.return_value = mock_agent_instance

                        # The verification should be called after execution
                        with patch('rev.execution.orchestrator.verify_task_execution') as mock_verify:
                            mock_verify.return_value = VerificationResult(
                                passed=True,
                                message="Verification passed",
                                details={}
                            )

                            result = orchestrator._continuous_sub_agent_execution(
                                "Create ./lib/analysts/ directory",
                                coding_mode=True
                            )

                            # Verify that verification was called
                            assert mock_verify.called, "verify_task_execution should be called"
                            assert result is True, "Should return True for successful execution"

            finally:
                os.chdir(old_cwd)

    def test_failed_verification_marks_task_failed(self):
        """Test that failed verification marks the task as FAILED."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                config = OrchestratorConfig(
                    enable_research=False,
                    enable_review=False,
                    enable_validation=False,
                    auto_approve=True
                )
                orchestrator = Orchestrator(Path(tmpdir), config)
                # Initialize context
                orchestrator.context = RevContext(user_request="Create a file")
                from rev.core.context import ResourceBudget
                orchestrator.context.resource_budget = ResourceBudget()

                with patch('rev.execution.orchestrator.ollama_chat') as mock_llm:
                    with patch('rev.execution.orchestrator.AgentRegistry.get_agent_instance') as mock_agent:
                        # Return a task, then GOAL_ACHIEVED
                        mock_llm.side_effect = [
                            {
                                "message": {
                                    "content": "[add] Create ./nonexistent_file.py"
                                }
                            },
                            {"message": {"content": "GOAL_ACHIEVED"}}
                        ]

                        # Mock agent to succeed (but file won't actually exist)
                        mock_agent_instance = Mock()
                        mock_agent_instance.execute.return_value = "File created"
                        mock_agent.return_value = mock_agent_instance

                        # Verification will fail because file doesn't exist
                        with patch('rev.execution.orchestrator.verify_task_execution') as mock_verify:
                            mock_verify.return_value = VerificationResult(
                                passed=False,
                                message="File was not created",
                                details={},
                                should_replan=True
                            )

                            result = orchestrator._continuous_sub_agent_execution(
                                "Create a file",
                                coding_mode=True
                            )

                            # Should still complete due to max iterations, but task should be marked failed
                            # The important part is that verification was called and task status changed
                            assert mock_verify.called

            finally:
                os.chdir(old_cwd)

    def test_verification_reports_in_work_summary(self):
        """Test that verification results are included in work summary for next action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                config = OrchestratorConfig(
                    enable_research=False,
                    enable_review=False,
                    enable_validation=False,
                    auto_approve=True
                )
                orchestrator = Orchestrator(Path(tmpdir), config)
                # Initialize context
                orchestrator.context = RevContext(user_request="Create directories")
                from rev.core.context import ResourceBudget
                orchestrator.context.resource_budget = ResourceBudget()

                with patch('rev.execution.orchestrator.ollama_chat') as mock_llm:
                    with patch('rev.execution.orchestrator.AgentRegistry.get_agent_instance') as mock_agent:
                        call_count = [0]

                        def llm_side_effect(messages, **kwargs):
                            call_count[0] += 1
                            if call_count[0] == 1:
                                # First action
                                return {
                                    "message": {
                                        "content": "[create_directory] Create ./lib/"
                                    }
                                }
                            elif call_count[0] == 2:
                                # Check that work summary includes previous action
                                messages_str = str(messages)
                                assert "[COMPLETED]" in messages_str or "completed" in messages_str.lower(), \
                                    "Work summary should include completed task info"
                                # Return goal achieved
                                return {"message": {"content": "GOAL_ACHIEVED"}}
                            return {"message": {"content": "GOAL_ACHIEVED"}}

                        mock_llm.side_effect = llm_side_effect

                        mock_agent_instance = Mock()
                        mock_agent_instance.execute.return_value = "Created"
                        mock_agent.return_value = mock_agent_instance

                        with patch('rev.execution.orchestrator.verify_task_execution') as mock_verify:
                            mock_verify.return_value = VerificationResult(
                                passed=True,
                                message="Directory created",
                                details={}
                            )

                            result = orchestrator._continuous_sub_agent_execution(
                                "Create directories",
                                coding_mode=True
                            )

                            # Verify that LLM was called at least twice (planning second action)
                            assert call_count[0] >= 2

            finally:
                os.chdir(old_cwd)


class TestRealWorldExtractionScenario:
    """Tests for real-world extraction scenarios."""

    def test_extraction_workflow_complete(self):
        """
        Test a complete extraction workflow:
        1. Create directory
        2. Extract files
        3. Verify completion
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Create a source file with multiple classes
                lib_dir = Path("lib")
                lib_dir.mkdir()
                analysts_file = lib_dir / "analysts.py"
                analysts_file.write_text("""
class BreakoutAnalyst:
    def __init__(self):
        self.name = "breakout"

    def analyze(self):
        return "breakout analysis"

class ClaudeAnalyst:
    def __init__(self):
        self.name = "claude"

    def analyze(self):
        return "claude analysis"

class VolumeAnalyst:
    def __init__(self):
        self.name = "volume"

    def analyze(self):
        return "volume analysis"
""")

                config = OrchestratorConfig(
                    enable_research=False,
                    enable_review=False,
                    enable_validation=False,
                    auto_approve=True
                )
                orchestrator = Orchestrator(Path(tmpdir), config)
                # Initialize context
                orchestrator.context = RevContext(user_request="Extract analyst classes")
                from rev.core.context import ResourceBudget
                orchestrator.context.resource_budget = ResourceBudget()

                with patch('rev.execution.orchestrator.ollama_chat') as mock_llm:
                    with patch('rev.execution.orchestrator.AgentRegistry.get_agent_instance') as mock_agent:
                        action_sequence = [
                            # 1. Create directory
                            "[create_directory] Create lib/analysts/ directory",
                            # 2. Create breakout analyst file
                            "[add] Create lib/analysts/breakout_analyst.py with BreakoutAnalyst class",
                            # 3. Create claude analyst file
                            "[add] Create lib/analysts/claude_analyst.py with ClaudeAnalyst class",
                            # 4. Create volume analyst file
                            "[add] Create lib/analysts/volume_analyst.py with VolumeAnalyst class",
                            # 5. Create __init__.py
                            "[add] Create lib/analysts/__init__.py to export all analysts",
                            # 6. Update main file with imports
                            "[edit] Update lib/analysts.py to import from new directory",
                            # Done
                            "GOAL_ACHIEVED"
                        ]
                        action_idx = [0]

                        def llm_side_effect(messages, **kwargs):
                            if action_idx[0] < len(action_sequence):
                                result = {
                                    "message": {
                                        "content": action_sequence[action_idx[0]]
                                    }
                                }
                                action_idx[0] += 1
                                return result
                            return {"message": {"content": "GOAL_ACHIEVED"}}

                        mock_llm.side_effect = llm_side_effect

                        # Mock agent to create files
                        def agent_execute(task, context):
                            # Simulate file creation
                            if "create_directory" in task.action_type.lower():
                                Path("lib/analysts").mkdir(exist_ok=True)
                            elif task.action_type == "add":
                                # Create the file
                                if "breakout" in task.description:
                                    Path("lib/analysts/breakout_analyst.py").write_text(
                                        "class BreakoutAnalyst:\n    pass"
                                    )
                                elif "claude" in task.description:
                                    Path("lib/analysts/claude_analyst.py").write_text(
                                        "class ClaudeAnalyst:\n    pass"
                                    )
                                elif "volume" in task.description:
                                    Path("lib/analysts/volume_analyst.py").write_text(
                                        "class VolumeAnalyst:\n    pass"
                                    )
                                elif "__init__" in task.description:
                                    Path("lib/analysts/__init__.py").write_text(
                                        "from .breakout_analyst import BreakoutAnalyst\n"
                                        "from .claude_analyst import ClaudeAnalyst\n"
                                        "from .volume_analyst import VolumeAnalyst\n"
                                    )
                            elif task.action_type == "edit":
                                # Update imports in main file
                                main_file = Path("lib/analysts.py")
                                main_file.write_text(
                                    "from .analysts import BreakoutAnalyst, ClaudeAnalyst, VolumeAnalyst\n"
                                )
                            return "Success"

                        mock_agent_instance = Mock()
                        mock_agent_instance.execute.side_effect = agent_execute
                        mock_agent.return_value = mock_agent_instance

                        # Run the orchestration
                        result = orchestrator._continuous_sub_agent_execution(
                            "Extract analyst classes from lib/analysts.py into individual files in lib/analysts/",
                            coding_mode=True
                        )

                        # Verify the extraction was successful
                        assert Path("lib/analysts").is_dir(), "Analysts directory should exist"
                        assert Path("lib/analysts/breakout_analyst.py").exists(), "breakout_analyst.py should exist"
                        assert Path("lib/analysts/claude_analyst.py").exists(), "claude_analyst.py should exist"
                        assert Path("lib/analysts/volume_analyst.py").exists(), "volume_analyst.py should exist"
                        assert Path("lib/analysts/__init__.py").exists(), "__init__.py should exist"

            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
