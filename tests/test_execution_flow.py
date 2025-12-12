import pathlib
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rev.execution.orchestrator import AgentPhase, Orchestrator, OrchestratorConfig
from rev.execution.executor import concurrent_execution_mode
from rev.execution.reviewer import _quick_security_check
from rev.models.task import ExecutionPlan, TaskStatus


def _dummy_research(*_args, **_kwargs):
    return type("RF", (), {"relevant_files": [], "estimated_complexity": "low", "warnings": []})()


def test_mark_failed_advances_current_index():
    plan = ExecutionPlan()
    plan.add_task("first")
    plan.add_task("second")

    plan.mark_failed("boom")
    next_task = plan.get_current_task()

    assert next_task.description == "second"
    assert plan.tasks[0].status == TaskStatus.FAILED


def test_orchestrator_success_requires_all_tasks_complete(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("first")
    plan.add_task("second")

    def fake_planning_mode(user_request, coding_mode=False):
        return plan

    def fake_execution_mode(plan_obj, **kwargs):
        for t in plan_obj.tasks:
            t.status = TaskStatus.COMPLETED

    # Inject the fakes
    import rev.execution.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "planning_mode", fake_planning_mode)
    monkeypatch.setattr(orch_mod, "execution_mode", fake_execution_mode)
    monkeypatch.setattr(orch_mod, "concurrent_execution_mode", fake_execution_mode)
    # Disable routing effects
    # Patch router at its definition point
    import rev.execution.router as router_mod

    monkeypatch.setattr(router_mod, "TaskRouter", lambda: type("R", (), {"route": lambda self, *a, **k: type("Route", (), {"mode": "quick_edit", "reasoning": "", "enable_learning": False, "enable_research": False, "enable_review": False, "enable_validation": False, "review_strictness": "lenient", "parallel_workers": 1, "auto_approve": True, "enable_action_review": False, "enable_auto_fix": False, "research_depth": "shallow", "max_retries": 1})()})())
    monkeypatch.setattr(orch_mod, "research_codebase", _dummy_research)
    monkeypatch.setattr(orch_mod, "review_execution_plan", lambda *a, **k: None)
    monkeypatch.setattr(orch_mod, "validate_execution", lambda *a, **k: type("VR", (), {"overall_status": None, "results": [], "auto_fixed": []})())

    config = OrchestratorConfig(
        enable_learning=False,
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        auto_approve=True,
        parallel_workers=1,
    )

    orch = Orchestrator(Path("."), config)
    result = orch.execute("do things")
    assert result.success is True

    # Now mark one task failed and ensure success becomes False
    def fake_execution_mode_noop(plan_obj, **kwargs):
        return None

    monkeypatch.setattr(orch_mod, "execution_mode", fake_execution_mode_noop)
    monkeypatch.setattr(orch_mod, "concurrent_execution_mode", fake_execution_mode_noop)
    plan.tasks[1].status = TaskStatus.FAILED
    result = orch.execute("do things")
    assert result.success is False


def test_orchestrator_reports_failure_phase(monkeypatch):
    def failing_planning_mode(*_, **__):
        raise RuntimeError("planning blew up")

    import rev.execution.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "planning_mode", failing_planning_mode)
    monkeypatch.setattr(orch_mod, "execution_mode", lambda *a, **k: None)
    monkeypatch.setattr(orch_mod, "concurrent_execution_mode", lambda *a, **k: None)
    monkeypatch.setattr(orch_mod, "research_codebase", _dummy_research)
    monkeypatch.setattr(orch_mod, "review_execution_plan", lambda *a, **k: None)
    monkeypatch.setattr(orch_mod, "validate_execution", lambda *a, **k: None)

    import rev.execution.router as router_mod

    monkeypatch.setattr(
        router_mod,
        "TaskRouter",
        lambda: type(
            "R",
            (),
            {
                "route": lambda self, *a, **k: type(
                    "Route",
                    (),
                    {
                        "mode": "quick_edit",
                        "reasoning": "",
                        "enable_learning": False,
                        "enable_research": False,
                        "enable_review": False,
                        "enable_validation": False,
                        "review_strictness": "lenient",
                        "parallel_workers": 1,
                        "auto_approve": True,
                        "enable_action_review": False,
                        "enable_auto_fix": False,
                        "research_depth": "shallow",
                        "max_retries": 1,
                    },
                )()
            },
        )(),
    )

    config = OrchestratorConfig(
        enable_learning=False,
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        auto_approve=True,
        parallel_workers=1,
    )

    orch = Orchestrator(Path("."), config)
    result = orch.execute("do things")

    assert result.phase_reached == AgentPhase.PLANNING
    assert result.success is False
    assert any("planning blew up" in err for err in result.errors)


