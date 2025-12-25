from rev import config
from rev.core.context import RevContext
from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task, TaskStatus


def _make_orchestrator(monkeypatch) -> Orchestrator:
    monkeypatch.setattr(config, "EXECUTION_MODE", "sub-agent")
    monkeypatch.setattr(config, "UCCT_ENABLED", False)
    orch_config = OrchestratorConfig(
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        enable_learning=False,
        enable_prompt_optimization=False,
        enable_context_guard=False,
    )
    orchestrator = Orchestrator(project_root=config.ROOT, config=orch_config)
    orchestrator.context = RevContext(user_request="test diagnostics")
    orchestrator.context.work_history = ["[COMPLETED] initial workspace examination"]
    orchestrator.context.load_history = lambda: ["[COMPLETED] initial workspace examination"]
    return orchestrator


def test_injects_diagnostics_after_repeated_failure(monkeypatch) -> None:
    orchestrator = _make_orchestrator(monkeypatch)
    tasks = [
        Task(description="Edit src/app.py to fix issue", action_type="edit"),
        Task(description="Edit src/app.py to fix issue", action_type="edit"),
        None,
    ]

    def fake_determine_next_action(*_args, **_kwargs):
        return tasks.pop(0)

    executed = []

    def fake_dispatch(context, task=None):
        if task is None:
            return False
        task.status = TaskStatus.COMPLETED
        executed.append(task)
        return True

    def fake_verify(task, _context):
        if task.action_type == "edit":
            return VerificationResult(passed=False, message="Boom", details={})
        return VerificationResult(passed=True, message="ok", details={})

    monkeypatch.setattr(orchestrator, "_determine_next_action", fake_determine_next_action)
    monkeypatch.setattr(orchestrator, "_dispatch_to_sub_agents", fake_dispatch)
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", fake_verify)

    assert orchestrator._continuous_sub_agent_execution("test diagnostics", coding_mode=True) is True
    assert any("get_file_info" in task.description for task in executed)


def test_fast_exit_on_repeated_failure_signature(monkeypatch) -> None:
    orchestrator = _make_orchestrator(monkeypatch)
    tasks = [
        Task(description="Edit src/app.py to fix issue (attempt 1)", action_type="edit"),
        Task(description="Edit src/app.py to fix issue (attempt 2)", action_type="edit"),
        Task(description="Edit src/app.py to fix issue (attempt 3)", action_type="edit"),
        None,
    ]

    def fake_determine_next_action(*_args, **_kwargs):
        return tasks.pop(0)

    def fake_dispatch(context, task=None):
        if task is None:
            return False
        task.status = TaskStatus.COMPLETED
        return True

    def fake_verify(task, _context):
        if task.action_type == "edit":
            return VerificationResult(passed=False, message="Boom", details={})
        return VerificationResult(passed=True, message="ok", details={})

    monkeypatch.setattr(orchestrator, "_determine_next_action", fake_determine_next_action)
    monkeypatch.setattr(orchestrator, "_dispatch_to_sub_agents", fake_dispatch)
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", fake_verify)

    assert orchestrator._continuous_sub_agent_execution("test diagnostics", coding_mode=True) is False
    assert any("Repeated failure signature" in err for err in orchestrator.context.errors)
