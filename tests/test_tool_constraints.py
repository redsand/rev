import json
from pathlib import Path

from rev import config
from rev.core.text_tool_shim import maybe_execute_tool_call_from_text
from rev.execution.tool_constraints import allowed_tools_for_action, has_write_tool
from rev.execution.orchestrator import _enforce_action_tool_constraints
from rev.models.task import Task


def test_allowed_tools_for_write_action_excludes_read_tools():
    allowed = allowed_tools_for_action("add")
    assert allowed is not None
    assert "write_file" in allowed
    assert "read_file" not in allowed


def test_has_write_tool_detects_write_usage():
    assert has_write_tool(["read_file", "list_dir"]) is False
    assert has_write_tool(["read_file", "write_file"]) is True


def test_recovered_tool_call_rejected_for_write_action():
    base = Path("tmp_test/tool_constraints").resolve()
    base.mkdir(parents=True, exist_ok=True)
    config.set_workspace_root(base)
    allowed = allowed_tools_for_action("edit")
    payload = json.dumps({"tool_name": "read_file", "arguments": {"path": "notes.txt"}})
    executed = maybe_execute_tool_call_from_text(payload, allowed_tools=sorted(allowed or []))
    assert executed is None


def test_enforce_action_tool_constraints_requires_write_tool():
    task = Task(description="add file", action_type="add")
    task.tool_events = [{"tool": "read_file", "args": {}}]
    ok, reason = _enforce_action_tool_constraints(task)
    assert ok is False
    assert reason is not None and "write tool" in reason.lower()


def test_enforce_action_tool_constraints_allows_write_tool():
    task = Task(description="edit file", action_type="edit")
    task.tool_events = [{"tool": "read_file", "args": {}}, {"tool": "write_file", "args": {}}]
    ok, reason = _enforce_action_tool_constraints(task)
    assert ok is True
    assert reason is None
