from pathlib import Path

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import TaskStatus
from rev.core.context import RevContext, ResourceBudget
from rev.execution.quick_verify import VerificationResult


def test_inconclusive_edit_injects_test_task(monkeypatch):
    base = Path("tmp_test/inconclusive_injection").resolve()
    base.mkdir(parents=True, exist_ok=True)
    config = OrchestratorConfig(
        enable_research=False,
        enable_review=False,
        enable_validation=False,
        enable_learning=False,
        enable_prompt_optimization=False,
        enable_context_guard=False,
    )
    orchestrator = Orchestrator(base, config)
    orchestrator.context = RevContext(user_request="edit foo.txt")
    orchestrator.context.resource_budget = ResourceBudget()
    orchestrator.context.work_history = ["[COMPLETED] initial workspace examination"]

    tasks_seen = []

    def mock_dispatch(context, task=None):
        if task is None and context.plan and context.plan.tasks:
            task = context.plan.tasks[0]
        if task:
            tasks_seen.append((task.action_type, task.description))
            task.status = TaskStatus.COMPLETED
        return True

    monkeypatch.setattr(orchestrator, "_dispatch_to_sub_agents", mock_dispatch)
    monkeypatch.setattr(orchestrator, "_is_completion_grounded", lambda *_a, **_k: (True, ""))

    def mock_llm(*_args, **_kwargs):
        mock_llm.calls += 1
        if mock_llm.calls == 1:
            return {"message": {"content": "[edit] Update foo.txt"}}
        return {"message": {"content": "GOAL_ACHIEVED"}}

    mock_llm.calls = 0
    monkeypatch.setattr("rev.execution.orchestrator.ollama_chat", mock_llm)

    def mock_verify(task, _context):
        mock_verify.calls += 1
        if mock_verify.calls == 1:
            return VerificationResult(
                passed=False,
                inconclusive=True,
                message="Cannot verify edit",
                details={"file_path": "foo.txt", "suggestion": "Run pytest"},
                should_replan=True,
            )
        return VerificationResult(passed=True, message="ok", details={})

    mock_verify.calls = 0
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", mock_verify)

    result = orchestrator._continuous_sub_agent_execution(
        "edit foo.txt",
        coding_mode=True,
    )

    assert result is True
    assert tasks_seen
    assert any(action == "edit" for action, _ in tasks_seen)
    assert any(action == "test" for action, _ in tasks_seen)
    test_task = next(desc for action, desc in tasks_seen if action == "test")
    assert "pytest" in test_task.lower()
