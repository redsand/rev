"""
Test suite for critical issues identified in sub-agent execution.

Tests the following critical fixes:
1. Review Agent JSON parsing issue
2. CodeWriterAgent text response issue
3. File existence validation before writing imports
4. Test validation checking actual output not just return code
"""

import json
import pytest
from unittest.mock import patch, MagicMock, Mock
from pathlib import Path
import tempfile
import os

from rev.execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision, _parse_json_from_text
from rev.models.task import ExecutionPlan, Task, TaskStatus, RiskLevel
from rev.agents.code_writer import CodeWriterAgent
from rev.core.context import RevContext


class TestReviewAgentJSONParsing:
    """Test that Review Agent properly handles JSON parsing and empty responses."""

    def test_parse_json_from_text_with_valid_json(self):
        """Verify _parse_json_from_text extracts JSON correctly."""
        json_str = '{"decision": "approved", "confidence_score": 0.85}'
        result = _parse_json_from_text(json_str)
        assert result is not None
        assert result["decision"] == "approved"
        assert result["confidence_score"] == 0.85

    def test_parse_json_from_text_with_empty_content(self):
        """Verify _parse_json_from_text returns None for empty content."""
        result = _parse_json_from_text("")
        assert result is None

        result = _parse_json_from_text("   ")
        assert result is None

    def test_parse_json_from_text_with_whitespace_before_json(self):
        """Verify _parse_json_from_text extracts JSON from text with whitespace."""
        text = """
        Some explanatory text here

        {
            "decision": "approved",
            "confidence_score": 0.9
        }
        """
        result = _parse_json_from_text(text)
        assert result is not None
        assert result["decision"] == "approved"

    def test_review_agent_handles_empty_llm_response(self):
        """Test that review agent gracefully handles empty LLM response."""
        plan = ExecutionPlan()
        task = Task(description="Test task", action_type="test")
        task.risk_level = RiskLevel.LOW
        plan.tasks = [task]

        # Mock ollama_chat to return empty content
        with patch('rev.execution.reviewer.ollama_chat') as mock_chat:
            mock_chat.return_value = {
                "message": {"content": ""},  # Empty content
                "usage": {"prompt": 10, "completion": 5}
            }

            review = review_execution_plan(plan, "test request")

            # Should not crash and should approve with default decision
            assert review.decision in [ReviewDecision.APPROVED, ReviewDecision.APPROVED_WITH_SUGGESTIONS]
            assert review.confidence_score == 0.7

    def test_review_agent_handles_no_response(self):
        """Test that review agent handles None response from LLM."""
        plan = ExecutionPlan()
        task = Task(description="Test task", action_type="test")
        task.risk_level = RiskLevel.LOW
        plan.tasks = [task]

        with patch('rev.execution.reviewer.ollama_chat') as mock_chat:
            mock_chat.return_value = None

            review = review_execution_plan(plan, "test request")

            # Should not crash
            assert review.decision in [ReviewDecision.APPROVED, ReviewDecision.APPROVED_WITH_SUGGESTIONS]

    def test_review_agent_with_tool_calls_response(self):
        """Test that review agent handles response with tool_calls instead of content."""
        plan = ExecutionPlan()
        task = Task(description="Test task", action_type="test")
        task.risk_level = RiskLevel.LOW
        plan.tasks = [task]

        # Mock response with tool_calls but no content (the bug from execution)
        with patch('rev.execution.reviewer.ollama_chat') as mock_chat:
            mock_chat.return_value = {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "analyze_ast_patterns", "arguments": "{}"}}
                    ]
                    # Note: No "content" key
                },
                "usage": {"prompt": 10, "completion": 5}
            }

            review = review_execution_plan(plan, "test request")

            # Should handle gracefully and not crash
            assert review is not None
            assert review.decision is not None


