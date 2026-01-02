from rev.execution.quick_verify import verify_task_execution, VerificationResult
from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext


def test_run_cmd_stderr_error_triggers_replan():
    ctx = RevContext(user_request="test")
    task = Task(description="run npm run build", action_type="run")
    task.status = TaskStatus.COMPLETED
    task.tool_events = [{
        "tool": "run_cmd",
        "raw_result": {
            "rc": 0,
            "stdout": "",
            "stderr": "Error: missing module pinia",
        }
    }]

    result = verify_task_execution(task, ctx)
    assert isinstance(result, VerificationResult)
    assert result.passed is False
    assert result.should_replan is True
    assert "missing" in (result.details.get("stderr", "").lower())
