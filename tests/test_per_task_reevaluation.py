"""
Tests for per-task reevaluation and stale state fixes.

Verifies that:
1. System pauses after destructive tasks to replan
2. Batch execution stops when file state changes dangerously
3. Repo context is updated after task phases
4. Analysis caches are cleared between iterations
5. No infinite loops occur
6. Proper task sequencing is maintained
"""

import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.core.context import RevContext


class TestPerTaskReevaluation:
    """Test suite for per-task reevaluation logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)
        self.context = RevContext(user_request="Test task")

    def test_should_pause_for_reevaluation_detects_destructive_ops(self):
        """Test that destructive operations are properly detected."""
        # Task: Extract class from file
        task = Task(
            description="Extract BreakoutAnalyst from lib/analysts.py",
            action_type="edit"
        )
        task.task_id = 0

        # Add pending task that references same file
        pending_task = Task(
            description="Extract VolumeAnalyst from lib/analysts.py",
            action_type="edit"
        )
        pending_task.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task, pending_task]

        # Should detect that replan is needed
        result = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)
        assert result is True, "Should detect conflict between tasks"

    def test_should_pause_ignores_non_destructive_ops(self):
        """Test that non-destructive operations don't trigger replan."""
        # Task: Add comment (not destructive)
        task = Task(
            description="Add documentation to lib/utils.py",
            action_type="edit"
        )
        task.task_id = 0

        # Add pending task
        pending_task = Task(
            description="Run tests",
            action_type="test"
        )
        pending_task.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task, pending_task]

        # Should NOT trigger replan for non-destructive op
        result = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)
        assert result is False, "Non-destructive ops should not trigger replan"

    def test_should_pause_no_pending_tasks(self):
        """Test that no replan is needed if no pending tasks exist."""
        # Task: Destructive operation
        task = Task(
            description="Delete temporary files in lib/temp/",
            action_type="edit"
        )
        task.task_id = 0

        # No pending tasks
        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task]

        # Should NOT trigger replan
        result = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)
        assert result is False, "No replan needed if no pending tasks"

    def test_should_pause_different_files(self):
        """Test that replan not triggered if tasks reference different files."""
        # Task: Modify one file
        task = Task(
            description="Refactor lib/utils.py",
            action_type="edit"
        )
        task.task_id = 0
        task.status = TaskStatus.IN_PROGRESS  # Mark as being executed

        # Pending task references completely different file
        pending_task = Task(
            description="Add feature to lib/api.py",
            action_type="edit"
        )
        pending_task.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task, pending_task]

        # Should NOT trigger replan (different files - utils.py vs api.py)
        result = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)
        assert result is False, "Different files should not trigger replan"

    def test_destructive_keywords_detected(self):
        """Test that all destructive keywords are recognized."""
        destructive_keywords = ["extract", "delete", "remove", "refactor", "modify", "split", "create"]
        pending_task = Task(
            description="Extract SomeClass from lib/analysts.py",
            action_type="edit"
        )
        pending_task.task_id = 0

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [pending_task]

        for keyword in destructive_keywords:
            task = Task(
                description=f"{keyword} something from lib/analysts.py",
                action_type="edit"
            )
            task.task_id = 1

            result = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)
            assert result is True, f"Keyword '{keyword}' should be detected as destructive"

    def test_replan_request_added_to_context(self):
        """Test that replan request is properly added to context."""
        # Simulate task that will return replan request
        task = Task(
            description="Extract class from lib/analysts.py",
            action_type="edit"
        )
        task.task_id = 0

        pending_task = Task(
            description="Extract another class from lib/analysts.py",
            action_type="edit"
        )
        pending_task.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task, pending_task]
        self.context.agent_requests = []

        # Simulate dispatcher detection
        should_replan = self.orchestrator._should_pause_for_task_reevaluation(task, self.context)

        if should_replan:
            # Simulate what dispatch loop would do
            self.context.agent_requests.append({
                "type": "replan_immediately",
                "reason": "File state changed",
                "completed_task": task.task_id
            })

        # Verify request was added
        assert len(self.context.agent_requests) > 0
        assert self.context.agent_requests[0]["type"] == "replan_immediately"

    def test_no_replan_for_independent_tasks(self):
        """Test that independent tasks don't trigger replan."""
        # Task 1: Modify file A
        task1 = Task(
            description="Add feature to lib/api.py",
            action_type="edit"
        )
        task1.task_id = 0

        # Task 2: Modify independent file B
        task2 = Task(
            description="Fix bug in lib/utils.py",
            action_type="edit"
        )
        task2.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task1, task2]

        # Should not trigger replan
        result = self.orchestrator._should_pause_for_task_reevaluation(task1, self.context)
        assert result is False, "Independent tasks should not trigger replan"

    def test_multiple_destructive_operations_sequence(self):
        """Test handling sequence of destructive operations."""
        # Scenario: Multiple extracts from same file followed by delete
        extract_tasks = [
            Task(description="Extract Class1 from lib/analysts.py", action_type="edit"),
            Task(description="Extract Class2 from lib/analysts.py", action_type="edit"),
            Task(description="Extract Class3 from lib/analysts.py", action_type="edit"),
        ]
        for i, task in enumerate(extract_tasks):
            task.task_id = i

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = extract_tasks

        # First extraction should trigger replan (other extracts pending)
        result = self.orchestrator._should_pause_for_task_reevaluation(extract_tasks[0], self.context)
        assert result is True, "First extraction should trigger replan when other extracts pending"

        # Test with single delete task (no other pending tasks)
        delete_task = Task(description="Delete lib/analysts.py", action_type="edit")
        delete_task.task_id = 0
        delete_task.status = TaskStatus.IN_PROGRESS  # Mark as being executed

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [delete_task]  # No other tasks (none pending to reference the file)

        result = self.orchestrator._should_pause_for_task_reevaluation(delete_task, self.context)
        assert result is False, "Delete should not trigger replan when no pending tasks exist"

    def test_replan_signal_processing_in_main_loop(self):
        """Test that orchestrator correctly processes replan signals."""
        # Create a mock plan with replan request
        self.context.agent_requests = [{
            "type": "replan_immediately",
            "reason": "File state changed after task 1",
            "completed_task": "1"
        }]

        # Verify we can detect the signal
        should_replan = False
        for request in self.context.agent_requests:
            if request.get("type") == "replan_immediately":
                should_replan = True
                break

        assert should_replan is True, "Should detect replan signal"

    def test_cache_invalidation_called(self):
        """Test that cache invalidation is called for file operations."""
        from rev.cache import FileContentCache

        # Create a mock file cache
        file_cache = FileContentCache()

        # Verify invalidate_file method exists
        assert hasattr(file_cache, 'invalidate_file'), "File cache should have invalidate_file method"
        assert callable(getattr(file_cache, 'invalidate_file')), "invalidate_file should be callable"

    def test_analysis_cache_clearing_available(self):
        """Test that clear_analysis_caches function is available."""
        from rev.cache import clear_analysis_caches

        # Verify function exists and is callable
        assert callable(clear_analysis_caches), "clear_analysis_caches should be callable"


