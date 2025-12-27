from pathlib import Path

from rev.execution import quick_verify
from rev.models.task import Task


def test_run_validation_steps_uses_project_root_cwd(monkeypatch):
    root = Path("tmp_test/workdir_project").resolve()
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
    test_file = root / "src" / "app.test.ts"
    test_file.write_text("test", encoding="utf-8")

    task = Task("run tests", action_type="test")
    task.validation_steps = ["test"]
    details = {"file_path": str(test_file)}

    calls = []

    def fake_run_validation_command(cmd, use_tests_tool=False, timeout=None, cwd=None, _retry_count=0):
        calls.append(cwd)
        return {"rc": 0}

    monkeypatch.setattr(quick_verify, "_run_validation_command", fake_run_validation_command)

    result = quick_verify._run_validation_steps(task, details, tool_events=None)
    assert result is not None
    assert calls, "expected at least one validation command"
    assert Path(calls[0]).resolve() == root
