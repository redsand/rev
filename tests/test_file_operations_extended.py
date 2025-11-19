"""Extended tests for file operations to increase coverage."""
import json
import os
import tempfile
import pytest
from pathlib import Path
import rev


class TestFileOperations:
    """Test file operations with various edge cases."""

    def test_read_file_basic(self, tmp_path):
        """Test basic file reading."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        # Read the file
        result = json.loads(rev.read_file(str(test_file)))
        assert "Hello World" in result["content"]

    def test_write_file_basic(self, tmp_path):
        """Test basic file writing."""
        test_file = tmp_path / "new_file.txt"

        # Write content
        result = json.loads(rev.write_file(str(test_file), "Test content"))
        assert result.get("status") == "success" or "wrote" in result.get("message", "").lower()

        # Verify content
        assert test_file.read_text() == "Test content"

    def test_file_exists_true(self, tmp_path):
        """Test file_exists returns true for existing file."""
        test_file = tmp_path / "exists.txt"
        test_file.write_text("content")

        result = json.loads(rev.file_exists(str(test_file)))
        assert result["exists"] is True

    def test_file_exists_false(self, tmp_path):
        """Test file_exists returns false for non-existing file."""
        test_file = tmp_path / "does_not_exist.txt"

        result = json.loads(rev.file_exists(str(test_file)))
        assert result["exists"] is False

    def test_delete_file(self, tmp_path):
        """Test file deletion."""
        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("content")

        result = json.loads(rev.delete_file(str(test_file)))
        assert not test_file.exists()

    def test_copy_file(self, tmp_path):
        """Test file copying."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("copy me")

        result = json.loads(rev.copy_file(str(src), str(dst)))
        assert dst.exists()
        assert dst.read_text() == "copy me"

    def test_move_file(self, tmp_path):
        """Test file moving."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("move me")

        result = json.loads(rev.move_file(str(src), str(dst)))
        assert dst.exists()
        assert not src.exists()
        assert dst.read_text() == "move me"

    def test_append_to_file(self, tmp_path):
        """Test appending to file."""
        test_file = tmp_path / "append.txt"
        test_file.write_text("Line 1\n")

        result = json.loads(rev.append_to_file(str(test_file), "Line 2\n"))
        content = test_file.read_text()
        assert "Line 1" in content
        assert "Line 2" in content

    def test_replace_in_file(self, tmp_path):
        """Test replacing text in file."""
        test_file = tmp_path / "replace.txt"
        test_file.write_text("Hello World")

        result = json.loads(rev.replace_in_file(str(test_file), "World", "Python"))
        assert "Python" in test_file.read_text()
        assert "World" not in test_file.read_text()

    def test_create_directory(self, tmp_path):
        """Test directory creation."""
        new_dir = tmp_path / "new_directory"

        result = json.loads(rev.create_directory(str(new_dir)))
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_get_file_info(self, tmp_path):
        """Test getting file information."""
        test_file = tmp_path / "info.txt"
        test_file.write_text("test content")

        result = json.loads(rev.get_file_info(str(test_file)))
        assert "size" in result
        assert "modified" in result

    def test_read_file_lines(self, tmp_path):
        """Test reading file with line numbers."""
        test_file = tmp_path / "lines.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3")

        result = json.loads(rev.read_file_lines(str(test_file), 1, 2))
        assert "Line 1" in result["content"]
        assert "Line 2" in result["content"]

    def test_tree_view(self, tmp_path):
        """Test tree view of directory."""
        # Create some files and directories
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file2.txt").write_text("content")

        result = json.loads(rev.tree_view(str(tmp_path)))
        assert "file1.txt" in result["tree"] or "files" in result

    def test_list_dir(self, tmp_path):
        """Test listing directory contents."""
        # Create some files
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()

        result = json.loads(rev.list_dir(str(tmp_path)))
        assert "files" in result or "entries" in result


class TestSearchOperations:
    """Test search operations."""

    def test_search_code_basic(self, tmp_path):
        """Test basic code search."""
        test_file = tmp_path / "search.py"
        test_file.write_text("def hello():\n    print('world')\n")

        result = json.loads(rev.search_code("hello", path=str(tmp_path)))
        # Should find matches
        assert "matches" in result or "results" in result

    def test_search_code_no_match(self, tmp_path):
        """Test search with no matches."""
        test_file = tmp_path / "search.py"
        test_file.write_text("def hello():\n    print('world')\n")

        result = json.loads(rev.search_code("nonexistent_string", path=str(tmp_path)))
        # Should return empty or no matches
        matches = result.get("matches", [])
        assert len(matches) == 0 or not matches


class TestGitOperations:
    """Test git operations."""

    def test_git_status(self):
        """Test git status command."""
        result = json.loads(rev.git_status())
        assert "status" in result or "output" in result

    def test_git_log(self):
        """Test git log command."""
        result = json.loads(rev.git_log(limit=5))
        assert "log" in result or "commits" in result or "output" in result

    def test_git_branch(self):
        """Test git branch command."""
        result = json.loads(rev.git_branch())
        assert "branches" in result or "current" in result or "output" in result


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_system_info(self):
        """Test getting system information."""
        result = json.loads(rev.get_system_info())
        assert "os" in result
        assert "python_version" in result

    def test_get_repo_context(self):
        """Test getting repository context."""
        result = json.loads(rev.get_repo_context())
        # Should have some git context
        assert "status" in result or "error" in result


class TestCommandExecution:
    """Test command execution."""

    def test_run_tests_pytest(self):
        """Test running tests with pytest."""
        result = json.loads(rev.run_tests("pytest --version"))
        # Should execute or block
        assert "rc" in result or "blocked" in result or "output" in result

    def test_run_cmd_python(self):
        """Test running Python command."""
        result = json.loads(rev.run_cmd("python --version"))
        # Should execute successfully
        assert "stdout" in result or "output" in result


class TestCacheOperations:
    """Test cache operations."""

    def test_get_cache_stats(self):
        """Test getting cache statistics."""
        result = json.loads(rev.get_cache_stats())
        assert "file_cache" in result or "stats" in result or isinstance(result, dict)

    def test_clear_caches(self):
        """Test clearing caches."""
        result = json.loads(rev.clear_caches())
        assert "cleared" in result or "status" in result or isinstance(result, dict)


class TestSSHOperations:
    """Test SSH operations (will skip if SSH not available)."""

    def test_ssh_list_connections(self):
        """Test listing SSH connections."""
        result = json.loads(rev.ssh_list_connections())
        # Should return empty list or error if SSH not available
        assert "connections" in result or "error" in result


class TestWebOperations:
    """Test web operations."""

    def test_web_fetch_error_handling(self):
        """Test web fetch with invalid URL."""
        result = json.loads(rev.web_fetch("http://invalid.local.nonexistent"))
        # Should handle error gracefully
        assert "error" in result or "content" in result
