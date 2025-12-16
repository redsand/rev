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
        enable_learning=False
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
    
    # 3. Mock the sub-agents' execute methods
    mock_code_writer = MagicMock(return_value="File 'world.txt' created.")
    mock_test_executor = MagicMock(return_value="Tests passed.")
    
    # Since the agents are imported inside the dispatch function, we need to patch them there.
    # We patch the class's execute method.
    monkeypatch.setattr("rev.agents.code_writer.CodeWriterAgent.execute", mock_code_writer)
    monkeypatch.setattr("rev.agents.test_executor.TestExecutorAgent.execute", mock_test_executor)
    
    # 4. Run the orchestrator
    orchestrator = Orchestrator(project_root=config.ROOT, config=sub_agent_config)
    result = orchestrator.execute(user_request="test sub-agent dispatch")

    # 5. Assertions
    assert result.success is True, f"Orchestrator failed with errors: {result.errors}"
    
    # Check that the correct agents were called
    assert mock_code_writer.call_count == 1
    assert mock_test_executor.call_count == 1
    
    # Check that they were called with the correct tasks
    code_writer_call_args = mock_code_writer.call_args
    assert code_writer_call_args[0][0].description == "Write 'hello' to 'world.txt'"
    
    test_executor_call_args = mock_test_executor.call_args
    assert test_executor_call_args[0][0].description == "Run tests for 'world.txt'"


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
        adaptive_replan_attempts=1 # Allow at least one adaptive replan attempt
    )

    plan = ExecutionPlan()
    plan.add_task("Write 'hello' to 'world.txt'", "add")
    plan.add_task("Fail this task to trigger replan", "add") # This task will cause CodeWriterAgent to request replan
    plan.add_task("Run tests for 'world.txt'", "test")

    # Mock the planner to return this plan initially and for subsequent replans
    monkeypatch.setattr("rev.execution.orchestrator.planning_mode", MagicMock(return_value=plan))
    
    # Use the custom mock execute method for CodeWriterAgent
    monkeypatch.setattr("rev.agents.code_writer.CodeWriterAgent.execute", mock_code_writer_execute_replan)
    
    # Mock TestExecutorAgent.execute for the successful task
    monkeypatch.setattr("rev.agents.test_executor.TestExecutorAgent.execute", MagicMock(return_value="Tests passed."))

    orchestrator = Orchestrator(project_root=config.ROOT, config=orchestrator_config)
    result = orchestrator.execute(user_request="test replan request from agent")

    # Assertions
    # The orchestrator will detect the replan request, set execution_success=False,
    # and then _should_adaptively_replan will return True (since adaptive_replan_attempts > 0 and execution_success is False).
    # It will then try to regenerate the plan. Since planning_mode is mocked to return the same failing plan,
    # it will enter the execute loop again, fail again, and eventually exhaust adaptive_replan_attempts, leading to overall failure.
    assert result.success is False, "Orchestrator should indicate overall failure after exhausting replan attempts."
    
    assert "agent_request_triggered_replan" in result.agent_insights.get("orchestrator", {}), \
        "Orchestrator should record that an agent request triggered replan."
    
    assert result.agent_insights["orchestrator"]["agent_request_triggered_replan"]["reason"] == "Simulated LLM tool call error", \
        "The reason for the replan request should be recorded."
    
    # Verify that planning_mode was called multiple times (initial plan + 1 adaptive replan)
    assert orchestrator.context.plan is not None
    # Depending on the loop, planning_mode might be called more than twice.
    # Initial call, then potentially one for adaptive replan.
    # With adaptive_replan_attempts=1, it will be called once for initial, then once for replan.
    assert orchestrator.context.agent_insights.get("orchestrator", {}).get("adaptive_replan_count", 0) >= 1, \
        "At least one adaptive replan attempt should have occurred."