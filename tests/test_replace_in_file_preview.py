"""
Test to verify that replace_in_file preview displays correct diff.

ISSUE: replace_in_file was showing "(No changes)" with 0 → 0 lines
ROOT CAUSE: Parameter mismatch - code looked for "old_string"/"new_string"
           but tool defines "find"/"replace"
FIX: Changed arguments.get("old_string") to arguments.get("find")
"""

import io
from unittest.mock import patch, MagicMock
import pytest

from rev.agents.code_writer import CodeWriterAgent
from rev.core.context import RevContext


class TestReplaceInFilePreview:
    """Test suite for replace_in_file preview display."""

    def setup_method(self):
        """Set up test fixtures."""
        self.agent = CodeWriterAgent()

    def capture_print_output(self, func):
        """Capture print output and return it."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            func()
        return captured_output.getvalue()

    def test_replace_in_file_displays_diff(self):
        """
        Test that replace_in_file shows actual diff between find and replace text.

        ISSUE: Was showing "(No changes)" because looking for wrong parameter names
        """
        # Simulate LLM tool call arguments for replace_in_file
        # Note: Tool uses "find" and "replace" (not "old_string" and "new_string")
        arguments = {
            "path": "lib/utils.py",
            "find": "def old_function():\n    return 42",
            "replace": "def new_function():\n    return 100"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Should show the file
        assert "lib/utils.py" in output, f"File path not shown. Got:\n{output}"

        # Should show diff markers
        assert "--- Original Content" in output or "---" in output, \
            f"Diff markers not shown. Got:\n{output}"

        # Should NOT show "(No changes)"
        assert "(No changes)" not in output, \
            f"ERROR: Still showing '(No changes)'. Fix didn't work. Got:\n{output}"

        # Should show line changes (not 0 → 0)
        assert "2 → 2 lines" in output or "Changes:" in output, \
            f"Change count not shown. Got:\n{output}"

    def test_replace_in_file_shows_actual_content_diff(self):
        """Test that the actual text differences are displayed."""
        arguments = {
            "path": "config.py",
            "find": "DEBUG = True\nLOG_LEVEL = 'info'",
            "replace": "DEBUG = False\nLOG_LEVEL = 'warning'"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Verify the old content would be shown (in diff context)
        assert "DEBUG = True" in output or "True" in output, \
            f"Old content not visible in diff. Got:\n{output}"

        # Verify the new content would be shown (in diff context)
        assert "DEBUG = False" in output or "False" in output, \
            f"New content not visible in diff. Got:\n{output}"

    def test_replace_in_file_with_multiline_change(self):
        """Test replace_in_file with realistic multi-line changes."""
        arguments = {
            "path": "src/main.py",
            "find": "def authenticate(username, password):\n    # TODO: implement\n    pass",
            "replace": "def authenticate(username, password):\n    \"\"\"Authenticate user against database.\"\"\"\n    user = db.query(username)\n    if user and verify_password(user, password):\n        return True\n    return False"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Should show it's a multi-line change
        assert "3 → 5 lines" in output or "Changes:" in output, \
            f"Line counts not correct. Got:\n{output}"

        # Should not say "(No changes)"
        assert "(No changes)" not in output, \
            f"Incorrectly showing no changes for multi-line replacement. Got:\n{output}"

    def test_replace_in_file_parameter_consistency(self):
        """
        CRITICAL: Verify parameter names match tool definition.

        Tool defines: find, replace
        Code must use: arguments.get("find"), arguments.get("replace")
        """
        # Simulate actual tool call from LLM (uses "find" and "replace")
        arguments = {
            "path": "test.py",
            "find": "old",
            "replace": "new"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Most important: not empty
        assert output.strip(), "Preview output is empty!"

        # Should show change
        assert "(No changes)" not in output, \
            "ERROR: Parameter names still wrong. Using wrong keys to get 'find' and 'replace'"

    def test_replace_in_file_empty_arguments_handled(self):
        """Test that empty arguments are handled gracefully."""
        arguments = {
            "path": "test.py",
            "find": "",
            "replace": ""
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # When find and replace are empty, (No changes) is correct
        assert "(No changes)" in output, \
            f"Empty changes should show '(No changes)'. Got:\n{output}"

        assert "0 → 0 lines" in output, \
            f"Empty changes should show '0 → 0 lines'. Got:\n{output}"

    def test_replace_in_file_one_liner_change(self):
        """Test single-line replacement."""
        arguments = {
            "path": "settings.py",
            "find": "TIMEOUT = 30",
            "replace": "TIMEOUT = 60"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Should show 1 line change
        assert "1 → 1 lines" in output, \
            f"Single line replacement not shown correctly. Got:\n{output}"

        # Should not show "(No changes)"
        assert "(No changes)" not in output, \
            f"Single line replacement showing as no change. Got:\n{output}"

    def test_replace_in_file_header_footer_present(self):
        """Test that preview has proper formatting."""
        arguments = {
            "path": "test.py",
            "find": "x = 1",
            "replace": "x = 2"
        }

        def display():
            self.agent._display_change_preview("replace_in_file", arguments)

        output = self.capture_print_output(display)

        # Should have header and footer
        assert "CODE CHANGE PREVIEW" in output, \
            f"Preview header missing. Got:\n{output}"

        assert "=" * 70 in output, \
            f"Footer separators missing. Got:\n{output}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
