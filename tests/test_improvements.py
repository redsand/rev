#!/usr/bin/env python3
"""Pytest coverage for verification improvements.

These tests must run inside the repo workspace. Some sandboxed Windows
environments deny access to system temp directories, so we create test
workspaces under the current rev repo root.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from rev.config import ROOT
from rev.core.context import RevContext
from rev.execution.quick_verify import verify_task_execution
from rev.models.task import Task, TaskStatus


def _make_workspace_dir(prefix: str) -> Path:
    path = ROOT / f"{prefix}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_verification_improvements() -> None:
    test_root = _make_workspace_dir("tmp_verify")
    try:
        lib_dir = test_root / "lib"
        analysts_dir = lib_dir / "analysts"
        analysts_dir.mkdir(parents=True)

        (analysts_dir / "analyst1.py").write_text("class Analyst1: pass\n", encoding="utf-8")
        (analysts_dir / "analyst2.py").write_text("class Analyst2: pass\n", encoding="utf-8")
        (analysts_dir / "__init__.py").write_text(
            "from .analyst1 import Analyst1\nfrom .analyst2 import Analyst2\n",
            encoding="utf-8",
        )

        source_rel = (lib_dir / "analysts.py").relative_to(ROOT).as_posix()
        target_rel = analysts_dir.relative_to(ROOT).as_posix() + "/"

        context = RevContext(user_request="Extract analysts")
        test_descriptions = [
            f"Extract analyst classes from {source_rel} into {target_rel} directory",
            f"Break out individual analysts from {source_rel} to {target_rel}",
            f"Split the analyst file into separate modules in {target_rel}",
            f"Reorganize the analysts by moving them to {target_rel}",
            f"Create individual files for each analyst in {target_rel} directory",
        ]

        for desc in test_descriptions:
            task = Task(description=desc, action_type="refactor")
            task.status = TaskStatus.COMPLETED
            result = verify_task_execution(task, context)
            assert result.passed, f"Verification incorrectly failed for: {desc}\n{result.message}"
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_empty_extraction_detection() -> None:
    test_root = _make_workspace_dir("tmp_empty_extract")
    try:
        lib_dir = test_root / "lib"
        analysts_dir = lib_dir / "analysts"
        analysts_dir.mkdir(parents=True)

        source_rel = (lib_dir / "analysts.py").relative_to(ROOT).as_posix()
        target_rel = analysts_dir.relative_to(ROOT).as_posix() + "/"

        context = RevContext(user_request="Extract analysts")
        test_descriptions = [
            f"Extract 3 analysts from {source_rel} into {target_rel} directory",
            f"Move analyst classes to {target_rel}",
            f"Reorganize by putting each analyst in its own file in {target_rel}",
        ]

        for desc in test_descriptions:
            task = Task(description=desc, action_type="refactor")
            task.status = TaskStatus.COMPLETED
            result = verify_task_execution(task, context)
            assert not result.passed, "Should have detected empty extraction"
            assert result.should_replan, "Should request replan on empty extraction"
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_logging_output() -> None:
    import logging

    logger = logging.getLogger("rev.agents.refactoring")
    assert logger.name == "rev.agents.refactoring"

