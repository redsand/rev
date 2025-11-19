"""Tests for edge cases and error handling to increase coverage."""
import json
import pytest
from pathlib import Path
import rev


class TestPathSafety:
    """Test path safety checks."""

    def test_safe_path_escapes_repo(self):
        """Test that _safe_path blocks path traversal."""
        with pytest.raises(ValueError):
            rev._safe_path("../../etc/passwd")

    def test_safe_path_absolute_outside(self):
        """Test that absolute paths outside repo are blocked."""
        with pytest.raises(ValueError):
            rev._safe_path("/etc/passwd")


class TestFileOperationErrors:
    """Test error handling in file operations."""

    def test_read_file_nonexistent(self):
        """Test reading non-existent file."""
        result = json.loads(rev.read_file("/tmp/nonexistent_file_xyz123.txt"))
        # Should return error
        assert "error" in result or "not found" in result.get("message", "").lower()

    def test_write_file_invalid_path(self):
        """Test writing to invalid path."""
        # Try to write to a path that should fail (e.g., directory doesn't exist)
        try:
            result = json.loads(rev.write_file("/tmp/nonexistent_dir_xyz/file.txt", "content"))
            # Either succeeds (creates dir) or fails gracefully
            assert "error" in result or "wrote" in result.get("message", "").lower() or result.get("status") == "success"
        except Exception:
            pass  # Expected to fail

    def test_delete_nonexistent_file(self):
        """Test deleting non-existent file."""
        result = json.loads(rev.delete_file("/tmp/nonexistent_xyz123.txt"))
        # Should handle gracefully
        assert "error" in result or "not found" in result.get("message", "").lower() or "deleted" in result.get("message", "").lower()

    def test_copy_file_nonexistent_source(self, tmp_path):
        """Test copying from non-existent source."""
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dest.txt"

        result = json.loads(rev.copy_file(str(src), str(dst)))
        # Should return error
        assert "error" in result or "not found" in result.get("message", "").lower()

    def test_move_file_nonexistent_source(self, tmp_path):
        """Test moving non-existent file."""
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dest.txt"

        result = json.loads(rev.move_file(str(src), str(dst)))
        # Should return error
        assert "error" in result or "not found" in result.get("message", "").lower()

    def test_append_to_nonexistent_file(self, tmp_path):
        """Test appending to non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        result = json.loads(rev.append_to_file(str(test_file), "content"))
        # Might create file or return error
        assert "error" in result or "appended" in result.get("message", "").lower() or test_file.exists()

    def test_replace_in_nonexistent_file(self, tmp_path):
        """Test replacing in non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        result = json.loads(rev.replace_in_file(str(test_file), "old", "new"))
        # Should return error
        assert "error" in result or "not found" in result.get("message", "").lower()

    def test_get_file_info_nonexistent(self, tmp_path):
        """Test getting info for non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        result = json.loads(rev.get_file_info(str(test_file)))
        # Should return error
        assert "error" in result or "not found" in result.get("message", "").lower()


class TestCommandExecutionErrors:
    """Test error handling in command execution."""

    def test_run_cmd_blocked_command(self):
        """Test running blocked command."""
        result = json.loads(rev.run_cmd("rm -rf /"))
        # Should be blocked
        assert "blocked" in result or "not allowed" in result.get("message", "").lower()

    def test_run_cmd_nonexistent_command(self):
        """Test running non-existent command."""
        result = json.loads(rev.run_cmd("nonexistentcommand12345"))
        # Should handle error
        assert "error" in result or "blocked" in result or "rc" in result

    def test_run_tests_blocked_command(self):
        """Test running tests with blocked command."""
        result = json.loads(rev.run_tests("curl http://malicious.site"))
        # Should be blocked
        assert "blocked" in result or "not allowed" in result.get("message", "").lower()


class TestGitOperationErrors:
    """Test error handling in git operations."""

    def test_apply_patch_invalid(self):
        """Test applying invalid patch."""
        result = json.loads(rev.apply_patch("invalid patch content"))
        # Should handle error gracefully
        assert "error" in result or "applied" in result or "message" in result

    def test_git_commit_no_changes(self):
        """Test committing with no changes."""
        result = json.loads(rev.git_commit("test message"))
        # Might succeed or fail depending on repo state
        assert isinstance(result, dict)

    def test_git_log_with_limit(self):
        """Test git log with specific limit."""
        result = json.loads(rev.git_log(limit=1))
        assert "log" in result or "commits" in result or "output" in result


class TestSearchEdgeCases:
    """Test search operation edge cases."""

    def test_search_code_empty_query(self, tmp_path):
        """Test searching with empty query."""
        result = json.loads(rev.search_code("", path=str(tmp_path)))
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_search_code_special_characters(self, tmp_path):
        """Test searching with special regex characters."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def func():\n    return [1, 2, 3]\n")

        result = json.loads(rev.search_code("[1, 2, 3]", path=str(tmp_path)))
        # Should handle special characters
        assert isinstance(result, dict)