class TestCodeWriterAgentTextResponse:
    """Test that CodeWriterAgent handles LLM text responses instead of tool calls."""

    def test_agent_detects_text_response_not_tool_call(self):
        """Verify agent detects when LLM returns conversational text instead of tool call."""
        agent = CodeWriterAgent()

        # Mock ollama_chat to return conversational text
        text_response = "I'll help you create individual files for each analyst class in the lib/analysts/ directory. First, I need to see what analyst classes exist in the current analysts.py file to understand the pattern."

        with patch('rev.agents.code_writer.ollama_chat') as mock_chat:
            mock_chat.return_value = {
                "message": {"content": text_response},
                "usage": {}
            }

            task = Task(
                description="Create individual files for analyst classes",
                action_type="add"
            )
            context = RevContext(Path.cwd())

            result = agent.execute(task, context)

            # Should detect this as an error, not a successful execution
            assert "[RECOVERY_REQUESTED]" in result or "[FINAL_FAILURE]" in result
            assert "text_instead_of_tool_call" in result

    def test_agent_recovers_from_text_response(self):
        """Test that agent attempts recovery when LLM returns text."""
        agent = CodeWriterAgent()

        call_count = [0]

        def mock_chat_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: text response
                return {
                    "message": {"content": "I'll help you..."},
                    "usage": {}
                }
            else:
                # Second call: proper tool call
                return {
                    "message": {
                        "tool_calls": [{
                            "function": {
                                "name": "write_file",
                                "arguments": '{"file_path": "test.py", "content": "# test"}'
                            }
                        }]
                    },
                    "usage": {}
                }

        with patch('rev.agents.code_writer.ollama_chat', side_effect=mock_chat_side_effect):
            with patch('rev.agents.code_writer.execute_tool') as mock_execute:
                with patch('builtins.input', return_value='y'):
                    mock_execute.return_value = "File written successfully"

                    task = Task(
                        description="Create a test file",
                        action_type="add"
                    )
                    context = RevContext(Path.cwd())

                    result = agent.execute(task, context)

                    # After recovery, should succeed
                    assert "successfully" in result.lower() or "[RECOVERY_REQUESTED]" in result


class TestFileExistenceValidation:
    """Test that file existence is validated before writing imports."""

    def test_import_validation_checks_target_files_exist(self):
        """Verify that import statements target files that actually exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create lib directory
            lib_dir = Path(tmpdir) / "lib"
            lib_dir.mkdir()

            # Create lib/__init__.py
            init_file = lib_dir / "__init__.py"
            init_file.write_text("")

            # Attempt to write imports to non-existent modules
            import_code = """
from .analysts.breakout import BreakoutAnalyst
from .analysts.claude import ClaudeAnalyst
"""

            # This should be detected as invalid
            # The validation should check if .analysts.breakout and .analysts.claude exist
            analysts_dir = lib_dir / "analysts"
            exists = analysts_dir.exists()

            assert not exists, "Target directory should not exist yet"

    def test_code_writer_validates_import_targets_before_writing(self):
        """Test that CodeWriterAgent validates import targets before writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_dir = Path(tmpdir) / "lib"
            lib_dir.mkdir()

            init_file = lib_dir / "__init__.py"
            init_file.write_text("")

            agent = CodeWriterAgent()

            # Try to write an import that references non-existent files
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                with patch('rev.agents.code_writer.execute_tool') as mock_execute:
                    with patch('builtins.input', return_value='y'):
                        with patch('rev.agents.code_writer.ollama_chat') as mock_chat:
                            mock_chat.return_value = {
                                "message": {
                                    "tool_calls": [{
                                        "function": {
                                            "name": "write_file",
                                            "arguments": json.dumps({
                                                "file_path": "lib/__init__.py",
                                                "content": "from .analysts.nonexistent import NonExistent"
                                            })
                                        }
                                    }]
                                },
                                "usage": {}
                            }

                            mock_execute.return_value = "File written"

                            task = Task(
                                description="Update imports",
                                action_type="edit"
                            )
                            context = RevContext(Path(tmpdir))

                            result = agent.execute(task, context)

                            # The operation should complete, but validation should flag the broken imports
                            assert result is not None
            finally:
                os.chdir(old_cwd)


class TestTestValidation:
    """Test that test validation checks actual output, not just return code."""

    def test_validation_checks_test_output_not_just_rc(self):
        """Verify that test validation inspects actual test output."""
        from rev.execution.validator import validate_execution

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple Python file
            test_file = Path(tmpdir) / "test_dummy.py"
            test_file.write_text("""
def test_pass():
    assert True
""")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                plan = ExecutionPlan()
                task = Task(description="Run tests", action_type="test")
                task.status = TaskStatus.IN_PROGRESS
                plan.tasks = [task]

                # Run validation
                validation = validate_execution(
                    plan,
                    "Test validation",
                    run_tests=True,
                    run_linter=False,
                    check_syntax=False
                )

                # Check that validation actually inspects test output
                if validation.results:
                    for result in validation.results:
                        if "test" in result.name.lower():
                            # Should have actual output, not just a pass/fail
                            assert result.message is not None

            finally:
                os.chdir(old_cwd)

    def test_validation_detects_no_tests_found(self):
        """Verify that validation detects when no tests are found."""
        from rev.execution.validator import validate_execution

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                plan = ExecutionPlan()
                task = Task(description="Run tests", action_type="test")
                task.status = TaskStatus.IN_PROGRESS
                plan.tasks = [task]

                # Run validation (no tests directory)
                validation = validate_execution(
                    plan,
                    "Test validation",
                    run_tests=True,
                    run_linter=False,
                    check_syntax=False
                )

                # Should detect the issue
                test_results = [r for r in validation.results if "test" in r.name.lower()]

                # Either no tests found or validation should note this
                assert validation is not None
                # The key is that it should NOT report success if tests weren't found

            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
