from rev.execution import planner
from rev.models.task import Task


def test_apply_validation_steps_to_task_trims_description() -> None:
    task = Task(
        "Edit src/app.js to add login flow. Run tests: npm test -- tests/app.test.js.",
        action_type="edit",
    )

    planner.apply_validation_steps_to_task(task)

    assert "npm test" not in task.description.lower()
    assert task.validation_steps == ["npm test -- tests/app.test.js"]


def test_apply_validation_steps_to_task_is_idempotent() -> None:
    task = Task(
        "Update api routes. Validation: pytest tests/test_api.py.",
        action_type="edit",
    )

    planner.apply_validation_steps_to_task(task)
    planner.apply_validation_steps_to_task(task)

    assert task.validation_steps == ["pytest tests/test_api.py"]


def test_apply_validation_steps_to_task_skips_test_action() -> None:
    task = Task("Run tests: npm test -- tests/app.test.js", action_type="test")

    planner.apply_validation_steps_to_task(task)

    assert task.description == "Run tests: npm test -- tests/app.test.js"
    assert task.validation_steps == []
