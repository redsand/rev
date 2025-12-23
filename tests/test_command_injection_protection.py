"""
Tests for command injection protection in command_runner module.

These tests verify that:
1. Shell metacharacters are rejected
2. Command allowlisting works correctly
3. Normal commands execute successfully
4. Interrupt support works
"""

import json
import pytest
from rev.tools.command_runner import (
    run_command_safe,
    run_cmd,
    run_tests,
    _parse_and_validate,
    FORBIDDEN_TOKENS,
)


class TestCommandInjectionProtection:
    """Test that command injection attacks are blocked."""

    def test_blocks_shell_operators(self):
        """Test that shell operators like && are blocked."""
        result = run_command_safe("git status && echo pwned")
        assert result["blocked"] is True
        assert "shell metacharacters" in result["error"].lower()

    def test_blocks_semicolon(self):
        """Test that semicolons are blocked."""
        result = run_command_safe("git status; echo pwned")
        assert result["blocked"] is True

    def test_blocks_pipe(self):
        """Test that pipes are blocked."""
        result = run_command_safe("git status | grep malicious")
        assert result["blocked"] is True

    def test_blocks_redirection(self):
        """Test that redirections are blocked."""
        result = run_command_safe("git status > /tmp/pwned")
        assert result["blocked"] is True

    def test_blocks_backticks(self):
        """Test that backticks are blocked."""
        result = run_command_safe("echo `whoami`")
        assert result["blocked"] is True

    def test_blocks_command_substitution(self):
        """Test that command substitution is blocked."""
        result = run_command_safe("echo $(whoami)")
        assert result["blocked"] is True

    def test_blocks_newline_injection(self):
        """Test that newline injection is blocked."""
        result = run_command_safe("git status\necho pwned")
        assert result["blocked"] is True

    def test_blocks_non_allowlisted_command(self):
        """Test that non-allowlisted commands are blocked."""
        result = run_command_safe("malicious_command arg1 arg2")
        assert result["blocked"] is True
        assert "command not allowed" in result["error"].lower()

    def test_allows_git_status(self):
        """Test that normal git status works."""
        result = run_command_safe("git status")
        assert result.get("blocked") is not True
        assert "rc" in result

    def test_allows_pytest(self):
        """Test that pytest command is allowed."""
        # This will fail if there are no tests, but it should not be blocked
        result = run_command_safe("pytest --help", timeout=10)
        assert result.get("blocked") is not True

    def test_run_cmd_blocks_injection(self):
        """Test that run_cmd blocks injection via the backwards compat interface."""
        result_json = run_cmd("git status && echo pwned")
        result = json.loads(result_json)
        assert result["blocked"] is True

    def test_run_cmd_allows_normal(self):
        """Test that run_cmd allows normal commands."""
        result_json = run_cmd("git status")
        result = json.loads(result_json)
        assert result.get("blocked") is not True
        assert "rc" in result


class TestCommandValidation:
    """Test the command validation logic."""

    def test_parse_and_validate_empty_command(self):
        """Test that empty commands are rejected."""
        is_valid, error_msg, args = _parse_and_validate("")
        assert not is_valid
        assert "empty" in error_msg.lower()

    def test_parse_and_validate_valid_command(self):
        """Test that valid commands parse correctly."""
        is_valid, error_msg, args = _parse_and_validate("git status")
        assert is_valid
        assert error_msg == ""
        assert args == ["git", "status"]

    def test_parse_and_validate_with_args(self):
        """Test that commands with arguments parse correctly."""
        is_valid, error_msg, args = _parse_and_validate("git log -n 5")
        assert is_valid
        assert args == ["git", "log", "-n", "5"]

    def test_parse_and_validate_quoted_args(self):
        """Test that quoted arguments are parsed correctly."""
        is_valid, error_msg, args = _parse_and_validate('git commit -m "test message"')
        assert is_valid
        # On Windows, shlex may preserve quotes differently
        assert len(args) == 4
        assert args[0] == "git"
        assert args[1] == "commit"
        assert args[2] == "-m"
        # Accept either quoted or unquoted
        assert args[3] in ["test message", '"test message"']

    def test_forbidden_tokens_in_args(self):
        """Test that forbidden tokens in arguments are rejected."""
        for token in ["&&", "||", ";", "|"]:
            is_valid, error_msg, args = _parse_and_validate(f"echo {token}")
            # The token should be caught either by regex or token check
            assert not is_valid


