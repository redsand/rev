from rev import config
from rev.core.context import RevContext
from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.execution.quick_verify import VerificationResult
from rev.models.task import TaskStatus


def test_orchestrator_forces_test_after_tdd(monkeypatch) -> None:
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
    orchestrator.context = RevContext(user_request="tdd flow")
    orchestrator.context.work_history = ["[COMPLETED] initial workspace examination"]
    orchestrator.context.load_history = lambda: ["[COMPLETED] initial workspace examination"]
    orchestrator.context.agent_state["tdd_require_test"] = True

    executed = []

    def fake_determine_next_action(*_args, **_kwargs):
        return None

    def fake_dispatch(context, task=None):
        if task is None:
            return False
        task.status = TaskStatus.COMPLETED
        executed.append(task)
        return True

    def fake_verify(task, context):
        if task.action_type == "test":
            context.agent_state["tdd_require_test"] = False
        return VerificationResult(passed=True, message="ok", details={})

    monkeypatch.setattr(orchestrator, "_determine_next_action", fake_determine_next_action)
    monkeypatch.setattr(orchestrator, "_dispatch_to_sub_agents", fake_dispatch)
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", fake_verify)

    assert orchestrator._continuous_sub_agent_execution("tdd flow", coding_mode=True) is True
    assert any(task.action_type == "test" for task in executed)
