"""Tests for task resume functionality."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from rev.models.task import ExecutionPlan, Task, TaskStatus


def test_stopped_status_enum():
    """Test that STOPPED status exists in TaskStatus enum."""
    assert hasattr(TaskStatus, "STOPPED")
    assert TaskStatus.STOPPED.value == "stopped"


def test_task_serialization_with_stopped():
    """Test that tasks with STOPPED status can be serialized and deserialized."""
    task = Task("Test task", "edit")
    task.task_id = 0
    task.status = TaskStatus.STOPPED

    # Serialize
    task_dict = task.to_dict()
    assert task_dict["status"] == "stopped"

    # Deserialize
    restored_task = Task.from_dict(task_dict)
    assert restored_task.status == TaskStatus.STOPPED
    assert restored_task.description == "Test task"
    assert restored_task.action_type == "edit"


def test_execution_plan_serialization():
    """Test that ExecutionPlan can be serialized and deserialized."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "add")
    plan.add_task("Task 2", "edit", dependencies=[0])
    plan.add_task("Task 3", "test", dependencies=[1])

    # Mark some tasks
    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED
    plan.tasks[2].status = TaskStatus.PENDING

    # Serialize
    plan_dict = plan.to_dict()
    assert len(plan_dict["tasks"]) == 3
    assert plan_dict["tasks"][0]["status"] == "completed"
    assert plan_dict["tasks"][1]["status"] == "stopped"
    assert plan_dict["tasks"][2]["status"] == "pending"

    # Deserialize
    restored_plan = ExecutionPlan.from_dict(plan_dict)
    assert len(restored_plan.tasks) == 3
    assert restored_plan.tasks[0].status == TaskStatus.COMPLETED
    assert restored_plan.tasks[1].status == TaskStatus.STOPPED
    assert restored_plan.tasks[2].status == TaskStatus.PENDING
    assert restored_plan.tasks[1].dependencies == [0]
    assert restored_plan.tasks[2].dependencies == [1]


def test_checkpoint_save_and_load():
    """Test that checkpoints can be saved and loaded."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "add")
    plan.add_task("Task 2", "edit")
    plan.add_task("Task 3", "test")

    # Mark first task complete, second stopped, third pending
    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[0].result = "Task 1 completed successfully"
    plan.tasks[1].status = TaskStatus.STOPPED
    plan.tasks[2].status = TaskStatus.PENDING

    # Save checkpoint to temporary file
    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = os.path.join(tmpdir, "test_checkpoint.json")
        returned_path = plan.save_checkpoint(checkpoint_path)
        assert returned_path == checkpoint_path
        assert os.path.exists(checkpoint_path)

        # Load checkpoint
        restored_plan = ExecutionPlan.load_checkpoint(checkpoint_path)
        assert len(restored_plan.tasks) == 3
        assert restored_plan.tasks[0].status == TaskStatus.COMPLETED
        assert restored_plan.tasks[0].result == "Task 1 completed successfully"
        assert restored_plan.tasks[1].status == TaskStatus.STOPPED
        assert restored_plan.tasks[2].status == TaskStatus.PENDING


def test_checkpoint_default_location():
    """Test that checkpoints are saved to default location."""
    plan = ExecutionPlan()
    plan.add_task("Test task", "edit")
    plan.tasks[0].status = TaskStatus.STOPPED

    # Save without specifying path
    checkpoint_path = plan.save_checkpoint()
    try:
        assert ".rev_checkpoints" in checkpoint_path
        assert os.path.exists(checkpoint_path)

        # Load it back
        restored_plan = ExecutionPlan.load_checkpoint(checkpoint_path)
        assert len(restored_plan.tasks) == 1
        assert restored_plan.tasks[0].status == TaskStatus.STOPPED
    finally:
        # Cleanup
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)


def test_list_checkpoints():
    """Test listing available checkpoints."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a few checkpoints
        for i in range(3):
            plan = ExecutionPlan()
            plan.add_task(f"Task {i}", "edit")
            checkpoint_path = os.path.join(tmpdir, f"checkpoint_{i}.json")
            plan.save_checkpoint(checkpoint_path)

        # List checkpoints
        checkpoints = ExecutionPlan.list_checkpoints(tmpdir)
        assert len(checkpoints) == 3
        assert all("filename" in cp for cp in checkpoints)
        assert all("timestamp" in cp for cp in checkpoints)
        assert all("tasks_total" in cp for cp in checkpoints)


def test_list_checkpoints_empty_directory():
    """Test listing checkpoints when directory doesn't exist."""
    checkpoints = ExecutionPlan.list_checkpoints("/nonexistent/directory")
    assert checkpoints == []


