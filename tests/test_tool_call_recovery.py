import json
from pathlib import Path

from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev import config


def test_recovers_tool_call_from_leading_fenced_json():
    # Ensure workspace root exists for relative path handling
    config.set_workspace_root(Path.cwd())

    payload = """```json
{
  "tool_name": "create_directory",
  "arguments": {"path": "tmp_test/from_fence"}
}
```"""

    recovered = recover_tool_call_from_text(payload)
    assert recovered is not None
    assert recovered.name == "create_directory"
    assert recovered.arguments == {"path": "tmp_test/from_fence"}


def test_recovers_tool_call_with_multiple_paths_in_fence():
    config.set_workspace_root(Path.cwd())

    payload = """```json
{
  "tool_name": "read_file",
  "arguments": {
    "paths": [
      "lib/analysts/__init__.py",
      "lib/analysts/BreakoutAnalyst.py",
      "lib/analysts/AvwapEarningsAnalyst.py"
    ]
  }
}
```"""

    recovered = recover_tool_call_from_text(payload)
    assert recovered is not None
    assert recovered.name == "read_file"
    assert recovered.arguments["paths"] == [
        "lib/analysts/__init__.py",
        "lib/analysts/BreakoutAnalyst.py",
        "lib/analysts/AvwapEarningsAnalyst.py",
    ]


def test_executes_read_file_with_paths_via_text_shim():
    # Build a small workspace with two files (explicit path to avoid platform TMP issues)
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / "shim_workspace"
    (root / "lib" / "analysts").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "analysts" / "__init__.py").write_text("# init\n", encoding="utf-8")
    (root / "lib" / "analysts" / "A.py").write_text("class A: pass\n", encoding="utf-8")
    config.set_workspace_root(root)

    payload = """```json
{
  "tool_name": "read_file",
  "arguments": {
    "paths": [
      "lib/analysts/__init__.py",
      "lib/analysts/A.py"
    ]
  }
}
```"""

    from rev.core.text_tool_shim import maybe_execute_tool_call_from_text

    executed = maybe_execute_tool_call_from_text(payload, allowed_tools=["read_file"])
    assert executed is not None
    assert executed.tool_name == "read_file"
    assert executed.tool_args == {"paths": ["lib/analysts/__init__.py", "lib/analysts/A.py"]}
    output = json.loads(executed.tool_output)
    assert "lib/analysts/__init__.py" in output
    assert "lib/analysts/A.py" in output