def test_concurrent_execution_mode_forces_sequential(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("single task")

    called = {"execution_mode": False}

    def fake_execution_mode(plan_obj, **_kwargs):
        called["execution_mode"] = True
        for task in plan_obj.tasks:
            task.status = TaskStatus.COMPLETED
        return True

    monkeypatch.setattr("rev.execution.executor.execution_mode", fake_execution_mode)

    result = concurrent_execution_mode(plan, max_workers=3, auto_approve=True)

    assert result is True
    assert called["execution_mode"] is True
    assert all(task.status == TaskStatus.COMPLETED for task in plan.tasks)


def test_orchestrator_retries_failed_attempts(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("first")
    plan.add_task("second")

    call_counter = {"planning": 0}

    def flaky_planning_mode(user_request, coding_mode=False):
        call_counter["planning"] += 1
        if call_counter["planning"] == 1:
            raise RuntimeError("first failure")
        return plan

    def completing_execution_mode(plan_obj, **kwargs):
        for task in plan_obj.tasks:
            task.status = TaskStatus.COMPLETED

    import rev.execution.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "planning_mode", flaky_planning_mode)
    monkeypatch.setattr(orch_mod, "execution_mode", completing_execution_mode)
    monkeypatch.setattr(orch_mod, "concurrent_execution_mode", completing_execution_mode)
    monkeypatch.setattr(orch_mod, "research_codebase", _dummy_research)
    monkeypatch.setattr(orch_mod, "review_execution_plan", lambda *a, **k: type("RR", (), {"decision": None})())
    monkeypatch.setattr(orch_mod, "validate_execution", lambda *a, **k: type("VR", (), {"overall_status": None, "results": [], "auto_fixed": []})())

    import rev.execution.router as router_mod

    monkeypatch.setattr(
        router_mod,
        "TaskRouter",
        lambda: type(
            "R",
            (),
            {
                "route": lambda self, *a, **k: type(
                    "Route",
                    (),
                    {
                        "mode": "quick_edit",
                        "reasoning": "",
                        "enable_learning": False,
                        "enable_research": False,
                        "enable_review": False,
                        "enable_validation": False,
                        "review_strictness": "lenient",
                        "parallel_workers": 1,
                        "auto_approve": True,
                        "enable_action_review": False,
                        "enable_auto_fix": False,
                        "research_depth": "deep",
                        "max_retries": 1,
                    },
                )()
            },
        )(),
    )

    config = OrchestratorConfig(
        enable_learning=False,
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        auto_approve=True,
        parallel_workers=1,
        max_retries=1,
    )

    orch = Orchestrator(Path("."), config)
    result = orch.execute("do things")

    assert call_counter["planning"] == 2
    assert result.success is True
    assert any("first failure" in err for err in result.errors)


def test_quick_security_check_reads_cmd_argument():
    warnings = _quick_security_check(
        tool_name="run_cmd",
        tool_args={"cmd": "echo test && rm -rf /tmp"},
        description="dangerous command",
    )
    assert warnings, "Expected warnings for dangerous run_cmd command"


def test_orchestrator_forces_deep_research(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("first")

    def fake_planning_mode(user_request, coding_mode=False):
        return plan

    def fake_execution_mode(plan_obj, **kwargs):
        for task in plan_obj.tasks:
            task.status = TaskStatus.COMPLETED

    research_invocation = {}

    def capturing_research_codebase(user_request, quick_mode=False, search_depth="shallow"):
        research_invocation.update(
            {"quick_mode": quick_mode, "search_depth": search_depth, "user_request": user_request}
        )
        return _dummy_research()

    import rev.execution.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "planning_mode", fake_planning_mode)
    monkeypatch.setattr(orch_mod, "execution_mode", fake_execution_mode)
    monkeypatch.setattr(orch_mod, "concurrent_execution_mode", fake_execution_mode)
    monkeypatch.setattr(orch_mod, "research_codebase", capturing_research_codebase)
    monkeypatch.setattr(orch_mod, "review_execution_plan", lambda *a, **k: type("RR", (), {"decision": None})())
    monkeypatch.setattr(orch_mod, "validate_execution", lambda *a, **k: type("VR", (), {"overall_status": None, "results": [], "auto_fixed": []})())

    import rev.execution.router as router_mod

    monkeypatch.setattr(
        router_mod,
        "TaskRouter",
        lambda: type(
            "R",
            (),
            {
                "route": lambda self, *a, **k: type(
                    "Route",
                    (),
                    {
                        "mode": "quick_edit",
                        "reasoning": "",
                        "enable_learning": False,
                        "enable_research": True,
                        "enable_review": False,
                        "enable_validation": False,
                        "review_strictness": "lenient",
                        "parallel_workers": 1,
                        "auto_approve": True,
                        "enable_action_review": False,
                        "enable_auto_fix": False,
                        "research_depth": "shallow",
                        "max_retries": 1,
                    },
                )()
            },
        )(),
    )

    config = OrchestratorConfig(
        enable_learning=False,
        enable_research=True,
        enable_review=False,
        enable_validation=False,
        auto_approve=True,
        parallel_workers=1,
        research_depth="medium",
    )

    orch = Orchestrator(Path("."), config)
    result = orch.execute("do things")

    assert result.success is True
    assert research_invocation["quick_mode"] is False
    assert research_invocation["search_depth"] == "deep"
