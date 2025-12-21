import json
from pathlib import Path

from rev import config
from rev.core.text_tool_shim import maybe_execute_tool_call_from_text


def test_text_tool_shim_executes_allowed_tool(tmp_path: Path):
    config.set_workspace_root(tmp_path)
    content = json.dumps({"tool_name": "create_directory", "arguments": {"path": "lib/analysts"}})
    executed = maybe_execute_tool_call_from_text(content, allowed_tools=["create_directory"])
    assert executed is not None
    assert executed.tool_name == "create_directory"
    assert (tmp_path / "lib" / "analysts").exists()


def test_text_tool_shim_rejects_disallowed_tool(tmp_path: Path):
    config.set_workspace_root(tmp_path)
    content = json.dumps({"tool_name": "create_directory", "arguments": {"path": "lib/analysts"}})
    executed = maybe_execute_tool_call_from_text(content, allowed_tools=["write_file"])
    assert executed is None

