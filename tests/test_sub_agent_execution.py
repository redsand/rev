import pytest
from unittest.mock import MagicMock, patch

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import ExecutionPlan, Task
from rev import config
from rev.core.context import RevContext # Import RevContext
from rev.agents.code_writer import CodeWriterAgent # Import CodeWriterAgent (for mocking)
from rev.agents.test_executor import TestExecutorAgent # Import TestExecutorAgent (for mocking)


@pytest.fixture
def sub_agent_config():
    """Fixture to set execution mode to sub-agent."""
    original_mode = config.EXECUTION_MODE
    config.EXECUTION_MODE = "sub-agent"
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
    # 1. Create a mock plan
    plan = ExecutionPlan()
    plan.add_task("Write 'hello' to 'world.txt'", "add")
    plan.add_task("Run tests for 'world.txt'", "test")

    # 2. Mock the planner to return this plan
    monkeypatch.setattr("rev.execution.orchestrator.planning_mode", lambda *args, **kwargs: plan)
    
    # 3. Mock the dispatch method to avoid real agent calls
    mock_dispatch = MagicMock(return_value=True)
    monkeypatch.setattr("rev.execution.orchestrator.Orchestrator._dispatch_to_sub_agents", mock_dispatch)
    
    # 4. Mock the verification method to always pass
    from rev.execution.quick_verify import VerificationResult
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", 
                        lambda *args, **kwargs: VerificationResult(passed=True, message="Success", details={}))
    
    # 5. Run the orchestrator
    orchestrator = Orchestrator(project_root=config.ROOT, config=sub_agent_config)
    result = orchestrator.execute(user_request="test sub-agent dispatch")

    # 6. Assertions
    assert result.success is True, f"Orchestrator failed with errors: {result.errors}"
    assert mock_dispatch.call_count >= 2


def test_sub_agent_replan_request(monkeypatch):
    """
    Tests that the orchestrator correctly detects a replan request from a sub-agent
    and triggers the adaptive replanning mechanism.
    """
    config.EXECUTION_MODE = "sub-agent"
    orchestrator_config = OrchestratorConfig(
        enable_research=False, # Disable for this specific test flow
        enable_review=False,
        enable_validation=False,
        enable_learning=False,
        enable_prompt_optimization=False,
        enable_context_guard=False,
        adaptive_replan_attempts=1 # Allow at least one adaptive replan attempt
    )

    plan = ExecutionPlan()
    plan.add_task("First successful task", "add")
    plan.add_task("Fail this task to trigger replan", "add") 

    # Mock the planner
    monkeypatch.setattr("rev.execution.orchestrator.planning_mode", MagicMock(return_value=plan))
    
    # Mock dispatch to simulate replan request on specific task
    def mock_dispatch(self, context, task=None):
        if task and "Fail this task to trigger replan" in task.description:
            context.add_agent_request("REPLAN_REQUEST", {"agent": "CodeWriter", "reason": "Simulated LLM tool call error"})
            return False
        return True
        
    monkeypatch.setattr("rev.execution.orchestrator.Orchestrator._dispatch_to_sub_agents", mock_dispatch)
    
    # Mock verification
    from rev.execution.quick_verify import VerificationResult
    monkeypatch.setattr("rev.execution.orchestrator.verify_task_execution", 
                        lambda *args, **kwargs: VerificationResult(passed=True, message="Success", details={}))

    orchestrator = Orchestrator(project_root=config.ROOT, config=orchestrator_config)
    result = orchestrator.execute(user_request="test replan request from agent")

    # Assertions
    assert "agent_request_triggered_replan" in result.agent_insights.get("orchestrator", {}), \
        "Orchestrator should record that an agent request triggered replan."
    
    assert result.agent_insights["orchestrator"]["agent_request_triggered_replan"]["reason"] == "Simulated LLM tool call error", \
        "The reason for the replan request should be recorded."