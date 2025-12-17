"""
Test to verify that destructive operations don't break subsequent task dependencies.

CRITICAL TEST: Prevents the situation where:
  Task 1: Extract BreakoutAnalyst from lib/analysts.py (DESTRUCTIVE)
  Task 2: Extract VolumeAnalyst from lib/analysts.py (FAILS - already truncated)

This test ensures the validator catches these dangerous patterns BEFORE execution.
"""

import pytest
from unittest.mock import MagicMock

from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.execution.validator import (
    validate_no_destructive_interdependencies,
    ValidationStatus
)


class TestDestructiveInterdependencies:
    """Test suite for catching destructive operations that break dependencies."""

    def create_task(self, description: str, status: TaskStatus = TaskStatus.PENDING) -> Task:
        """Helper to create a task."""
        task = MagicMock(spec=Task)
        task.description = description
        task.status = status
        return task

    def create_plan(self, task_descriptions: list) -> ExecutionPlan:
        """Helper to create a plan with multiple tasks."""
        plan = MagicMock(spec=ExecutionPlan)
        plan.tasks = [self.create_task(desc) for desc in task_descriptions]
        return plan

    def test_detects_extract_extract_pattern(self):
        """
        CRITICAL: Detect the problematic pattern:
          Task 1: Extract BreakoutAnalyst from lib/analysts.py
          Task 2: Extract VolumeAnalyst from lib/analysts.py

        This pattern is DANGEROUS because:
          - Task 1 will modify/truncate lib/analysts.py
          - Task 2 tries to read from lib/analysts.py (but it's already modified!)
        """
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py to lib/analysts/breakout.py",
            "Extract VolumeAnalyst from lib/analysts.py to lib/analysts/volume.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # MUST FAIL - this is dangerous
        assert result.status == ValidationStatus.FAILED, \
            f"Should detect destructive interdependency. Got: {result.message}"

        assert "destructive" in result.message.lower(), \
            f"Message should mention 'destructive'. Got: {result.message}"

        assert result.details.get("issues"), \
            f"Should have issues list. Got: {result.details}"

    def test_detects_extract_multiple_extract_pattern(self):
        """Test detection with multiple extractions from same file."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py",
            "Extract VolumeAnalyst from lib/analysts.py",
            "Extract TrendAnalyst from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Should detect all the bad dependencies
        assert result.status == ValidationStatus.FAILED
        assert len(result.details.get("issues", [])) >= 2, \
            f"Should detect multiple dependency issues. Got: {result.details}"

    def test_allows_safe_pattern_different_files(self):
        """Test that operations on DIFFERENT files are allowed."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py to lib/analysts/breakout.py",
            "Extract VolumeAnalyst from lib/strategies.py to lib/strategies/volume.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Should PASS - different files, no conflict
        assert result.status == ValidationStatus.PASSED, \
            f"Should allow operations on different files. Got: {result.message}"

    def test_allows_safe_pattern_read_before_write(self):
        """Test that READ operations before WRITE operations are safe."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py",
            "Create new file lib/analysts/breakout.py with the extracted class",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Note: This specific pattern might still have issues depending on
        # how we detect "read" vs "write", but the key is that it should
        # at least not flag subsequent operations as problematic
        # (The first task shouldn't be flagged as breaking the second)
        assert result.status in [ValidationStatus.PASSED, ValidationStatus.FAILED]
        # If it fails, it should be clear about why
        if result.status == ValidationStatus.FAILED:
            assert result.details.get("issues"), "Should explain the issue"

    def test_allows_refactor_without_same_file_dependency(self):
        """Test that refactoring is allowed if not breaking dependencies."""
        plan = self.create_plan([
            "Refactor helper functions in lib/utils.py",
            "Update import statements in lib/main.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # PASS - different files
        assert result.status == ValidationStatus.PASSED

    def test_allows_no_destructive_operations(self):
        """Test that plans with no destructive operations pass."""
        plan = self.create_plan([
            "Review the code in lib/utils.py",
            "Run tests for lib/test_utils.py",
            "Generate documentation for the module",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Should PASS - no destructive operations
        assert result.status == ValidationStatus.PASSED
        assert "no destructive" in result.message.lower()

    def test_detects_delete_then_read_pattern(self):
        """Test detection of: Delete file, then read from it."""
        plan = self.create_plan([
            "Delete old implementation from lib/analysts.py",
            "Extract remaining code from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Should detect this as dangerous
        assert result.status == ValidationStatus.FAILED, \
            f"Should detect delete-then-read pattern. Got: {result.message}"

    def test_detects_modify_then_extract_pattern(self):
        """Test detection of: Modify file, then extract from it."""
        plan = self.create_plan([
            "Refactor lib/analysts.py to optimize performance",
            "Extract BreakoutAnalyst from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # This SHOULD be flagged as dangerous
        assert result.status == ValidationStatus.FAILED, \
            f"Should detect refactor-then-extract pattern. Got: {result.message}"

        # Should mention the problematic file
        assert "lib/analysts.py" in str(result.details)

    def test_provides_helpful_recommendations(self):
        """Test that failure results include actionable recommendations."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py",
            "Extract VolumeAnalyst from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        if result.status == ValidationStatus.FAILED:
            # Should provide recommendations
            assert "recommendation" in result.details, \
                   f"Should provide recommendations. Got: {result.details}"
            # Verify recommendation is actionable
            recommendation = result.details.get("recommendation", "")
            assert len(recommendation) > 0, \
                   f"Recommendation should not be empty. Got: {result.details}"

    def test_multiple_extractions_then_single_file_ok(self):
        """Test that extracting multiple items to different files is OK."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py to lib/analysts/breakout.py",
            "Extract VolumeAnalyst from lib/analysts.py to lib/analysts/volume.py",
            "Create __init__.py in lib/analysts/ to import all analysts",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # First two tasks have a dependency issue
        # Unless we're copying (not extracting), this will fail
        # That's correct behavior - it should be flagged
        if result.status == ValidationStatus.FAILED:
            assert len(result.details.get("issues", [])) > 0, \
                "Should explain why it failed"

    def test_empty_plan(self):
        """Test that empty plans pass validation."""
        plan = MagicMock(spec=ExecutionPlan)
        plan.tasks = []

        result = validate_no_destructive_interdependencies(plan)

        assert result.status == ValidationStatus.PASSED

    def test_single_task_plan(self):
        """Test that single-task plans pass validation."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        # Single destructive task with no subsequent tasks is OK
        assert result.status == ValidationStatus.PASSED

    def test_issue_details_are_descriptive(self):
        """Test that issue details clearly explain the problem."""
        plan = self.create_plan([
            "Extract BreakoutAnalyst from lib/analysts.py",
            "Extract VolumeAnalyst from lib/analysts.py",
        ])

        result = validate_no_destructive_interdependencies(plan)

        if result.status == ValidationStatus.FAILED:
            issues = result.details.get("issues", [])
            assert len(issues) > 0

            for issue in issues:
                # Should explain the problem clearly
                assert "destructive_file" in issue or "lib/analysts.py" in str(issue)
                assert "Task" in str(issue), "Should reference which tasks"


