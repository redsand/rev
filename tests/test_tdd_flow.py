from pathlib import Path
import uuid

from rev.core.context import RevContext
from rev.execution import quick_verify
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task, TaskStatus
from rev import config


def _make_root(name: str) -> Path:
    root = Path("tmp_test") / "tdd_flow" / name / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_test_only_change_allows_tdd_red(monkeypatch) -> None:
    monkeypatch.setattr(config, "TDD_ENABLED", True)
    root = _make_root("red")
    test_dir = root / "tests"
    test_dir.mkdir()
    test_path = test_dir / "sample.test.js"
    test_path.write_text("test('x', () => {})\n", encoding="utf-8")

    task = Task(description="Add tests/sample.test.js", action_type="add")
    task.status = TaskStatus.COMPLETED
    task.tool_events = [{"tool": "write_file", "args": {"path": str(test_path)}}]

    context = RevContext(user_request="add tests")

    def fake_strict(_action, _paths, _mode=None, task=None, **_kwargs):
        return VerificationResult(
            passed=False,
            message="Frontend tests failed.",
            details={"strict": {"npm_test": {"rc": 1}}},
            should_replan=True,
        )

    monkeypatch.setattr(quick_verify, "_maybe_run_strict_verification", fake_strict)

    result = quick_verify.verify_task_execution(task, context)
    assert result.passed is True
    assert result.details.get("tdd_expected_failure") is True
    assert context.agent_state.get("tdd_pending_green") is True


def test_non_test_change_sets_tdd_require_test(monkeypatch) -> None:
    monkeypatch.setattr(config, "TDD_ENABLED", True)
    root = _make_root("green")
    src_dir = root / "src"
    src_dir.mkdir()
    src_path = src_dir / "app.py"
    src_path.write_text("print('hi')\n", encoding="utf-8")

    task = Task(description="Add src/app.py", action_type="add")
    task.status = TaskStatus.COMPLETED
    task.tool_events = [{"tool": "write_file", "args": {"path": str(src_path)}}]

    context = RevContext(user_request="implement feature")
    context.agent_state["tdd_pending_green"] = True

    monkeypatch.setattr(quick_verify, "_maybe_run_strict_verification", lambda *args, **kwargs: {})

    result = quick_verify.verify_task_execution(task, context)
    assert result.passed is True
    assert context.agent_state.get("tdd_require_test") is True
    assert context.agent_state.get("tdd_pending_green") is False


def test_test_task_failure_allowed_in_tdd_red(monkeypatch) -> None:
    monkeypatch.setattr(config, "TDD_ENABLED", True)
    task = Task(description="Run tests", action_type="test")
    task.status = TaskStatus.COMPLETED

    context = RevContext(user_request="tdd flow")
    context.agent_state["tdd_pending_green"] = True

    monkeypatch.setattr(
        quick_verify,
        "_verify_test_execution",
        lambda *_args, **_kwargs: VerificationResult(passed=False, message="Tests failed", details={}),
    )

    result = quick_verify.verify_task_execution(task, context)
    assert result.passed is True
    assert result.details.get("tdd_expected_failure") is True


def test_test_task_pass_clears_tdd_require_test(monkeypatch) -> None:
    monkeypatch.setattr(config, "TDD_ENABLED", True)
    task = Task(description="Run tests", action_type="test")
    task.status = TaskStatus.COMPLETED

    context = RevContext(user_request="tdd flow")
    context.agent_state["tdd_require_test"] = True

    monkeypatch.setattr(
        quick_verify,
        "_verify_test_execution",
        lambda *_args, **_kwargs: VerificationResult(passed=True, message="ok", details={}),
    )

    result = quick_verify.verify_task_execution(task, context)
    assert result.passed is True
    assert context.agent_state.get("tdd_require_test") is False
