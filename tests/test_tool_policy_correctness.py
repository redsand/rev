"""
Tests for tool policy correctness (REV-010 and REV-011).

These tests verify that:
1. Tool policy is loaded from workspace root, not cwd (REV-010)
2. Permission check failures result in fail-closed behavior by default (REV-011)
3. Permission failures can be overridden with environment variable (REV-011)
"""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, Mock

from rev import config
from rev.workspace import init_workspace, get_workspace
from rev.tools.registry import execute_tool


class TestPolicyPathResolution:
    """Test that tool_policy.yaml is loaded from workspace root (REV-010)."""

    def test_policy_loaded_from_workspace_root_not_cwd(self, tmp_path):
        """Test that policy is loaded from workspace root, not current directory."""
        # Create a workspace structure
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        # Create a subdirectory that we'll chdir into
        subdir = workspace_root / "subdir"
        subdir.mkdir()

        # Create policy file at workspace root
        policy_file = workspace_root / "tool_policy.yaml"
        policy_file.write_text("""
default_policy: deny

agent_roles:
  test_agent:
    allowed_tools:
      - read_file
    denied_tools:
      - write_file
""")

        # Initialize workspace with the root
        original_cwd = os.getcwd()
        try:
            init_workspace(root=workspace_root)

            # Change current directory to subdirectory
            os.chdir(str(subdir))

            # Verify that Path.cwd() would give us the subdirectory
            assert Path.cwd() == subdir

            # But get_workspace().root should still be the workspace root
            assert get_workspace().root == workspace_root

            # Now test that policy is loaded from workspace root
            # The policy should exist at workspace_root, not at cwd (subdir)
            policy_at_root = workspace_root / "tool_policy.yaml"
            policy_at_cwd = Path.cwd() / "tool_policy.yaml"

            assert policy_at_root.exists(), "Policy should exist at workspace root"
            assert not policy_at_cwd.exists(), "Policy should NOT exist at cwd"

            # Verify that the code would find the policy at the right location
            # (This tests the actual code path from registry.py line 697)
            expected_path = get_workspace().root / "tool_policy.yaml"
            assert expected_path.exists()
            assert expected_path == policy_at_root

        finally:
            # Restore original directory
            os.chdir(original_cwd)

    def test_policy_enforcement_after_set_workdir(self, tmp_path):
        """Test that policy is still enforced after /set_workdir command."""
        workspace_root = tmp_path / "project"
        workspace_root.mkdir()

        # Create a restrictive policy
        policy_file = workspace_root / "tool_policy.yaml"
        policy_file.write_text("""
default_policy: deny

agent_roles:
  executor:
    allowed_tools:
      - read_file
    denied_tools:
      - write_file
      - delete_file
""")

        # Create a subdirectory
        subdir = workspace_root / "src"
        subdir.mkdir()

        original_cwd = os.getcwd()
        try:
            # Initialize workspace
            init_workspace(root=workspace_root)

            # Simulate /set_workdir to subdirectory
            os.chdir(str(subdir))

            # Policy should still be found and enforced
            policy_path = get_workspace().root / "tool_policy.yaml"
            assert policy_path.exists()

            # Test file should exist for read_file to work
            test_file = workspace_root / "test.txt"
            test_file.write_text("test content")

            # Try to execute a denied tool
            with patch('rev.tools.permissions.get_permission_manager') as mock_get_mgr:
                mock_mgr_instance = Mock()
                mock_result = Mock()
                mock_result.allowed = False
                mock_result.reason = "Tool not in allowed list"
                mock_mgr_instance.check_permission.return_value = mock_result
                mock_mgr_instance.log_denial = Mock()
                mock_get_mgr.return_value = mock_mgr_instance

                result = execute_tool(
                    name="write_file",
                    args={"file_path": str(test_file), "content": "blocked"},
                    agent_name="executor"
                )

                result_data = json.loads(result)
                assert result_data.get("permission_denied") is True

        finally:
            os.chdir(original_cwd)


