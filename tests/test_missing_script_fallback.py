import json
from pathlib import Path

from rev.execution import quick_verify
from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext


def test_run_validation_command_retries_missing_script(monkeypatch):
    calls = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({
                "rc": 1,
                "stdout": "",
                "stderr": "npm error Missing script: \"test\"",
            })
        return json.dumps({"rc": 0, "stdout": "ok", "stderr": ""})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_ensure_tool_available", lambda cmd: True)
    monkeypatch.setattr(quick_verify, "detect_test_command", lambda path: ["npm", "run", "test:ci"])

    result = quick_verify._run_validation_command(
        ["npm", "test"],
        use_tests_tool=True,
        timeout=10,
        cwd=Path("tmp_test"),
    )

    assert result.get("rc") == 0
    assert len(calls) == 2
    assert calls[1]["cmd"] == ["npm", "run", "test:ci"]


def test_verify_test_execution_skips_missing_script(monkeypatch):
    task = Task(description="Run tests", action_type="test")
    task.status = TaskStatus.COMPLETED
    task.result = {
        "rc": 1,
        "stdout": "",
        "stderr": "npm error Missing script: \"test\"",
        "cmd": "npm test",
    }
    context = RevContext(user_request="Test request")

    monkeypatch.setattr(quick_verify, "detect_test_command", lambda path: None)

    result = quick_verify.verify_task_execution(task, context)

    assert result.passed is True
    assert result.details.get("skipped") is True
