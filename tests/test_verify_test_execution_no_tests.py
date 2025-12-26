import json

from rev.execution import quick_verify
from rev.core.context import RevContext
from rev.models.task import Task, TaskStatus


def test_verify_test_execution_retries_no_tests(monkeypatch) -> None:
    payload = {
        "rc": 1,
        "stdout": "No tests found, exiting with code 1",
        "stderr": "",
        "cmd": "npx jest tests/api/users.test.js",
        "cwd": "tmp_test",
    }
    raw_payload = json.dumps(payload)

    task = Task("Run jest on tests/api/users.test.js", action_type="test")
    task.status = TaskStatus.COMPLETED
    task.result = raw_payload
    task.tool_events = [{"tool": "run_tests", "raw_result": raw_payload}]

    calls = []

    def fake_run_validation_command(cmd, **_kwargs):
        calls.append(cmd)
        return {"rc": 0, "stdout": "ok", "stderr": "", "cmd": cmd}

    monkeypatch.setattr(quick_verify, "_run_validation_command", fake_run_validation_command)

    context = RevContext("test")
    result = quick_verify.verify_task_execution(task, context)

    assert result.passed is True
    assert calls
    retry_cmd = calls[0]
    assert isinstance(retry_cmd, list)
    assert "--runTestsByPath" in retry_cmd
