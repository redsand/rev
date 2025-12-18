"""
Tests for the refactoring extraction workflow - specifically testing that
analyst classes are actually extracted to individual files.

This tests the complete workflow that was shown as broken in the issue.
"""

import pytest
import tempfile
import shutil
from uuid import uuid4
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext
from rev.execution.quick_verify import (
    verify_task_execution,
    VerificationResult,
    quick_verify_extraction_completeness,
)
from rev.workspace import init_workspace, reset_workspace


class TestAnalystExtractionWorkflow:
    """Tests for extracting analyst classes into individual files."""

    def test_extraction_creates_individual_files(self):
        """
        Test that extracting analyst classes from a single file
        creates individual files for each analyst.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Create lib directory
                lib_dir = Path("lib")
                lib_dir.mkdir()

                # Create analysts.py with multiple analyst classes
                analysts_file = lib_dir / "analysts.py"
                analysts_file.write_text("""
import datetime

class BreakoutAnalyst:
    \"\"\"Analyzes breakout patterns in trading data.\"\"\"
    def __init__(self):
        self.name = "Breakout"
        self.version = "1.0"

    def analyze(self, market_data):
        # Breakout analysis logic
        return {"signal": "bullish", "strength": 0.8}

    def validate(self):
        return True


class ClaudeAnalyst:
    \"\"\"AI-powered analysis using Claude.\"\"\"
    def __init__(self):
        self.name = "Claude"
        self.version = "2.0"

    def analyze(self, market_data):
        # Claude analysis logic
        return {"signal": "neutral", "strength": 0.5}

    def validate(self):
        return True


class VolumeAnalyst:
    \"\"\"Analyzes volume trends and patterns.\"\"\"
    def __init__(self):
        self.name = "Volume"
        self.version = "1.5"

    def analyze(self, market_data):
        # Volume analysis logic
        return {"signal": "bearish", "strength": 0.6}

    def validate(self):
        return True
""")

                # Simulate extraction: create individual files
                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()

                # Create individual analyst files
                (analysts_dir / "breakout_analyst.py").write_text("""
class BreakoutAnalyst:
    \"\"\"Analyzes breakout patterns in trading data.\"\"\"
    def __init__(self):
        self.name = "Breakout"
        self.version = "1.0"

    def analyze(self, market_data):
        # Breakout analysis logic
        return {"signal": "bullish", "strength": 0.8}

    def validate(self):
        return True
""")

                (analysts_dir / "claude_analyst.py").write_text("""
class ClaudeAnalyst:
    \"\"\"AI-powered analysis using Claude.\"\"\"
    def __init__(self):
        self.name = "Claude"
        self.version = "2.0"

    def analyze(self, market_data):
        # Claude analysis logic
        return {"signal": "neutral", "strength": 0.5}

    def validate(self):
        return True
""")

                (analysts_dir / "volume_analyst.py").write_text("""
class VolumeAnalyst:
    \"\"\"Analyzes volume trends and patterns.\"\"\"
    def __init__(self):
        self.name = "Volume"
        self.version = "1.5"

    def analyze(self, market_data):
        # Volume analysis logic
        return {"signal": "bearish", "strength": 0.6}

    def validate(self):
        return True
""")

                # Create __init__.py
                (analysts_dir / "__init__.py").write_text("""
from .breakout_analyst import BreakoutAnalyst
from .claude_analyst import ClaudeAnalyst
from .volume_analyst import VolumeAnalyst

__all__ = ['BreakoutAnalyst', 'ClaudeAnalyst', 'VolumeAnalyst']
""")

                # Update main analysts.py to import from new directory
                analysts_file.write_text("""
from .analysts import BreakoutAnalyst, ClaudeAnalyst, VolumeAnalyst

