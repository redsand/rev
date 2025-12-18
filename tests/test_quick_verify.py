"""
Tests for the quick_verify module - verification of task execution.

These tests ensure that the workflow loop verification system works correctly:
Plan → Execute → Verify → Report → Re-plan if needed
"""

import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import json
import uuid

from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext
from rev.execution.quick_verify import (
    verify_task_execution,
    VerificationResult,
    _verify_refactoring,
    _verify_file_creation,
    _verify_directory_creation,
    quick_verify_extraction_completeness,
)


class TestVerificationResult:
    """Tests for the VerificationResult dataclass."""

    def test_verification_result_passed(self):
        """Test creating a passed verification result."""
        result = VerificationResult(
            passed=True,
            message="All checks passed",
            details={"check1": "ok"},
        )
        assert result.passed is True
        assert "All checks passed" in str(result)
        assert "[OK]" in str(result)

    def test_verification_result_failed(self):
        """Test creating a failed verification result."""
        result = VerificationResult(
            passed=False,
            message="Verification failed",
            details={"error": "File not found"},
            should_replan=True,
        )
        assert result.passed is False
        assert result.should_replan is True
        assert "[FAIL]" in str(result)


class TestVerifyTaskExecution:
    """Tests for the main verify_task_execution function."""

    def test_verify_non_completed_task(self):
        """Test verifying a task that hasn't completed."""
        task = Task(
            description="Test task",
            action_type="test"
        )
        task.status = TaskStatus.IN_PROGRESS

        context = RevContext(user_request="Test")
        result = verify_task_execution(task, context)

        assert result.passed is False
        assert "not COMPLETED" in result.message

    def test_verify_unknown_action_type(self):
        """Test verifying a task with unknown action type."""
        task = Task(
            description="Do something unknown",
            action_type="unknown_action"
        )
        task.status = TaskStatus.COMPLETED

        context = RevContext(user_request="Test")
        result = verify_task_execution(task, context)

        # Should pass because we skip verification for unknown types
        assert result.passed is True
        assert "No specific verification available" in result.message

    def test_edit_replace_in_file_noop_fails(self):
        """replace_in_file with replaced=0 must fail verification (prevents silent no-ops)."""
        from rev import config

        base = Path("tmp_test/manual").resolve()
        base.mkdir(parents=True, exist_ok=True)
        tmp_path = base / f"noop_{uuid.uuid4().hex[:8]}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        config.set_workspace_root(tmp_path)
        (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

        task = Task(description="Edit main.py to update imports", action_type="edit")
        task.status = TaskStatus.COMPLETED
        task.tool_events = [
            {
                "tool": "replace_in_file",
                "args": {"path": "main.py", "find": "x", "replace": "y"},
                "raw_result": json.dumps({"replaced": 0, "path_rel": "main.py"}),
            }
        ]

        context = RevContext(user_request="Test")
        result = verify_task_execution(task, context)
        assert result.passed is False
        assert "tool_noop" in result.message

    def test_refactor_read_only_fails(self):
        """A refactor task that only read files should not be marked completed."""
        from rev import config

        base = Path("tmp_test/manual").resolve()
        base.mkdir(parents=True, exist_ok=True)
        tmp_path = base / f"readonly_{uuid.uuid4().hex[:8]}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        config.set_workspace_root(tmp_path)
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "analysts.py").write_text("class A: pass\n", encoding="utf-8")

        task = Task(description="Refactor lib/analysts.py into a package", action_type="refactor")
        task.status = TaskStatus.COMPLETED
        task.tool_events = [
            {"tool": "read_file", "args": {"path": "lib/analysts.py"}, "raw_result": json.dumps({"path_rel": "lib/analysts.py"})}
        ]

        context = RevContext(user_request="Test")
        result = verify_task_execution(task, context)
        assert result.passed is False
        assert "read-only" in result.message.lower()

    def test_refactor_does_not_truncate_init_py_as_directory(self):
        """Guard against '__init__.py' being mis-parsed as a '__init__' directory."""
        from rev import config
        from rev.execution.quick_verify import _verify_refactoring

        base = Path("tmp_test/manual").resolve()
        base.mkdir(parents=True, exist_ok=True)
        tmp_path = base / f"initpy_{uuid.uuid4().hex[:8]}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        config.set_workspace_root(tmp_path)
        analysts_dir = tmp_path / "lib" / "analysts"
        analysts_dir.mkdir(parents=True)
        (analysts_dir / "__init__.py").write_text("# init\n", encoding="utf-8")
        (analysts_dir / "breakout.py").write_text("class Breakout: pass\n", encoding="utf-8")

        task = Task(description="Update lib/analysts/__init__.py exports", action_type="refactor")
        task.status = TaskStatus.COMPLETED

        context = RevContext(user_request="Test")
        result = _verify_refactoring(task, context)
        # It may still fail for other reasons, but it must not choose __init__ as a directory.
        debug = (result.details or {}).get("debug", {})
        target_dir = str(debug.get("target_directory", ""))
        assert "__init__" not in target_dir.replace("\\", "/").split("/")[-1]