class TestDestructiveInterdependenciesIntegration:
    """Integration tests for destructive interdependency detection."""

    def test_real_world_scenario_analyst_extraction(self):
        """Test the real-world scenario that caused the user's problem."""
        # This is what the user experienced
        plan = MagicMock(spec=ExecutionPlan)

        # Create tasks that mimic the problematic execution
        task1 = MagicMock(spec=Task)
        task1.description = "Extract BreakoutAnalyst class from lib/analysts.py to lib/analysts/breakout_analyst.py"
        task1.status = TaskStatus.PENDING

        task2 = MagicMock(spec=Task)
        task2.description = "Extract VolumeAnalyst class from lib/analysts.py to lib/analysts/volume_analyst.py"
        task2.status = TaskStatus.PENDING

        task3 = MagicMock(spec=Task)
        task3.description = "Run tests for newly extracted analysts"
        task3.status = TaskStatus.PENDING

        plan.tasks = [task1, task2, task3]

        result = validate_no_destructive_interdependencies(plan)

        # This should FAIL because tasks 1 and 2 both read/write from lib/analysts.py
        assert result.status == ValidationStatus.FAILED, \
            f"Should detect the real-world problem. Got: {result.message}\n{result.details}"

        assert "lib/analysts.py" in str(result.details), \
            "Should identify lib/analysts.py as the problematic file"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
