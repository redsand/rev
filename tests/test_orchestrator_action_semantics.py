from rev.models.task import Task
from rev.execution.orchestrator import _preflight_correct_action_semantics


def test_refactor_with_read_only_intent_is_coerced_to_read():
    task = Task(
        description="Identify all import statements referencing lib.analysts and list files/lines",
        action_type="refactor",
    )
    ok, msgs = _preflight_correct_action_semantics(task)
    assert ok is True
    assert task.action_type == "read"
    assert any("coerced action" in m for m in msgs)


def test_read_action_with_write_intent_fails_fast():
    task = Task(
        description="Update imports across the codebase to use from lib.analysts import ...",
        action_type="read",
    )
    ok, msgs = _preflight_correct_action_semantics(task)
    assert ok is False
    assert any("conflicts with write intent" in m for m in msgs)

