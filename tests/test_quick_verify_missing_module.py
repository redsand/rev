from rev.execution.quick_verify import VerificationResult, verify_task_execution
from rev.models.task import Task
from rev.core.context import RevContext


def test_run_cmd_missing_module_triggers_replan(monkeypatch):
    ctx = RevContext(user_request="test")
    task = Task(description="run npm run build", action_type="tool")
    from rev.models.task import TaskStatus
    task.status = TaskStatus.COMPLETED

    fake_events = [{
        "tool": "run_cmd",
        "raw_result": {
            "rc": 1,
            "stdout": "",
            "stderr": "Module not found: Cannot find module 'pinia'",
        }
    }]

    task.tool_events = fake_events

    result = verify_task_execution(task, ctx)
    assert isinstance(result, VerificationResult)
    assert result.passed is False
    assert result.should_replan is True
    assert result.should_replan is True
    stderr_lower = (result.details.get("stderr", "") or "").lower()
    remediation = result.details.get("remediation")
    assert ("module not found" in stderr_lower) or remediation
