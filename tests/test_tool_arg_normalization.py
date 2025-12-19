import json
from pathlib import Path
import uuid

import pytest

from rev import config
from rev.tools.registry import execute_tool


def _make_workspace() -> Path:
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"tool_args_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def temp_workspace():
    old_root = config.ROOT
    root = _make_workspace()
    config.set_workspace_root(root)
    try:
        yield root
    finally:
        config.set_workspace_root(old_root)


def test_execute_tool_unwraps_arguments_wrapper_for_list_dir(temp_workspace: Path):
    (temp_workspace / "lib" / "analysts").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "lib" / "analysts" / "__init__.py").write_text("# ok\n", encoding="utf-8")

    result = json.loads(execute_tool("list_dir", {"arguments": {"pattern": "lib/analysts/"}}))
    assert "files" in result
    assert "lib/analysts/__init__.py" in result["files"]
    assert all(path.startswith("lib/analysts/") for path in result["files"])


def test_split_python_module_classes_accepts_alias_args_and_backs_up_source(temp_workspace: Path):
    (temp_workspace / "lib").mkdir(parents=True, exist_ok=True)
    (temp_workspace / "lib" / "analysts.py").write_text(
        "class A:\n"
        "    pass\n\n"
        "class B:\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = json.loads(
        execute_tool(
            "split_python_module_classes",
            {"module_path": "lib/analysts.py", "output_dir": "lib/analysts"},
        )
    )

    assert result["package_dir"] == "lib/analysts"
    assert result["package_init"] == "lib/analysts/__init__.py"
    assert result["source_moved_to"].startswith("lib/analysts.py.bak")
    assert "lib/analysts/A.py" in result["created_files"]
    assert "lib/analysts/B.py" in result["created_files"]

    assert not (temp_workspace / "lib" / "analysts" / "lib" / "analysts").exists()
    assert (temp_workspace / "lib" / "analysts" / "__init__.py").exists()
    assert (temp_workspace / "lib" / "analysts" / "A.py").exists()
    assert (temp_workspace / "lib" / "analysts" / "B.py").exists()


def test_split_python_module_classes_skips_repeated_backups(temp_workspace: Path):
    (temp_workspace / "lib").mkdir(parents=True, exist_ok=True)
    source = temp_workspace / "lib" / "analysts.py"
    source.write_text("class A: pass\n", encoding="utf-8")

    # First split should succeed and rename source to .bak
    result1 = json.loads(
        execute_tool(
            "split_python_module_classes",
            {"module_path": "lib/analysts.py", "output_dir": "lib/analysts"},
        )
    )
    assert result1["package_dir"].endswith("lib/analysts")

    # Second split should detect the existing backup and skip
    result2 = json.loads(
        execute_tool(
            "split_python_module_classes",
            {"module_path": "lib/analysts.py", "output_dir": "lib/analysts"},
        )
    )
    assert result2.get("status") == "source_already_split"
