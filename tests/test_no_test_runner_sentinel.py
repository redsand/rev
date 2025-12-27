import json

from rev.core.context import RevContext
from rev.execution import quick_verify
from rev.models.task import Task, TaskStatus


def test_no_test_runner_sentinel_skips_tests() -> None:
    payload = json.dumps({"rc": 0, "stdout": "REV_NO_TEST_RUNNER", "stderr": ""})
    task = Task("Run tests", action_type="test")
    task.status = TaskStatus.COMPLETED
    task.result = payload
    task.tool_events = [{"tool": "run_cmd", "raw_result": payload}]

    context = RevContext("test")
    result = quick_verify.verify_task_execution(task, context)

    assert result.passed is True
    assert result.details.get("skipped") is True