class TestVerifyFileCreation:
    """Tests for file creation verification."""

    def test_verify_file_created(self):
        """Test verifying that a file was actually created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a test file
            test_file = tmpdir_path / "test.py"
            test_file.write_text("print('hello')")

            # Change to temp directory for relative path resolution
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="create file at ./test.py",
                    action_type="add"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_file_creation(task, context)

                assert result.passed is True
                assert "test.py" in result.message
                assert result.details["file_exists"] is True
                assert result.details["file_size"] > 0
            finally:
                os.chdir(old_cwd)

    def test_verify_file_not_created(self):
        """Test verification fails when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="create file at ./nonexistent.py",
                    action_type="add"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_file_creation(task, context)

                assert result.passed is False
                assert "not created" in result.message
                assert result.should_replan is True
            finally:
                os.chdir(old_cwd)

    def test_verify_empty_file_fails(self):
        """Test that empty files are detected as failed verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create an empty file
            test_file = tmpdir_path / "empty.py"
            test_file.write_text("")

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="create file at ./empty.py",
                    action_type="add"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_file_creation(task, context)

                assert result.passed is False
                assert "empty" in result.message
                assert result.should_replan is True
            finally:
                os.chdir(old_cwd)


class TestVerifyDirectoryCreation:
    """Tests for directory creation verification."""

    def test_verify_directory_created(self):
        """Test verifying that a directory was created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a test directory
            test_dir = tmpdir_path / "test_dir"
            test_dir.mkdir()

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="create directory ./test_dir/",
                    action_type="create_directory"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_directory_creation(task, context)

                assert result.passed is True
                assert "successfully" in result.message
            finally:
                os.chdir(old_cwd)

    def test_verify_directory_not_created(self):
        """Test verification fails when directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="create directory ./nonexistent/",
                    action_type="create_directory"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_directory_creation(task, context)

                assert result.passed is False
                assert "not created" in result.message
                assert result.should_replan is True
            finally:
                os.chdir(old_cwd)


class TestVerifyExtractionCompleteness:
    """Tests for extraction completeness verification."""

    def test_extraction_complete(self):
        """Test successful extraction completeness check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create source file
            source_file = tmpdir_path / "source.py"
            source_file.write_text("class A:\n    pass\nclass B:\n    pass")

            # Create target directory with extracted files
            target_dir = tmpdir_path / "extracted"
            target_dir.mkdir()
            (target_dir / "a.py").write_text("class A:\n    pass")
            (target_dir / "b.py").write_text("class B:\n    pass")

            success, details = quick_verify_extraction_completeness(
                source_file,
                target_dir,
                expected_items=["A", "B"]
            )

            assert success is True
            assert len(details["found_files"]) >= 2

    def test_extraction_incomplete_missing_directory(self):
        """Test extraction fails when target directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            source_file = tmpdir_path / "source.py"
            source_file.write_text("class A:\n    pass")

            target_dir = tmpdir_path / "nonexistent"

            success, details = quick_verify_extraction_completeness(
                source_file,
                target_dir,
                expected_items=["A"]
            )

            assert success is False
            assert "does not exist" in details.get("error", "")

    def test_extraction_incomplete_missing_files(self):
        """Test extraction fails when not all files were created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            source_file = tmpdir_path / "source.py"
            source_file.write_text("class A:\n    pass\nclass B:\n    pass")

            target_dir = tmpdir_path / "extracted"
            target_dir.mkdir()
            # Only create one file, but expect two
            (target_dir / "a.py").write_text("class A:\n    pass")

            success, details = quick_verify_extraction_completeness(
                source_file,
                target_dir,
                expected_items=["A", "B"]
            )

            assert success is False
            assert "Found" in details.get("error", "")


class TestVerifyRefactoringExtraction:
    """Tests for refactoring/extraction verification."""

    def test_verify_extraction_with_valid_structure(self):
        """Test verifying a valid extraction refactoring."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create the analyst directory structure
            analysts_dir = tmpdir_path / "lib" / "analysts"
            analysts_dir.mkdir(parents=True)

            # Create individual analyst files
            (analysts_dir / "breakout_analyst.py").write_text(
                "class BreakoutAnalyst:\n    pass"
            )
            (analysts_dir / "claude_analyst.py").write_text(
                "class ClaudeAnalyst:\n    pass"
            )

            # Create __init__.py
            (analysts_dir / "__init__.py").write_text(
                "from .breakout_analyst import BreakoutAnalyst\n"
                "from .claude_analyst import ClaudeAnalyst\n"
            )

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="break out analyst classes in ./lib/analysts.py into ./lib/analysts/ directory",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_refactoring(task, context)

                assert result.passed is True
                assert "successful" in result.message.lower()
                assert result.details.get("files_created", 0) >= 2
            finally:
                os.chdir(old_cwd)

    def test_verify_extraction_incomplete(self):
        """Test verification fails for incomplete extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create the directory but leave it empty
            analysts_dir = tmpdir_path / "lib" / "analysts"
            analysts_dir.mkdir(parents=True)

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                task = Task(
                    description="break out analyst classes in ./lib/analysts.py into ./lib/analysts/ directory",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Test")
                result = _verify_refactoring(task, context)

                # Should fail because directory is empty
                assert result.passed is False
                assert result.should_replan is True
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