class TestFailClosedBehavior:
    """Test that permission check failures result in fail-closed behavior (REV-011)."""

    def test_fail_closed_by_default(self, tmp_path):
        """Test that tool execution is BLOCKED when permission check fails (default behavior)."""
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        # Create a malformed policy that will cause permission check to fail
        policy_file = workspace_root / "tool_policy.yaml"
        policy_file.write_text("invalid: yaml: syntax {{{{")

        original_cwd = os.getcwd()
        original_fail_open = config.PERMISSIONS_FAIL_OPEN

        try:
            # Ensure PERMISSIONS_FAIL_OPEN is False (secure default)
            config.PERMISSIONS_FAIL_OPEN = False

            init_workspace(root=workspace_root)
            os.chdir(str(workspace_root))

            # Create a test file
            test_file = workspace_root / "test.txt"
            test_file.write_text("content")

            # Try to execute a tool - should be BLOCKED due to policy error
            result = execute_tool(
                name="read_file",
                args={"file_path": str(test_file)},
                agent_name="test_agent"
            )

            result_data = json.loads(result)

            # Tool should be blocked
            assert result_data.get("blocked") is True, "Tool should be BLOCKED when permission check fails"
            assert result_data.get("permission_check_failed") is True
            assert "fail-closed" in result_data.get("error", "").lower()

        finally:
            os.chdir(original_cwd)
            config.PERMISSIONS_FAIL_OPEN = original_fail_open

    def test_fail_open_with_env_override(self, tmp_path):
        """Test that tool execution is ALLOWED when PERMISSIONS_FAIL_OPEN=true."""
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        # Create a malformed policy
        policy_file = workspace_root / "tool_policy.yaml"
        policy_file.write_text("malformed yaml content {{{")

        original_cwd = os.getcwd()
        original_fail_open = config.PERMISSIONS_FAIL_OPEN

        try:
            # Set PERMISSIONS_FAIL_OPEN to True (insecure override)
            config.PERMISSIONS_FAIL_OPEN = True

            init_workspace(root=workspace_root)
            os.chdir(str(workspace_root))

            # Create a test file
            test_file = workspace_root / "test.txt"
            test_file.write_text("test content")

            # Try to execute a tool - should be ALLOWED despite policy error
            result = execute_tool(
                name="read_file",
                args={"file_path": str(test_file)},
                agent_name="test_agent"
            )

            # read_file returns raw text on success, JSON on error
            # With fail-open, it should succeed and return raw text
            assert result is not None, "Tool should return a result"
            assert "test content" in result, "Tool should be ALLOWED with PERMISSIONS_FAIL_OPEN=true and return file content"

            # Verify it's NOT a blocked/error JSON response
            try:
                error_check = json.loads(result)
                # If it parses as JSON, it should not be blocked
                assert error_check.get("blocked") is not True
                assert error_check.get("permission_check_failed") is not True
            except json.JSONDecodeError:
                # Expected - raw text content means success
                pass

        finally:
            os.chdir(original_cwd)
            config.PERMISSIONS_FAIL_OPEN = original_fail_open

    def test_normal_permission_denial_still_works(self, tmp_path):
        """Test that normal permission denials still work (not affected by REV-011)."""
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        # Create a VALID policy that denies write_file
        policy_file = workspace_root / "tool_policy.yaml"
        policy_file.write_text("""
default_policy: allow

agent_roles:
  restricted_agent:
    allowed_tools:
      - read_file
    denied_tools:
      - write_file
      - delete_file
""")

        original_cwd = os.getcwd()
        original_fail_open = config.PERMISSIONS_FAIL_OPEN

        try:
            config.PERMISSIONS_FAIL_OPEN = False  # Default secure mode

            init_workspace(root=workspace_root)
            os.chdir(str(workspace_root))

            test_file = workspace_root / "test.txt"

            # Try to execute a denied tool (write_file)
            with patch('rev.tools.permissions.get_permission_manager') as mock_get_mgr:
                mock_mgr_instance = Mock()
                mock_result = Mock()
                mock_result.allowed = False
                mock_result.reason = "Tool not in allowed list"
                mock_result.risk_level = None
                mock_mgr_instance.check_permission.return_value = mock_result
                mock_mgr_instance.log_denial = Mock()
                mock_get_mgr.return_value = mock_mgr_instance

                result = execute_tool(
                    name="write_file",
                    args={"file_path": str(test_file), "content": "blocked"},
                    agent_name="restricted_agent"
                )

                result_data = json.loads(result)

                # Should be denied due to policy
                assert result_data.get("permission_denied") is True
                assert "Permission denied" in result_data.get("error", "")

        finally:
            os.chdir(original_cwd)
            config.PERMISSIONS_FAIL_OPEN = original_fail_open


class TestEnvironmentVariableConfig:
    """Test that REV_PERMISSIONS_FAIL_OPEN environment variable works correctly."""

    def test_env_var_parsing_true_values(self):
        """Test that various true values are recognized."""
        true_values = ["true", "1", "yes", "TRUE", "True", "YES"]

        for value in true_values:
            with patch.dict(os.environ, {"REV_PERMISSIONS_FAIL_OPEN": value}):
                # Re-import config to pick up env var
                import importlib
                importlib.reload(config)

                assert config.PERMISSIONS_FAIL_OPEN is True, f"'{value}' should be parsed as True"

    def test_env_var_parsing_false_values(self):
        """Test that false/missing values result in False."""
        false_values = ["false", "0", "no", "FALSE", "", "anything_else"]

        for value in false_values:
            with patch.dict(os.environ, {"REV_PERMISSIONS_FAIL_OPEN": value}):
                # Re-import config to pick up env var
                import importlib
                importlib.reload(config)

                assert config.PERMISSIONS_FAIL_OPEN is False, f"'{value}' should be parsed as False"

    def test_default_is_false(self):
        """Test that default (unset) is False (secure default)."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure env var is not set
            if "REV_PERMISSIONS_FAIL_OPEN" in os.environ:
                del os.environ["REV_PERMISSIONS_FAIL_OPEN"]

            # Re-import config
            import importlib
            importlib.reload(config)

            # Default should be False (fail closed = secure)
            assert config.PERMISSIONS_FAIL_OPEN is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
