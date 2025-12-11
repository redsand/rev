import json

import pytest

from rev.execution.router import TaskRouter
from rev.execution.planner import _cap_plan_tasks
from rev.execution.executor import _consume_tool_budget
from rev.execution.validator import (
    validate_execution,
    ValidationResult,
    ValidationStatus,
)
from rev.models.task import ExecutionPlan, Task, TaskStatus


def test_router_selects_quick_edit_for_small_bugfix():
    router = TaskRouter()
    route = router.route("Fix a typo in file foo.py and update a docstring", repo_stats={})
    assert route.mode == "quick_edit"
    assert route.validation_mode == "smoke"


def test_router_selects_focused_feature_for_multi_file_feature():
    router = TaskRouter()
    route = router.route("Add new CLI command and update parser and runner modules", repo_stats={})
    assert route.mode == "focused_feature"
    assert route.validation_mode == "targeted"


def test_router_selects_full_feature_for_security_audit():
    router = TaskRouter()
    route = router.route("Perform a security audit across services; check for vulnerabilities", repo_stats={})
    assert route.mode == "full_feature"
    assert route.validation_mode == "full"


def test_cap_plan_tasks_merges_validation_and_trims():
    plan = ExecutionPlan()
    for i in range(25):
        plan.add_task(f"Edit feature part {i}", action_type="edit")
    for i in range(10):
        plan.add_task(f"Run lint tool {i}", action_type="test")
    for i in range(15):
        plan.add_task(f"Run pytest module {i}", action_type="test")

    original = _cap_plan_tasks(plan, max_plan_tasks=10)
    assert original == 50
    assert len(plan.tasks) <= 10
    descriptions = [t.description for t in plan.tasks]
    assert any("lint/format/type checks" in d for d in descriptions)
    assert any("Run automated tests" in d for d in descriptions)


def test_tool_budget_blocks_after_limit():
    counters = {}
    limits = {"read_file": 1}
    allowed, msg = _consume_tool_budget("read_file", counters, limits)
    assert allowed
    assert counters["read_file"] == 1
    allowed, msg = _consume_tool_budget("read_file", counters, limits)
    assert not allowed
    assert "maximum number of read_file calls" in msg


@pytest.mark.parametrize(
    "mode,expected_test,expected_lint",
    [
        ("smoke", "python -m compileall .", None),
        ("targeted", "pytest -q tests/ --maxfail=1", "ruff check . --select E9,F63,F7,F82 --output-format=json"),
        ("full", "pytest -q tests/", "ruff check . --output-format=json"),
    ],
)
def test_validation_modes_run_expected_commands(monkeypatch, mode, expected_test, expected_lint):
    captured = []

    def fake_validate(result_name):
        return ValidationResult(name=result_name, status=ValidationStatus.PASSED)

    monkeypatch.setattr("rev.execution.validator._validate_goals", lambda goals: fake_validate("goals"))
    monkeypatch.setattr("rev.execution.validator._check_syntax", lambda: fake_validate("syntax"))
    monkeypatch.setattr(
        "rev.execution.validator._run_test_suite",
        lambda cmd: captured.append(("tests", cmd)) or ValidationResult("tests", ValidationStatus.PASSED),
    )
    monkeypatch.setattr(
        "rev.execution.validator._run_linter",
        lambda cmd: captured.append(("linter", cmd)) or ValidationResult("linter", ValidationStatus.PASSED),
    )
    monkeypatch.setattr("rev.execution.validator._check_git_diff", lambda plan: fake_validate("git_diff"))
    monkeypatch.setattr("rev.execution.validator._semantic_validation", lambda plan, req: fake_validate("semantic"))

    plan = ExecutionPlan()
    task = Task("edit something", "edit")
    task.status = TaskStatus.COMPLETED
    plan.tasks.append(task)

    report = validate_execution(
        plan,
        user_request="do work",
        validation_mode=mode,
        enable_auto_fix=False,
    )

    cmds = dict(captured)
    assert report.overall_status in (ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS)
    if expected_test:
        assert cmds.get("tests") == expected_test
    else:
        assert "tests" not in cmds
    if expected_lint:
        assert cmds.get("linter") == expected_lint
    else:
        assert "linter" not in cmds