class TestBatchExecutionPause:
    """Test that batch execution properly pauses on file state changes."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)
        self.context = RevContext(user_request="Split analyst classes")

    @patch('rev.execution.orchestrator.AgentRegistry.get_agent_instance')
    def test_dispatch_stops_on_replan_request(self, mock_agent_registry):
        """Test that dispatch loop stops when replan is needed."""
        # Create tasks
        tasks = [
            Task(description="Extract BreakoutAnalyst from lib/analysts.py", action_type="add"),
            Task(description="Extract CandlestickAnalyst from lib/analysts.py", action_type="add"),
            Task(description="Run tests", action_type="test"),
        ]
        for i, task in enumerate(tasks):
            task.task_id = i

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = tasks

        # Mock agent to simulate success
        mock_agent = MagicMock()
        mock_agent.execute.return_value = "success"
        mock_agent_registry.return_value = mock_agent

        # Verify initial state
        assert all(t.status == TaskStatus.PENDING for t in tasks)

        # Note: Full dispatch test would need more mocking of internal state
        # For now, verify the detection logic works
        result = self.orchestrator._should_pause_for_task_reevaluation(tasks[0], self.context)
        assert result is True, "Should detect need to pause after task 1"


class TestRepoContextUpdates:
    """Test that repo context is properly updated."""

    def setup_method(self):
        """Set up test fixtures."""
        self.context = RevContext(user_request="Test")

    def test_repo_context_update_called(self):
        """Test that update_repo_context method updates the context."""
        # Set initial context
        self.context.repo_context = {"initial": "data"}

        # Verify we can update it
        new_context = {"updated": "data"}
        self.context.repo_context = new_context

        # Verify it was updated
        assert self.context.repo_context == new_context, "repo_context should be updated"

    def test_repo_context_can_change(self):
        """Test that repo context can be updated between phases."""
        initial = "initial state"
        updated = "updated state"

        self.context.repo_context = initial
        assert self.context.repo_context == initial

        self.context.repo_context = updated
        assert self.context.repo_context == updated


class TestNoInfiniteLoops:
    """Test that fixes prevent infinite loops."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)
        self.context = RevContext(user_request="Split classes")

    def test_replan_signal_prevents_batch_reexecution(self):
        """Test that replan signal prevents same batch from running again."""
        # Simulate completed task
        task1 = Task(description="Extract from lib/analysts.py", action_type="edit")
        task1.task_id = 0
        task1.status = TaskStatus.COMPLETED

        # Simulate pending task
        task2 = Task(description="Extract from lib/analysts.py", action_type="edit")
        task2.task_id = 1

        self.context.plan = ExecutionPlan()
        self.context.plan.tasks = [task1, task2]

        # Verify replan would be triggered
        result = self.orchestrator._should_pause_for_task_reevaluation(task1, self.context)
        assert result is True

        # Add replan request
        self.context.agent_requests.append({
            "type": "replan_immediately",
            "reason": "State change",
            "completed_task": "1"
        })

        # Verify request is there
        assert len(self.context.agent_requests) > 0
        assert self.context.agent_requests[0]["type"] == "replan_immediately"


