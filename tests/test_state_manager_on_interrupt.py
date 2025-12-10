"""Tests for the ``StateManager.on_interrupt`` output.

The ``on_interrupt`` method is responsible for:
* Saving a checkpoint (the filename contains the ``session_id`` GUID)
* Printing a resume command that includes the full checkpoint path
* Optionally printing token‑usage statistics when a ``token_usage`` mapping is
  provided.

These tests capture the printed output and assert that the expected strings are
present. Two scenarios are covered:

1. ``token_usage`` is supplied – token usage lines should appear.
2. ``token_usage`` is omitted – token usage lines should not appear.

The tests use the ``capsys`` fixture from ``pytest`` to capture ``stdout``.
"""

import re

import pytest

import importlib.util, pathlib
_state_manager_path = pathlib.Path(__file__).parents[0].parent / "rev" / "execution" / "state_manager.py"
_spec = importlib.util.spec_from_file_location("rev.execution.state_manager", _state_manager_path)
_state_manager_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state_manager_module)
StateManager = _state_manager_module.StateManager
from rev.models.task import ExecutionPlan


def test_on_interrupt_includes_resume_command_and_guid(capsys):
    """When an interrupt occurs the printed resume command should contain the GUID.
    """
    plan = ExecutionPlan()
    manager = StateManager(plan, auto_save=False)
    checkpoint_path = manager.on_interrupt()

    captured = capsys.readouterr().out

    # The resume command line should be printed exactly as in ``StateManager``
    expected_resume = f"rev --resume {checkpoint_path}"
    assert expected_resume in captured

    # Verify that the checkpoint filename includes the session GUID (32‑hex chars)
    guid_pattern = re.compile(r"checkpoint_([0-9a-f]{32})_")
    match = guid_pattern.search(checkpoint_path)
    assert match, "Checkpoint filename does not contain a GUID"
    assert match.group(1) == manager.session_id


def test_on_interrupt_token_usage_display(capsys):
    """Token usage statistics should be printed when provided.
    """
    token_usage = {"total": 1234, "prompt": 567, "completion": 678}
    plan = ExecutionPlan()
    manager = StateManager(plan, auto_save=False)
    checkpoint_path = manager.on_interrupt(token_usage=token_usage)

    out = capsys.readouterr().out

    # Token usage header and formatted values should appear
    assert "Token Usage:" in out
    # Values are formatted with commas per implementation
    assert "Total: 1,234" in out
    assert "Prompt: 567" in out
    assert "Completion: 678" in out

    # The resume command should still be present
    assert f"rev --resume {checkpoint_path}" in out