def test_mark_task_stopped():
    """Test marking a task as stopped."""
    plan = ExecutionPlan()
    plan.add_task("Test task", "edit")
    task = plan.tasks[0]

    # Initially pending
    assert task.status == TaskStatus.PENDING

    # Mark as in progress
    plan.mark_task_in_progress(task)
    assert task.status == TaskStatus.IN_PROGRESS

    # Mark as stopped
    plan.mark_task_stopped(task)
    assert task.status == TaskStatus.STOPPED


def test_has_pending_tasks_includes_stopped():
    """Test that has_pending_tasks includes stopped tasks."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "edit")
    plan.add_task("Task 2", "edit")
    plan.add_task("Task 3", "edit")

    # All pending
    assert plan.has_pending_tasks()

    # Mark first completed, second stopped, third pending
    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED
    plan.tasks[2].status = TaskStatus.PENDING

    # Should still have pending tasks (stopped and pending)
    assert plan.has_pending_tasks()

    # Mark all completed
    plan.tasks[1].status = TaskStatus.COMPLETED
    plan.tasks[2].status = TaskStatus.COMPLETED

    # No pending tasks now
    assert not plan.has_pending_tasks()


def test_get_executable_tasks_includes_stopped():
    """Test that get_executable_tasks includes stopped tasks."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "edit")
    plan.add_task("Task 2", "edit", dependencies=[0])
    plan.add_task("Task 3", "edit")

    # Mark first completed, second stopped, third pending
    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED
    plan.tasks[2].status = TaskStatus.PENDING

    # Get executable tasks - should get both stopped and pending with deps met
    executable = plan.get_executable_tasks(max_count=10)
    assert len(executable) == 2
    assert plan.tasks[1] in executable  # Stopped task with deps met
    assert plan.tasks[2] in executable  # Pending task


def test_summary_includes_stopped():
    """Test that get_summary includes stopped tasks."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "edit")
    plan.add_task("Task 2", "edit")
    plan.add_task("Task 3", "edit")
    plan.add_task("Task 4", "edit")

    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED
    plan.tasks[2].status = TaskStatus.IN_PROGRESS
    plan.tasks[3].status = TaskStatus.PENDING

    summary = plan.get_summary()
    assert "1/4 completed" in summary
    assert "1 stopped" in summary
    assert "1 in progress" in summary


def test_is_complete_excludes_stopped():
    """Test that is_complete returns False when tasks are stopped."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "edit")
    plan.add_task("Task 2", "edit")

    # Mark first completed, second stopped
    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED

    # Should not be complete because of stopped task
    assert not plan.is_complete()

    # Mark stopped task as completed
    plan.tasks[1].status = TaskStatus.COMPLETED
    assert plan.is_complete()


def test_checkpoint_preserves_dependencies():
    """Test that checkpoints preserve task dependencies."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "add")
    plan.add_task("Task 2", "edit", dependencies=[0])
    plan.add_task("Task 3", "test", dependencies=[0, 1])

    plan.tasks[0].status = TaskStatus.COMPLETED
    plan.tasks[1].status = TaskStatus.STOPPED

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = os.path.join(tmpdir, "test_deps.json")
        plan.save_checkpoint(checkpoint_path)

        restored_plan = ExecutionPlan.load_checkpoint(checkpoint_path)
        assert restored_plan.tasks[1].dependencies == [0]
        assert restored_plan.tasks[2].dependencies == [0, 1]


def test_checkpoint_preserves_task_metadata():
    """Test that checkpoints preserve all task metadata."""
    plan = ExecutionPlan()
    plan.add_task("Test task", "edit")
    task = plan.tasks[0]

    # Set various metadata
    task.status = TaskStatus.STOPPED
    task.result = "Partial result"
    task.error = "Some error"
    task.risk_reasons = ["High risk"]
    task.impact_scope = ["file1.py", "file2.py"]
    task.estimated_changes = 50
    task.breaking_change = True
    task.rollback_plan = "Rollback instructions"
    task.validation_steps = ["Step 1", "Step 2"]
    task.complexity = "high"

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = os.path.join(tmpdir, "test_metadata.json")
        plan.save_checkpoint(checkpoint_path)

        restored_plan = ExecutionPlan.load_checkpoint(checkpoint_path)
        restored_task = restored_plan.tasks[0]

        assert restored_task.status == TaskStatus.STOPPED
        assert restored_task.result == "Partial result"
        assert restored_task.error == "Some error"
        assert restored_task.risk_reasons == ["High risk"]
        assert restored_task.impact_scope == ["file1.py", "file2.py"]
        assert restored_task.estimated_changes == 50
        assert restored_task.breaking_change is True
        assert restored_task.rollback_plan == "Rollback instructions"
        assert restored_task.validation_steps == ["Step 1", "Step 2"]
        assert restored_task.complexity == "high"
