import json
from pathlib import Path

from rev import config
from rev.tools.registry import execute_tool


def test_read_file_blocks_command_like_input():
    base = Path("tmp_test/command_guard").resolve()
    base.mkdir(parents=True, exist_ok=True)
    config.set_workspace_root(base)

    output = execute_tool("read_file", {"path": "npm test tests/user.test.js"})
    payload = json.loads(output)
    assert payload.get("blocked") is True
    assert "command-like" in payload.get("error", "").lower()


def test_read_file_allows_existing_path_with_spaces():
    base = Path("tmp_test/command_guard_spaces").resolve()
    target_dir = base / "dir with space"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "notes.txt"
    target_file.write_text("ok", encoding="utf-8")

    config.set_workspace_root(base)
    output = execute_tool("read_file", {"path": "dir with space/notes.txt"})
    assert output == "ok"
