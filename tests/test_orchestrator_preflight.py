import uuid
from pathlib import Path

from rev import config
from rev.models.task import Task
from rev.execution.orchestrator import _preflight_correct_task_paths


def _make_workspace() -> Path:
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"preflight_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_preflight_corrects_missing_basename_to_unique_match():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "analysts.py").write_text("class A: pass\n", encoding="utf-8")

    task = Task(description="split analysts.py into lib/analysts/ using split_python_module_classes", action_type="refactor")
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is True
    assert any("corrected missing path" in m for m in msgs)
    assert "lib/analysts.py" in task.description.replace("\\", "/")


def test_preflight_fails_on_ambiguous_basename_matches():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "utils").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "analysts.py").write_text("class A: pass\n", encoding="utf-8")
    (root / "utils" / "analysts.py").write_text("class B: pass\n", encoding="utf-8")

    task = Task(description="split analysts.py into a package", action_type="refactor")
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is False
    assert any("ambiguous" in m for m in msgs)


def test_preflight_allows_missing_output_paths_for_refactor_when_input_exists():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "analysts.py").write_text("class A: pass\n", encoding="utf-8")

    task = Task(
        description=(
            "Split ./lib/analysts.py into ./lib/analysts/breakout_analyst.py and update ./lib/analysts/__init__.py"
        ),
        action_type="refactor",
    )
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is True
    assert any("ignored missing output" in m for m in msgs)


def test_preflight_fails_for_read_task_when_any_path_missing():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "analysts.py").write_text("class A: pass\n", encoding="utf-8")

    task = Task(description="read ./lib/analysts/missing.py and summarize", action_type="read")
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is False
    assert any("missing path" in m for m in msgs)


def test_preflight_refuses_operating_on_backup_only():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "lib").mkdir(parents=True, exist_ok=True)
    # Only backup exists; original source is gone.
    (root / "lib" / "analysts.py.bak").write_text("class A: pass\n", encoding="utf-8")

    task = Task(description="split lib/analysts.py into lib/analysts/", action_type="refactor")
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is False
    assert any("only backup" in m.lower() for m in msgs)


def test_preflight_dedupes_redundant_prefix_paths():
    root = _make_workspace()
    config.set_workspace_root(root)
    (root / "lib" / "analysts").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "analysts" / "__init__.py").write_text("# init\n", encoding="utf-8")

    task = Task(
        description="read lib/analysts/lib/analysts/__init__.py and summarize",
        action_type="read",
    )
    ok, msgs = _preflight_correct_task_paths(task=task, project_root=root)

    assert ok is True
    assert "lib/analysts/__init__.py" in task.description.replace("\\", "/")
    assert any("duplicated" in m for m in msgs)
