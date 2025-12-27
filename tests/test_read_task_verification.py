from rev.execution.quick_verify import verify_task_execution
from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext


def test_read_task_skips_verification_when_tools_ran():
    task = Task(description="Read tree", action_type="read")
    task.status = TaskStatus.COMPLETED
    task.tool_events = [{"tool": "tree_view", "raw_result": "{}"}]

    result = verify_task_execution(task, RevContext(user_request="test"))

    assert result.passed is True
    assert "verification skipped" in result.message.lower()


def test_read_task_skips_noop_detection():
    task = Task(description="Search code", action_type="read")
    task.status = TaskStatus.COMPLETED
    task.tool_events = [
        {
            "tool": "search_code",
            "raw_result": '{"matches": []}',
        }
    ]

    result = verify_task_execution(task, RevContext(user_request="test"))

    assert result.passed is True


def test_read_task_fails_when_no_tools_ran():
    task = Task(description="Read tree", action_type="read")
    task.status = TaskStatus.COMPLETED
    task.tool_events = []

    result = verify_task_execution(task, RevContext(user_request="test"))

    assert result.passed is False
    assert "no tools" in result.message.lower()
