"""Test that test fix tasks skip unnecessary build steps."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.execution.orchestrator import _build_diagnostic_tasks_for_failure
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task


def test_syntax_error_in_test_file_skips_build():
    """Test that syntax errors in test files don't trigger build tasks."""

    # Simulate a failed test task with syntax error in test file
    # Use error message with specific path to trigger the syntax error code path
    failed_task = Task(
        description="fix tests/user.test.ts",
        action_type="test"
    )

    # Include "unterminated string" to trigger syntax error detection
    verification_result = VerificationResult(
        passed=False,
        message="Command failed with unterminated string literal in tests/user.test.ts",
        details={
            "tool": "run_tests",
            "rc": 1,
            "stdout": "",
            "stderr": "SyntaxError: unterminated string literal at tests/user.test.ts:15:10",
        },
        should_replan=True
    )

    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Debug: print all tasks
    print(f"Tasks created: {len(fix_tasks)}")
    for i, t in enumerate(fix_tasks):
        print(f"  {i+1}. [{t.action_type}] {t.description[:100]}")

    # Verify no build tasks were created
    build_tasks = [t for t in fix_tasks if t.action_type == "run" and ("build" in (t.description or "").lower() or "compile" in (t.description or "").lower())]

    assert len(build_tasks) == 0, f"Expected no build tasks for test file syntax error, but found: {[t.description for t in build_tasks]}"

    print("[OK] No build tasks created for test file syntax error")

    # Note: The exact tasks created depend on the error pattern detection
    # The key assertion is that build tasks are NOT created

    print("[OK] Syntax error in test file skips build tasks")


def test_syntax_error_in_source_file_includes_build():
    """Test that syntax errors in source files DO trigger build tasks."""

    # Simulate a failed task with syntax error in source file (NOT a test file)
    failed_task = Task(
        description="fix src/auth.ts",
        action_type="edit"
    )

    # Include "unterminated string" to trigger syntax error detection
    verification_result = VerificationResult(
        passed=False,
        message="Command failed with unterminated string in src/auth.ts",
        details={
            "tool": "run_cmd",
            "rc": 1,
            "stdout": "",
            "stderr": "SyntaxError: unterminated string literal at src/auth.ts:42:5",
        },
        should_replan=True
    )

    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Debug: print all tasks
    print(f"Tasks created for source file: {len(fix_tasks)}")
    for i, t in enumerate(fix_tasks):
        print(f"  {i+1}. [{t.action_type}] {t.description[:100]}")

    # Verify build tasks WERE created for source file (if syntax error path is triggered)
    build_tasks = [t for t in fix_tasks if t.action_type == "run" and ("build" in (t.description or "").lower() or "compile" in (t.description or "").lower())]

    # For source files, build tasks should be present since it's not a test file
    assert len(build_tasks) >= 1, f"Expected build tasks for source file syntax error, but found none. All tasks: {[(t.action_type, t.description[:80]) for t in fix_tasks]}"

    print(f"Build tasks for source file: {len(build_tasks)}")
    print("[OK] Source file syntax error includes build task (unlike test files)")


def test_watch_mode_fix_skips_build():
    """Test that watch mode timeout fix doesn't include build steps."""

    failed_task = Task(
        description="run vitest tests",
        action_type="test"
    )

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

    fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

    # Verify no build tasks
    build_tasks = [t for t in fix_tasks if t.action_type == "run" and ("build" in (t.description or "").lower())]

    assert len(build_tasks) == 0, f"Expected no build tasks for watch mode fix, but found: {[t.description for t in build_tasks]}"

    # Should have edit task for package.json and retest task
    assert len(fix_tasks) >= 2, "Should have at least 2 tasks (edit + retest)"
    assert fix_tasks[0].action_type == "edit", "First task should be edit"
    assert fix_tasks[1].action_type == "test", "Second task should be test"

    print("[OK] Watch mode fix skips build tasks and runs test immediately")


def test_test_file_patterns_detected():
    """Test that various test file patterns are correctly detected."""

    test_patterns = [
        "tests/user.test.ts",
        "tests/auth.spec.js",
        "test/integration.test.js",
        "src/components/__tests__/Button.test.tsx",
        "tests/test_auth.py",
        "tests/auth_test.py",
    ]

    for test_path in test_patterns:
        failed_task = Task(
            description=f"fix syntax in {test_path}",
            action_type="test"
        )

        verification_result = VerificationResult(
            passed=False,
            message="Syntax error",
            details={
                "tool": "run_tests",
                "rc": 1,
                "stdout": "",
                "stderr": f"SyntaxError in {test_path}",
            },
            should_replan=True
        )

        fix_tasks = _build_diagnostic_tasks_for_failure(failed_task, verification_result)

        # Verify no build tasks for any test file pattern
        build_tasks = [t for t in fix_tasks if t.action_type == "run" and ("build" in (t.description or "").lower())]

        assert len(build_tasks) == 0, f"Expected no build tasks for {test_path}, but found: {[t.description for t in build_tasks]}"

    print(f"[OK] All {len(test_patterns)} test file patterns correctly skip build")


if __name__ == "__main__":
    test_syntax_error_in_test_file_skips_build()
    test_syntax_error_in_source_file_includes_build()
    test_watch_mode_fix_skips_build()
    test_test_file_patterns_detected()

    print("\n[OK] All build optimization tests passed!")