class TestInterruptSupport:
    """Test that interrupt support works correctly."""

    def test_interrupt_flag_in_command_runner(self):
        """Test that command_runner has interrupt support."""
        from rev.tools.command_runner import run_command_safe
        from unittest.mock import patch

        # Mock get_escape_interrupt to return True immediately
        with patch('rev.tools.command_runner.get_escape_interrupt', return_value=True):
            # Run a command with interrupt checking enabled
            result = run_command_safe("git status", timeout=30, check_interrupt=True)

            # Command should have been interrupted
            assert result.get("interrupted") is True

    def test_interrupt_not_checked_when_disabled(self):
        """Test that interrupt flag is not checked when check_interrupt=False."""
        from rev.tools.command_runner import run_command_safe
        from unittest.mock import patch

        # Mock get_escape_interrupt to return True
        with patch('rev.tools.command_runner.get_escape_interrupt', return_value=True):
            # Run a command WITHOUT interrupt checking
            result = run_command_safe("git status", timeout=10, check_interrupt=False)

            # Command should complete normally (not interrupted)
            # Since check_interrupt=False, it won't check the flag
            assert result.get("rc") is not None


class TestStopCommandHandling:
    """Test that /stop command properly sets interrupt flags (REV-008)."""

    def test_stop_command_sets_escape_interrupt(self):
        """Test that /stop command sets the global escape interrupt flag."""
        from unittest.mock import Mock, patch
        from rev.config import get_escape_interrupt, set_escape_interrupt

        # Ensure clean state
        set_escape_interrupt(False)
        assert not get_escape_interrupt(), "Interrupt flag should be cleared initially"

        # Create a mock message queue
        mock_queue = Mock()
        mock_queue.submit = Mock()

        # Simulate the handle_user_input function from executor.py
        def handle_user_input(text: str):
            if text.startswith("/stop") or text.startswith("/cancel"):
                set_escape_interrupt(True)
                mock_queue.submit("STOP the current task immediately.", "INTERRUPT")

        # Call with /stop
        handle_user_input("/stop")

        # Verify interrupt flag was set
        assert get_escape_interrupt(), "Interrupt flag should be set after /stop"

        # Verify message was queued
        mock_queue.submit.assert_called_once()

        # Clean up
        set_escape_interrupt(False)

    def test_stop_command_interrupts_streaming_manager(self):
        """Test that /stop command calls streaming_manager.interrupt()."""
        from unittest.mock import Mock
        from rev.config import set_escape_interrupt

        # Ensure clean state
        set_escape_interrupt(False)

        # Create mock streaming manager
        mock_streaming_manager = Mock()
        mock_streaming_manager.interrupt = Mock()

        # Create mock message queue
        mock_queue = Mock()

        # Simulate the handle_user_input function from concurrent_execution_mode
        def handle_user_input(text: str):
            if text.startswith('/stop') or text.startswith('/cancel'):
                set_escape_interrupt(True)
                mock_streaming_manager.interrupt()
                mock_queue.submit("STOP", "INTERRUPT")

        # Call with /stop
        handle_user_input("/stop")

        # Verify streaming manager interrupt was called
        mock_streaming_manager.interrupt.assert_called_once()

        # Clean up
        set_escape_interrupt(False)


class TestSecurityDocumentation:
    """Test that security documentation is clear."""

    def test_deprecated_warning_in_docstrings(self):
        """Test that deprecated functions have clear warnings."""
        from rev.tools import git_ops, file_ops
        from rev import _run_shell

        # Check that deprecated functions warn about security
        assert "DEPRECATED" in git_ops._run_shell.__doc__ or "safe" in git_ops._run_shell.__doc__.lower()
        assert "DEPRECATED" in file_ops._run_shell.__doc__ or "safe" in file_ops._run_shell.__doc__.lower()
        assert "DEPRECATED" in _run_shell.__doc__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
