import pathlib
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.execution.reviewer import _quick_security_check
from rev.models.task import ExecutionPlan, TaskStatus


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
    monkeypatch.setattr(orch_mod, "research_codebase", lambda *a, **k: None)
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


def test_quick_security_check_reads_cmd_argument():
    warnings = _quick_security_check(
        tool_name="run_cmd",
        tool_args={"cmd": "echo test && rm -rf /tmp"},
        description="dangerous command",
    )
    assert warnings, "Expected warnings for dangerous run_cmd command"
