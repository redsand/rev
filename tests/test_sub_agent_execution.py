import pytest
from unittest.mock import MagicMock, patch

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev import config
from rev.core.context import RevContext # Import RevContext
from rev.agents.code_writer import CodeWriterAgent # Import CodeWriterAgent (for mocking)
from rev.agents.test_executor import TestExecutorAgent # Import TestExecutorAgent (for mocking)


@pytest.fixture
def sub_agent_config():
    """Fixture to set execution mode to sub-agent."""
    original_mode = config.EXECUTION_MODE
    original_ucct = config.UCCT_ENABLED
    config.EXECUTION_MODE = "sub-agent"
    config.UCCT_ENABLED = False
    # Disable other phases to isolate execution
    yield OrchestratorConfig(
        enable_research=False, 
        enable_review=False, 
        enable_validation=False,
        enable_learning=False,
        enable_prompt_optimization=False,
        enable_context_guard=False
    )
    config.EXECUTION_MODE = original_mode
    config.UCCT_ENABLED = original_ucct


# Mock implementation for CodeWriterAgent.execute that can simulate replan request
def mock_code_writer_execute_replan(self, task: Task, context: RevContext):
    if "Fail this task to trigger replan" in task.description:
        error_msg = "Simulated failure for replan request."
        context.add_error(f"CodeWriterAgent: {error_msg}")
        self.request_replan(context, "Simulated LLM tool call error", detailed_reason=error_msg)
        # Note: In a real scenario, this might not raise an exception immediately,
        # but return control to orchestrator. For testing, raising ensures flow.
        raise Exception(error_msg)
    return "Task completed by CodeWriterAgent."

def test_sub_agent_dispatch(monkeypatch, sub_agent_config):
    """
    Tests that the orchestrator correctly dispatches tasks to sub-agents.
    """
    # 1. Mock the planner/LLM responses
    mock_responses = [
        # First turn: Orchestrator calls _determine_next_action
        {"message": {"role": "assistant", "content": "[ADD] Write 'hello' to 'world.txt'"}},
        # Second turn: Orchestrator calls _determine_next_action
        {"message": {"role": "assistant", "content": "[TEST] Run tests for 'world.txt'"}},
    ]
    
    def mock_chat_side_effect(*args, **kwargs):
        if mock_responses:
            return mock_responses.pop(0)
        return {"message": {"role": "assistant", "content": "GOAL_ACHIEVED"}}

    monkeypatch.setattr("rev.execution.orchestrator.ollama_chat", mock_chat_side_effect)

    # 2. Mock the dispatch method to avoid real agent calls
    def mock_dispatch_fn(context, task=None):
        if task is None and context.plan and context.plan.tasks:
            task = context.plan.tasks[0]
        if task:
            task.status = TaskStatus.COMPLETED
        return True

    mock_dispatch = MagicMock(side_effect=mock_dispatch_fn)
    monkeypatch.setattr("rev.execution.orchestrator.Orchestrator._dispatch_to_sub_agents", mock_dispatch)
    
    # 3. Mock the verification method to always pass
    from rev.execution.quick_verify import VerificationResult
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", 
                        lambda *args, **kwargs: VerificationResult(passed=True, message="Success", details={}))
    
    # 4. Run the orchestrator
    orchestrator = Orchestrator(project_root=config.ROOT, config=sub_agent_config)
    # Inject an empty history so it doesn't try to load anything
    orchestrator.context = RevContext(user_request="test sub-agent dispatch")
    orchestrator.context.work_history = ["[COMPLETED] initial workspace examination"] # Bypass forced exam
    
    result = orchestrator.execute(user_request="test sub-agent dispatch")

    # 5. Assertions
    assert result.success is True, f"Orchestrator failed with errors: {result.errors}"
    # Expect 3 calls: initial workspace examination + 2 tasks from LLM
    assert mock_dispatch.call_count >= 2


def test_sub_agent_replan_request(monkeypatch):
    """
    Tests that the orchestrator correctly detects a replan request from a sub-agent
    and triggers the adaptive replanning mechanism.
    """
    config.EXECUTION_MODE = "sub-agent"
    config.UCCT_ENABLED = False
    orchestrator_config = OrchestratorConfig(
        enable_research=False, # Disable for this specific test flow
        enable_review=False,
        enable_validation=False,
        enable_learning=False,
        enable_prompt_optimization=False,
        enable_context_guard=False,
        adaptive_replan_attempts=1 # Allow at least one adaptive replan attempt
    )

    # Mock the planner/LLM
    mock_responses = [
        {"message": {"role": "assistant", "content": "[ADD] First successful task"}},
        {"message": {"role": "assistant", "content": "[ADD] Fail this task to trigger replan"}},
        # Next turn after failure: should be replanning or another action
        {"message": {"role": "assistant", "content": "[ADD] Recovery task"}},
        {"message": {"role": "assistant", "content": "GOAL_ACHIEVED"}}
    ]
    
    def mock_chat_side_effect(*args, **kwargs):
        if mock_responses:
            return mock_responses.pop(0)
        return {"message": {"role": "assistant", "content": "GOAL_ACHIEVED"}}

    monkeypatch.setattr("rev.execution.orchestrator.ollama_chat", mock_chat_side_effect)
    
    # Mock dispatch to simulate replan request on specific task
    def mock_dispatch_fn(context, task=None):
        if task is None and context.plan and context.plan.tasks:
            task = context.plan.tasks[0]
        
        if task and "Fail this task to trigger replan" in task.description:
            context.add_agent_request("REPLAN_REQUEST", {"agent": "CodeWriter", "reason": "Simulated LLM tool call error"})
            task.status = TaskStatus.FAILED
            return False
        
        if task:
            task.status = TaskStatus.COMPLETED
        return True
        
    mock_dispatch = MagicMock(side_effect=mock_dispatch_fn)
    monkeypatch.setattr("rev.execution.orchestrator.Orchestrator._dispatch_to_sub_agents", mock_dispatch)
    
    # Mock verification
    from rev.execution.quick_verify import VerificationResult
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", 
                        lambda *args, **kwargs: VerificationResult(passed=True, message="Success", details={}))

    orchestrator = Orchestrator(project_root=config.ROOT, config=orchestrator_config)
    # Inject an empty history so it doesn't try to load anything
    orchestrator.context = RevContext(user_request="test sub-agent dispatch")
    orchestrator.context.work_history = ["[COMPLETED] initial workspace examination"] # Bypass forced exam

    result = orchestrator.execute(user_request="test replan request from agent")

    # Assertions
    assert "agent_request_triggered_replan" in result.agent_insights.get("orchestrator", {}), \
        "Orchestrator should record that an agent request triggered replan."
    
    assert result.agent_insights["orchestrator"]["agent_request_triggered_replan"]["reason"] == "Simulated LLM tool call error", \
        "The reason for the replan request should be recorded."