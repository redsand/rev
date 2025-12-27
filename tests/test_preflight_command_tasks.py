import pytest

from rev.execution.orchestrator import _preflight_correct_action_semantics
from rev.models.task import Task


@pytest.mark.parametrize(
    "description",
    [
        "Use run_terminal_command to install missing dependency by running npm install --save-dev @eslint/js",
        "Install dependency using yum install nodejs",
        "Install dependency using dnf install nodejs",
        "Install dependency using choco install nodejs",
    ],
)
def test_preflight_coerces_command_task_to_test(description):
    task = Task(description=description, action_type="edit")

    ok, messages = _preflight_correct_action_semantics(task)

    assert ok is True
    assert task.action_type == "test"
    assert any("command execution task" in msg for msg in messages)
