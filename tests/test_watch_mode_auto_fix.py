"""Test watch mode timeout detection and automatic fix task creation."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.execution.orchestrator import _build_diagnostic_tasks_for_failure
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task


def test_watch_mode_timeout_creates_fix_tasks():
    """Test that watch mode timeout diagnosis creates package.json fix task."""

    # Simulate a failed test task
    failed_task = Task(
        description="run tests for auth module",
        action_type="test"
    )
    failed_task.error = "command exceeded 600s timeout"

    # Simulate verification result with timeout_diagnosis from timeout_recovery.py
    verification_result = VerificationResult(
        passed=False,
        message="Command failed (rc=-1)",
        details={
            "tool": "run_tests",
            "rc": -1,
            "stdout": "Test Files  6 failed | 1 passed (7)\nTests  10 failed | 12 passed (22)\nFAIL  Tests failed. Watching for file changes...\npress h to show help, press q to quit",
            "stderr": "",
            "timeout_diagnosis": {
                "is_watch_mode": True,
                "diagnosis": "Test command is running in watch mode and waiting for file changes (non-terminating)",
                "suggested_fix": "Add '--run' flag to vitest command or update package.json test script to use 'vitest run' instead of 'vitest'"
            }
        },
        should_replan=True
    )

    # Call the function that creates diagnostic tasks
    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Verify fix tasks were created
    assert len(fix_tasks) >= 2, f"Expected at least 2 fix tasks, got {len(fix_tasks)}"

    # First task should be to update package.json
    fix_task = fix_tasks[0]
    assert fix_task.action_type == "edit", f"First task should be EDIT, got {fix_task.action_type}"
    assert "package.json" in fix_task.description.lower(), f"Should mention package.json: {fix_task.description}"
    assert "vitest run" in fix_task.description or "--run" in fix_task.description, \
        f"Should mention fix suggestion: {fix_task.description}"

    # Second task should be to re-run tests
    retest_task = fix_tasks[1]
    assert retest_task.action_type == "test", f"Second task should be TEST, got {retest_task.action_type}"

    print(f"[OK] Watch mode timeout created fix tasks:")
    print(f"  1. {fix_task.description}")
    print(f"  2. {retest_task.description}")


def test_non_watch_timeout_doesnt_trigger_fix():
    """Test that regular timeouts (non-watch mode) don't create watch mode fix tasks."""

    failed_task = Task(
        description="run long computation",
        action_type="test"
    )

    # Timeout without watch mode diagnosis
    verification_result = VerificationResult(
        passed=False,
        message="Command failed (rc=-1)",
        details={
            "tool": "run_tests",
            "rc": -1,
            "stdout": "Computing... Processing... Still running...",
            "stderr": "",
            # No timeout_diagnosis or is_watch_mode=False
            "timeout_diagnosis": {
                "is_watch_mode": False,
                "diagnosis": None,
                "suggested_fix": None
            }
        },
        should_replan=True
    )

    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Should NOT create watch mode specific tasks
    for task in fix_tasks:
        assert "vitest run" not in task.description.lower(), \
            f"Should not suggest vitest run for non-watch timeout: {task.description}"
        assert "watch mode" not in task.description.lower(), \
            f"Should not mention watch mode for non-watch timeout: {task.description}"

    print(f"[OK] Non-watch timeout does not create watch mode fix tasks")


def test_jest_watch_mode_timeout():
    """Test that Jest watch mode is also detected and fixed."""

    failed_task = Task(
        description="run jest tests",
        action_type="test"
    )

    verification_result = VerificationResult(
        passed=False,
        message="Command failed (rc=-1)",
        details={
            "tool": "run_tests",
            "rc": -1,
            "stdout": "Jest watch mode\nWatch Usage\nPress p to filter by filename\nPress q to quit watch mode",
            "stderr": "",
            "timeout_diagnosis": {
                "is_watch_mode": True,
                "diagnosis": "Test command is running in watch mode (non-terminating)",
                "suggested_fix": "Add '--no-watch' or '--watchAll=false' to jest command"
            }
        },
        should_replan=True
    )

    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    assert len(fix_tasks) >= 2, f"Expected at least 2 fix tasks for Jest watch mode"

    fix_task = fix_tasks[0]
    assert "package.json" in fix_task.description.lower(), "Should fix package.json"
    assert "--no-watch" in fix_task.description or "watchAll" in fix_task.description, \
        f"Should mention Jest fix: {fix_task.description}"

    print(f"[OK] Jest watch mode timeout creates appropriate fix tasks")


def test_no_timeout_diagnosis_no_special_handling():
    """Test that missing timeout_diagnosis doesn't crash and uses generic flow."""

    failed_task = Task(
        description="run tests",
        action_type="test"
    )

    # No timeout_diagnosis in details
    verification_result = VerificationResult(
        passed=False,
        message="Command failed (rc=1)",
        details={
            "tool": "run_tests",
            "rc": 1,
            "stdout": "Tests failed with errors",
            "stderr": "Error: cannot find module"
        },
        should_replan=True
    )

    # Should not crash
    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Should use generic error handling, not watch mode handling
    for task in fix_tasks:
        assert "watch mode" not in task.description.lower(), \
            "Should not mention watch mode without diagnosis"

    print(f"[OK] Missing timeout_diagnosis handled gracefully")


if __name__ == "__main__":
    test_watch_mode_timeout_creates_fix_tasks()
    test_non_watch_timeout_doesnt_trigger_fix()
    test_jest_watch_mode_timeout()
    test_no_timeout_diagnosis_no_special_handling()

    print("\n[OK] All watch mode auto-fix tests passed!")
