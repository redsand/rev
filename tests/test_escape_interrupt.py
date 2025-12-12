"""Tests ensuring ESC interrupts execution immediately."""

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rev import config  # noqa: E402
from rev.execution import executor, planner  # noqa: E402
from rev.models.task import ExecutionPlan, TaskStatus  # noqa: E402


def _make_task():
    plan = ExecutionPlan()
    plan.add_task("sample task", "edit")
    return plan, plan.tasks[0]


def test_planning_mode_interrupts_before_llm(monkeypatch):
    """Planning should bail out immediately when ESC is active."""

    config.set_escape_interrupt(True)
    monkeypatch.setattr(
        planner,
        "_call_llm_with_tools",
        Mock(side_effect=AssertionError("LLM should not run when ESC is pressed")),
    )

    with pytest.raises(config.EscapeInterrupt):
        planner.planning_mode("sample request")

    assert config.get_escape_interrupt() is False


def test_execute_single_task_interrupts_before_llm(monkeypatch):
    """ESC should stop concurrent task execution before any LLM call."""
    plan, task = _make_task()

    # Simulate ESC already pressed
    config.set_escape_interrupt(True)

    # Ensure we never hit the LLM when ESC is already pressed
    monkeypatch.setattr(
        executor,
        "ollama_chat",
        Mock(side_effect=AssertionError("ollama_chat should not be called when ESC is pressed")),
    )

    result = executor.execute_single_task(
        task,
        plan,
        config.get_system_info_cached(),
        auto_approve=True,
        tools=[],
        enable_action_review=False,
        coding_mode=False,
        state_manager=None,
        exec_context=executor.ExecutionContext(plan),
        tool_limits={"read_file": 1, "search_code": 1, "run_cmd": 1},
    )

    assert result is False
    assert task.status == TaskStatus.STOPPED
    config.set_escape_interrupt(False)


def test_execute_single_task_interrupts_before_tool(monkeypatch):
    """ESC during planning loop stops execution immediately (sequential path)."""
    plan = ExecutionPlan()
    plan.add_task("sample task", "edit")
    # Start with ESC already pressed
    config.set_escape_interrupt(True)

    # Use a no-op execute_tool and ollama_chat to keep the loop simple
    monkeypatch.setattr(executor, "ollama_chat", Mock(return_value={"message": {"content": ""}}))
    monkeypatch.setattr(executor, "execute_tool", Mock(return_value="{}"))

    result = executor.execution_mode(
        plan,
        auto_approve=True,
        tools=[],
        enable_action_review=False,
        coding_mode=False,
    )

    assert result is False
    # Task should be marked stopped by the ESC interrupt handler
    assert plan.tasks[0].status == TaskStatus.STOPPED
    config.set_escape_interrupt(False)
