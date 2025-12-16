"""
Test to verify that file paths are correctly displayed in CODE CHANGE PREVIEW.

This test addresses the issue where file paths were showing as "unknown"
instead of the actual path because the code was looking for "file_path" key
instead of "path" key in the arguments dictionary.

Issue: CODE CHANGE PREVIEW was printing:
  File: unknown

Expected: CODE CHANGE PREVIEW should print:
  File: lib/analysts/breakout_analyst.py
"""

import io
import sys
import json
from unittest.mock import patch, MagicMock
import pytest

from rev.agents.code_writer import CodeWriterAgent
from rev.core.context import RevContext
from rev.models.task import Task


class TestFilePathVisibility:
    """Test suite for file path visibility in CODE CHANGE PREVIEW."""

    def setup_method(self):
        """Set up test fixtures."""
        self.agent = CodeWriterAgent()
        self.context = MagicMock(spec=RevContext)

    def capture_print_output(self, func):
        """Capture print output and return it."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            func()
        return captured_output.getvalue()

    def test_write_file_displays_correct_path(self):
        """
        Test that write_file operations display the correct file path.

        ISSUE: Previously looked for "file_path" key instead of "path"
        EXPECTED: Should display the actual file path from arguments["path"]
        """
        # Simulate LLM tool call arguments for write_file
        arguments = {
            "path": "lib/analysts/breakout_analyst.py",  # Note: key is "path"
            "content": "class BreakoutAnalyst:\n    def analyze(self):\n        pass"
        }

        def display():
            self.agent._display_change_preview("write_file", arguments)

        output = self.capture_print_output(display)

        # CRITICAL ASSERTIONS: File path must be visible
        assert "FILE: lib/analysts/breakout_analyst.py" in output.upper() or \
               "File: lib/analysts/breakout_analyst.py" in output, \
               f"File path not found in output. Got:\n{output}"

        assert "unknown" not in output.lower(), \
               f"File path showing as 'unknown'. This means 'path' key was not found. Got:\n{output}"

        # Verify the action is CREATE
        assert "CREATE" in output, f"CREATE action not displayed. Got:\n{output}"

        # Verify preview is shown
        assert "Preview" in output or "content" in output.lower(), \
               f"File content preview not shown. Got:\n{output}"

    def test_replace_in_file_displays_correct_path(self):
        """
        Test that replace_in_file operations display the correct file path.

        ISSUE: Previously looked for "file_path" key instead of "path"
        EXPECTED: Should display the actual file path from arguments["path"]
        """
        arguments = {
            "path": "src/main.py",  # Note: key is "path"
            "old_string": "def old_function():\n    pass",
            "new_string": "def new_function():\n    return True"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # CRITICAL ASSERTIONS: File path must be visible
        assert "File: src/main.py" in output, \
               f"File path 'src/main.py' not found in output. Got:\n{output}"

        assert "unknown" not in output.lower(), \
               f"File path showing as 'unknown'. This means 'path' key was not found. Got:\n{output}"

        # Verify diff is shown
        assert "Original Content" in output or "New Content" in output, \
               f"Diff not displayed. Got:\n{output}"

    def test_preview_header_and_footer_present(self):
        """Test that CODE CHANGE PREVIEW header and footer are present."""
        arguments = {
            "path": "test.py",
            "content": "# Test file"
        }

        def display():
            self.agent._display_change_preview("write_file", arguments)

        output = self.capture_print_output(display)

        assert "CODE CHANGE PREVIEW" in output, \
               f"CODE CHANGE PREVIEW header missing. Got:\n{output}"

        assert "=" * 70 in output, \
               f"Separator lines missing. Got:\n{output}"

    def test_write_file_with_multiline_content(self):
        """Test write_file with realistic multi-line content."""
        arguments = {
            "path": "lib/analysts/volume_analyst.py",
            "content": "\n".join([
                "class VolumeAnalyst:",
                "    def __init__(self, data):",
                "        self.data = data",
                "    ",
                "    def analyze(self):",
                "        volumes = [item['volume'] for item in self.data]",
                "        return {",
                "            'avg': sum(volumes) / len(volumes),",
                "            'max': max(volumes),",
                "            'min': min(volumes)",
                "        }"
            ])
        }

        def display():
            self.agent._display_change_preview("write_file", arguments)

        output = self.capture_print_output(display)

        # File path should be visible
        assert "lib/analysts/volume_analyst.py" in output, \
               f"File path not found. Got:\n{output}"

        # Size information should be shown
        assert "lines" in output.lower(), \
               f"Size info not shown. Got:\n{output}"

        # No "unknown" should appear
        assert "unknown" not in output.lower(), \
               f"'unknown' found in output. Got:\n{output}"

    def test_replace_in_file_shows_line_changes(self):
        """Test that replace_in_file shows the number of line changes."""
        arguments = {
            "path": "config.py",
            "old_string": "DEBUG = True\nLOG_LEVEL = 'info'\nTIMEOUT = 30",
            "new_string": "DEBUG = False\nLOG_LEVEL = 'warning'\nTIMEOUT = 60\nMAX_RETRIES = 3"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # File path should be visible
        assert "config.py" in output, f"File path not found. Got:\n{output}"

        # Line count changes should be shown
        assert "Changes:" in output or "lines" in output.lower(), \
               f"Line changes not shown. Got:\n{output}"

        # No "unknown" should appear
        assert "unknown" not in output.lower(), \
               f"'unknown' found in output. Got:\n{output}"

    def test_deeply_nested_file_paths(self):
        """Test that deeply nested file paths are displayed correctly."""
        deep_paths = [
            "src/features/authentication/oauth2/providers/google.py",
            "tests/unit/auth/test_oauth2_google_provider.py",
            "lib/deeply/nested/module/path/analyst.py"
        ]

        for file_path in deep_paths:
            arguments = {
                "path": file_path,
                "content": "# Test content"
            }

            def display():
                self.agent._display_change_preview("write_file", arguments)

            output = self.capture_print_output(display)

            assert file_path in output, \
                   f"Nested path '{file_path}' not found. Got:\n{output}"

            assert "unknown" not in output.lower(), \
                   f"'unknown' found for path '{file_path}'. Got:\n{output}"

    def test_special_characters_in_file_paths(self):
        """Test file paths with special characters."""
        special_paths = [
            "src/my-module/file.py",
            "src/my_module/file.py",
            "src/MyModule/File.py",
            "src/module-v2/file_v2.py"
        ]

        for file_path in special_paths:
            arguments = {
                "path": file_path,
                "content": "# Test"
            }

            def display():
                self.agent._display_change_preview("write_file", arguments)

            output = self.capture_print_output(display)

            assert file_path in output, \
                   f"Path with special chars '{file_path}' not found. Got:\n{output}"

    def test_no_unknown_in_any_preview_output(self):
        """
        CRITICAL TEST: Ensure "unknown" never appears in ANY preview output.

        This test would have caught the original bug.
        """
        test_cases = [
            ("write_file", {"path": "file1.py", "content": "content1"}),
            ("write_file", {"path": "nested/file2.py", "content": "content2"}),
            ("replace_in_file", {"path": "file3.py", "old_string": "old", "new_string": "new"}),
            ("replace_in_file", {"path": "deep/nested/file4.py", "old_string": "x", "new_string": "y"}),
        ]

        for tool_name, arguments in test_cases:
            def display():
                self.agent._display_change_preview(tool_name, arguments)

            output = self.capture_print_output(display)

            assert "unknown" not in output.lower(), \
                   f"FAIL: 'unknown' found in {tool_name} preview. Arguments: {arguments}. Output:\n{output}"


class TestFilePathVisibilityIntegration:
    """Integration tests for file path visibility in full execution flow."""

    @patch('rev.agents.code_writer.ollama_chat')
    @patch('rev.agents.code_writer.execute_tool')
    @patch('builtins.input', return_value='y')  # Auto-approve changes
    def test_file_path_shown_during_approval_prompt(self, mock_input, mock_execute, mock_llm):
        """
        Test that file path is displayed correctly in the approval prompt.

        The approval prompt should show the actual file path, not "unknown".
        """
        # Setup mock LLM response with a tool call
        mock_llm.return_value = {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "write_file",
                            "arguments": {
                                "path": "lib/analysts/test_analyst.py",  # Correct key
                                "content": "class TestAnalyst:\n    pass"
                            }
                        }
                    }
                ]
            }
        }

        mock_execute.return_value = "[SUCCESS] File written"

        agent = CodeWriterAgent()
        context = MagicMock(spec=RevContext)
        context.repo_context = "Test repository context"
        context.add_error = MagicMock()

        task = MagicMock(spec=Task)
        task.description = "Create a test analyst"
        task.task_id = "test_task_001"

        # Capture all output
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            result = agent.execute(task, context)

        output = captured_output.getvalue()

        # The file path should be displayed clearly
        assert "lib/analysts/test_analyst.py" in output or \
               output.count("test_analyst.py") >= 1, \
               f"File path 'lib/analysts/test_analyst.py' not clearly displayed. Got:\n{output}"

        # Should NOT show "unknown"
        assert "unknown" not in output.lower(), \
               f"File path showing as 'unknown'. Got:\n{output}"

        # Should show approval prompt
        assert "APPROVAL REQUIRED" in output or "Apply this change" in output, \
               f"Approval prompt not shown. Got:\n{output}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