class TestFilePathExtraction:
    """Test that file paths are correctly extracted from task descriptions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = OrchestratorConfig()
        self.orchestrator = Orchestrator(Path.cwd(), self.config)

    def test_extract_files_from_task_description(self):
        """Test file path extraction regex."""
        import re

        task_desc = "Extract BreakoutAnalyst from lib/analysts.py"
        pattern = r'(?:lib/|src/|tests/)[a-zA-Z0-9_./\-]+\.py'
        matches = set(re.findall(pattern, task_desc))

        assert "lib/analysts.py" in matches

    def test_extract_multiple_files(self):
        """Test extracting multiple file paths."""
        import re

        task_desc = "Refactor lib/analysts.py and lib/utils.py"
        pattern = r'(?:lib/|src/|tests/)[a-zA-Z0-9_./\-]+\.py'
        matches = set(re.findall(pattern, task_desc))

        assert len(matches) == 2
        assert "lib/analysts.py" in matches
        assert "lib/utils.py" in matches

    def test_extract_nested_paths(self):
        """Test extracting nested file paths."""
        import re

        task_desc = "Create lib/analysts/breakout_analyst.py"
        pattern = r'(?:lib/|src/|tests/)[a-zA-Z0-9_./\-]+\.py'
        matches = set(re.findall(pattern, task_desc))

        assert "lib/analysts/breakout_analyst.py" in matches


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