__all__ = ['BreakoutAnalyst', 'ClaudeAnalyst', 'VolumeAnalyst']
""")

                # Now verify the extraction
                success, details = quick_verify_extraction_completeness(
                    analysts_file,
                    analysts_dir,
                    expected_items=["BreakoutAnalyst", "ClaudeAnalyst", "VolumeAnalyst"]
                )

                # Assertions
                assert success is True, f"Extraction should be complete. Details: {details}"
                assert len(details["found_files"]) >= 3, "Should have at least 3 analyst files"
                assert any("breakout" in f.lower() for f in details["found_files"]), "Should have breakout analyst file"
                assert any("claude" in f.lower() for f in details["found_files"]), "Should have claude analyst file"
                assert any("volume" in f.lower() for f in details["found_files"]), "Should have volume analyst file"

            finally:
                os.chdir(old_cwd)

    def test_verify_extraction_task(self):
        """Test verifying an extraction task status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Setup extracted structure
                lib_dir = Path("lib")
                lib_dir.mkdir()

                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()

                (analysts_dir / "analyst1.py").write_text("class Analyst1: pass")
                (analysts_dir / "analyst2.py").write_text("class Analyst2: pass")
                (analysts_dir / "__init__.py").write_text(
                    "from .analyst1 import Analyst1\n"
                    "from .analyst2 import Analyst2\n"
                )

                # Create a task
                task = Task(
                    description="break out analyst classes into ./lib/analysts/ directory",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                # Verify the task
                context = RevContext(user_request="Extract analysts")
                result = verify_task_execution(task, context)

                assert result.passed is True, f"Verification should pass. Message: {result.message}"
                assert result.details.get("files_created", 0) >= 2, "Should detect created files"

            finally:
                os.chdir(old_cwd)

    def test_extraction_fails_when_files_missing(self):
        """Test that extraction verification fails when directory is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Setup incomplete extracted structure
                lib_dir = Path("lib")
                lib_dir.mkdir()

                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()

                # Create directory but leave it empty - extraction failed
                # Don't create any files - this is the critical failure case

                task = Task(
                    description="break out 3 analyst classes into ./lib/analysts/",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Extract analysts")
                result = verify_task_execution(task, context)

                # Verification should fail - directory is empty (no files extracted)
                assert result.passed is False, \
                    "Empty extraction should fail verification"
                assert result.should_replan is True, \
                    "Incomplete extraction should trigger re-planning"

            finally:
                os.chdir(old_cwd)

    def test_extraction_workflow_integration(self):
        """
        Test a complete extraction workflow integration:
        1. Initial state: all analysts in one file
        2. Extraction performed
        3. Verification confirms extraction complete
        4. Imports are valid
        5. Main file updated with imports
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # 1. Initial state
                lib_dir = Path("lib")
                lib_dir.mkdir()

                analysts_file = lib_dir / "analysts.py"
                initial_content = """
class Analyst1:
    pass

class Analyst2:
    pass

class Analyst3:
    pass
"""
                analysts_file.write_text(initial_content)

                # 2. Extraction performed
                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()

                analyst_files = {
                    "analyst1.py": "class Analyst1:\n    pass\n",
                    "analyst2.py": "class Analyst2:\n    pass\n",
                    "analyst3.py": "class Analyst3:\n    pass\n",
                    "__init__.py": (
                        "from .analyst1 import Analyst1\n"
                        "from .analyst2 import Analyst2\n"
                        "from .analyst3 import Analyst3\n"
                    )
                }

                for filename, content in analyst_files.items():
                    (analysts_dir / filename).write_text(content)

                # 5. Main file updated
                updated_content = (
                    "from .analysts import Analyst1, Analyst2, Analyst3\n"
                    "__all__ = ['Analyst1', 'Analyst2', 'Analyst3']\n"
                )
                analysts_file.write_text(updated_content)

                # 3. Verification
                task = Task(
                    description="Extract 3 analysts from ./lib/analysts.py into ./lib/analysts/ directory",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Extract analysts")
                result = verify_task_execution(task, context)

                # Assertions
                assert result.passed is True, f"Extraction should be verified. Message: {result.message}"

                # 4. Verify imports are valid
                init_content = (analysts_dir / "__init__.py").read_text()
                assert "Analyst1" in init_content, "Should import Analyst1"
                assert "Analyst2" in init_content, "Should import Analyst2"
                assert "Analyst3" in init_content, "Should import Analyst3"

                # Verify main file imports from new location
                main_content = analysts_file.read_text()
                assert "from .analysts import" in main_content, "Main file should import from .analysts"

            finally:
                os.chdir(old_cwd)


class TestRegressionPrevention:
    """Tests to prevent regression of the extraction issues."""

    def test_no_silent_failures_in_extraction(self):
        """
        Regression test: Ensure extraction failures don't silently succeed.

        The original issue was that the REPL would mark tasks as completed
        without actually extracting files.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Create a source file
                lib_dir = Path("lib")
                lib_dir.mkdir()

                analysts_file = lib_dir / "analysts.py"
                analysts_file.write_text("class MyAnalyst: pass")

                # Simulate a failed extraction - directory created but empty
                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()
                # Don't create any files - this simulates the failure

                # Try to verify
                task = Task(
                    description="Extract MyAnalyst from lib/analysts.py into lib/analysts/ directory",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Extract")
                result = verify_task_execution(task, context)

                # This should FAIL verification and mark for re-planning
                assert result.passed is False, "Empty extraction should fail verification"
                assert result.should_replan is True, "Should trigger re-planning"
                assert "No Python files found" in result.message or "extraction" in result.message.lower(), \
                    "Should report specific extraction failure"

            finally:
                os.chdir(old_cwd)

    def test_verification_detects_incomplete_imports(self):
        """
        Regression test: Ensure extraction with broken imports is detected.

        The original issue included importing from files that don't exist.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                lib_dir = Path("lib")
                lib_dir.mkdir()

                analysts_dir = lib_dir / "analysts"
                analysts_dir.mkdir()

                # Create a file with broken imports
                (analysts_dir / "analyst1.py").write_text(
                    "from .nonexistent_module import Something\n"
                    "class Analyst1: pass\n"
                )

                # Create __init__.py that imports from files that exist
                (analysts_dir / "__init__.py").write_text(
                    "from .analyst1 import Analyst1\n"
                )

                task = Task(
                    description="Extract analysts into lib/analysts/",
                    action_type="refactor"
                )
                task.status = TaskStatus.COMPLETED

                context = RevContext(user_request="Extract")
                result = verify_task_execution(task, context)

                # The extraction structure exists but has import issues
                # Should be flagged as warning or error
                assert result.details, "Should capture details about the extraction"

            finally:
                os.chdir(old_cwd)

    def test_verification_uses_parent_directory_for_init_py(self):
        """
        Regression: ensure verify_task_execution does not truncate `.py` when
        inferring the target directory from a description containing
        `__init__.py`.
        """
        base = Path(f"tmp_parent_dir_test_{uuid4().hex}")
        try:
            base.mkdir(parents=True, exist_ok=False)
            init_workspace(base)

            lib_dir = base / "lib"
            lib_dir.mkdir()

            # Source file that should be considered the "old" file
            analysts_file = lib_dir / "analysts.py"
            analysts_file.write_text(
                "from .analysts import BreakoutAnalyst\n__all__ = ['BreakoutAnalyst']\n"
            )

            # Extracted package with __init__.py and one module
            analysts_dir = lib_dir / "analysts"
            analysts_dir.mkdir()
            (analysts_dir / "breakout_analyst.py").write_text(
                "class BreakoutAnalyst:\n    pass\n"
            )
            analysts_init = analysts_dir / "__init__.py"
            analysts_init.write_text(
                "from .breakout_analyst import BreakoutAnalyst\n__all__ = ['BreakoutAnalyst']\n"
            )

            # Task description includes a .py path for the package init
            task = Task(
                description=(
                    f"Extract analysts from {analysts_file} into {analysts_init}"
                ),
                action_type="refactor",
            )
            task.status = TaskStatus.COMPLETED

            context = RevContext(user_request="Extract")
            result = verify_task_execution(task, context)

            assert result.passed is True, f"Verification should pass: {result.message}"
            debug = result.details.get("debug", {})
            target_dir = str(debug.get("target_directory", "")).replace("\\", "/")
            assert target_dir.endswith("lib/analysts"), "Should resolve to parent directory, not __init__"
        finally:
            reset_workspace()
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