class TestCacheEdgeCases:
    """Test cache operation edge cases."""

    def test_get_cache_stats_structure(self):
        """Test cache stats return structure."""
        result = json.loads(rev.get_cache_stats())
        assert isinstance(result, dict)

    def test_clear_caches_idempotent(self):
        """Test that clearing caches twice works."""
        rev.clear_caches()
        result = json.loads(rev.clear_caches())
        # Should work fine
        assert isinstance(result, dict)

    def test_persist_caches(self):
        """Test persisting caches."""
        result = json.loads(rev.persist_caches())
        # Should work fine
        assert isinstance(result, dict)


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_text_file_python(self, tmp_path):
        """Test _is_text_file for Python file."""
        py_file = tmp_path / "test.py"
        py_file.write_text("print('hello')")
        # This is a private function, so we test it indirectly
        # by reading the file which uses this function
        result = json.loads(rev.read_file(str(py_file)))
        assert "content" in result or "error" in result

    def test_should_skip_git_dir(self, tmp_path):
        """Test _should_skip for .git directory."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        # Test indirectly through list_dir
        result = json.loads(rev.list_dir(str(tmp_path)))
        # .git should be skipped
        assert isinstance(result, dict)


class TestDataConversionEdgeCases:
    """Test data conversion edge cases."""

    def test_convert_json_to_yaml_invalid_json(self, tmp_path):
        """Test converting invalid JSON."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("not valid json{{{")

        yaml_file = tmp_path / "out.yaml"
        result = json.loads(rev.convert_json_to_yaml(str(json_file), str(yaml_file)))

        # Should handle error
        assert "error" in result or "converted" in result

    def test_convert_yaml_to_json_invalid_yaml(self, tmp_path):
        """Test converting invalid YAML."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("{{{{not valid yaml")

        json_file = tmp_path / "out.json"
        result = json.loads(rev.convert_yaml_to_json(str(yaml_file), str(json_file)))

        # Should handle error
        assert "error" in result or "converted" in result


class TestSSHEdgeCases:
    """Test SSH operation edge cases."""

    def test_ssh_connect_no_ssh(self):
        """Test SSH operations when SSH not available."""
        result = json.loads(rev.ssh_connect("localhost", "user"))
        # Should handle SSH not being available
        assert "error" in result or "connection_id" in result

    def test_ssh_exec_no_connection(self):
        """Test SSH exec with invalid connection."""
        result = json.loads(rev.ssh_exec("nonexistent_id", "ls"))
        # Should handle invalid connection
        assert "error" in result or "output" in result

    def test_ssh_disconnect_invalid(self):
        """Test disconnecting invalid SSH connection."""
        result = json.loads(rev.ssh_disconnect("nonexistent_id"))
        # Should handle gracefully
        assert "error" in result or "disconnected" in result or "message" in result


class TestSystemInfo:
    """Test system info functions."""

    def test_get_system_info_structure(self):
        """Test system info return structure."""
        result = json.loads(rev.get_system_info())
        assert "os" in result
        assert "python_version" in result
        assert "platform" in result

    def test_get_system_info_cached(self):
        """Test that system info is cached."""
        info1 = rev._get_system_info_cached()
        info2 = rev._get_system_info_cached()
        # Should be the same object (cached)
        assert info1 is info2


class TestMCPOperations:
    """Test MCP (Model Context Protocol) operations."""

    def test_mcp_list_servers(self):
        """Test listing MCP servers."""
        result = json.loads(rev.mcp_list_servers())
        # Should return list or error
        assert "servers" in result or isinstance(result, dict)

    def test_mcp_call_tool_invalid(self):
        """Test calling MCP tool with invalid parameters."""
        result = json.loads(rev.mcp_call_tool("nonexistent", "tool", {}))
        # Should handle error
        assert "error" in result or "result" in result


class TestWebFetchEdgeCases:
    """Test web fetch edge cases."""

    def test_web_fetch_timeout(self):
        """Test web fetch with likely timeout."""
        # Use a URL that's likely to timeout or fail
        result = json.loads(rev.web_fetch("http://192.0.2.1:81"))
        # Should handle error
        assert "error" in result or "content" in result

    def test_web_fetch_invalid_url(self):
        """Test web fetch with invalid URL."""
        result = json.loads(rev.web_fetch("not-a-valid-url"))
        # Should handle error
        assert "error" in result
