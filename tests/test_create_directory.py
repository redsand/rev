#!/usr/bin/env python3
"""Tests for create_directory action/tool behavior."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from rev.config import ROOT
from rev.core.agent_registry import AgentRegistry
from rev.models.task import Task, TaskStatus
from rev.execution.quick_verify import verify_task_execution
from rev.core.context import RevContext
from rev.tools.registry import execute_tool


def test_create_directory_tool_and_verification() -> None:
    test_dir_rel = f"tmp_create_dir_{uuid.uuid4().hex}/nested"
    test_dir_abs = ROOT / test_dir_rel
    try:
        assert not test_dir_abs.exists()

        # Ensure registry routes create_directory to an agent (availability check).
        agent = AgentRegistry.get_agent_instance("create_directory")
        assert agent is not None

        # Execute tool directly (no LLM / interactive prompts in unit tests).
        result = execute_tool("create_directory", {"path": test_dir_rel})
        payload = json.loads(result)
        assert payload.get("error") is None
        assert test_dir_abs.exists() and test_dir_abs.is_dir()

        # Verify uses tool metadata to locate the created dir.
        task = Task(description=f"Create directory {test_dir_rel}", action_type="create_directory")
        task.status = TaskStatus.COMPLETED
        task.result = result
        context = RevContext(user_request="Create directory", auto_approve=True)
        verification = verify_task_execution(task, context)
        assert verification.passed, verification.message
    finally:
        shutil.rmtree(test_dir_abs.parents[0], ignore_errors=True)

