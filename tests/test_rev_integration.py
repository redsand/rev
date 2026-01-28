#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simplified REV Integration Tests for glm-4.7:cloud model.

This module tests REV's core components with the ollama provider.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
import time
import tempfile

# Configure for Windows UTF-8
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')

# Configure REV for testing
os.environ["REV_LLM_PROVIDER"] = "ollama"
os.environ["OLLAMA_MODEL"] = "glm-4.7:cloud"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"
os.environ["PYTHONIOENCODING"] = "utf-8"


def test_ollama_connection():
    """Test that ollama service is available and model is accessible."""
    print("=" * 70)
    print("Test 1: Ollama Connection")
    print("=" * 70)

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"FAIL: ollama CLI returned {result.returncode}")
            print(f"stderr: {result.stderr}")
            return False

        # Check if glm-4.7:cloud is available
        if "glm-4.7:cloud" in result.stdout:
            print("PASS: glm-4.7:cloud model is available")
            return True
        else:
            print(f"FAIL: glm-4.7:cloud not found in available models")
            print(f"Available models:\n{result.stdout}")
            return False

    except FileNotFoundError:
        print("FAIL: ollama CLI not found")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def test_rev_imports():
    """Test that REV can be imported without errors."""
    print("\n" + "=" * 70)
    print("Test 2: REV Imports")
    print("=" * 70)

    try:
        from rev.config import LLM_PROVIDER, OLLAMA_MODEL
        from rev.models.task import Task, TaskStatus, ExecutionPlan
        from rev.execution.plan_diff import diff_plans, detect_regression
        from rev.execution.goal_tracker import GoalTracker
        from rev.execution.plan_templates import TemplateRegistry

        print("PASS: All core REV modules imported successfully")
        print(f"  Provider: {LLM_PROVIDER}")
        print(f"  Model: {OLLAMA_MODEL}")

        # Verify the configuration is correct
        if LLM_PROVIDER != "ollama":
            print(f"FAIL: Expected provider 'ollama', got '{LLM_PROVIDER}'")
            return False
        if "glm-4.7:cloud" not in OLLAMA_MODEL:
            print(f"FAIL: Expected model 'glm-4.7:cloud', got '{OLLAMA_MODEL}'")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plan_diffing():
    """Test plan diffing functionality."""
    print("\n" + "=" * 70)
    print("Test 3: Plan Diffing")
    print("=" * 70)

    try:
        from rev.execution.plan_diff import diff_plans, format_diff
        from rev.models.task import ExecutionPlan

        # Test no changes
        plan1 = ExecutionPlan()
        plan1.add_task("Task 1")
        plan2 = ExecutionPlan()
        plan2.add_task("Task 1")
        diff = diff_plans(plan1, plan2)

        if not diff.has_changes:
            print("PASS: Plan diff correctly detects no changes")
        else:
            print(f"FAIL: Expected no changes, got {diff.summary}")
            return False

        # Test modified task - with position-based matching,
        # tasks at same position are compared as modifications
        plan3 = ExecutionPlan()
        plan3.add_task("Task 1 Modified")  # Same position, different description
        diff2 = diff_plans(plan1, plan3)

        if diff2.modified_count == 1:
            print("PASS: Plan diff correctly detects modified task")
        else:
            print(f"FAIL: Expected 1 modified task, got {diff2.modified_count}")
            return False

        # Test true added task (plan has fewer tasks)
        plan4 = ExecutionPlan()
        plan5 = ExecutionPlan()
        plan5.add_task("New Task")
        diff3 = diff_plans(plan4, plan5)

        if diff3.added_count == 1:
            print("PASS: Plan diff correctly detects added task (different plan sizes)")
        else:
            print(f"FAIL: Expected 1 added task, got {diff3.added_count}")
            return False

        # Test format_diff
        formatted = format_diff(diff2)
        if "Added:" in formatted:
            print("PASS: format_diff produces correct output")
        else:
            print(f"FAIL: format_diff output missing expected text")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_goal_tracker():
    """Test GoalTracker functionality."""
    print("\n" + "=" * 70)
    print("Test 4: GoalTracker")
    print("=" * 70)

    try:
        from rev.execution.goal_tracker import GoalTracker, GoalStatus
        from rev.models.task import Task, ExecutionPlan

        tracker = GoalTracker()

        # Test creating a goal
        goal = tracker.create_goal("Test goal")
        if goal.goal_id and goal.description == "Test goal":
            print("PASS: Goal created successfully")
        else:
            print("FAIL: Goal creation failed")
            return False

        # Test mapping a task to goal
        plan = ExecutionPlan()
        task = plan.add_task("Test task")
        change = tracker.map_task_to_goal(task, goal.goal_id)

        if change and change.goal_id == goal.goal_id:
            print("PASS: Task mapped to goal successfully")
        else:
            print("FAIL: Task mapping failed")
            return False

        # Test goal status update
        tracker.update_goal_status(goal.goal_id, GoalStatus.COMPLETED)
        updated_goal = tracker.get_goal(goal.goal_id)

        if updated_goal.status == GoalStatus.COMPLETED:
            print("PASS: Goal status updated successfully")
        else:
            print("FAIL: Goal status update failed")
            return False

        # Test summary
        summary = tracker.get_summary()
        if summary["total_goals"] == 1 and summary["completed"] == 1:
            print("PASS: GoalTracker summary is correct")
        else:
            print(f"FAIL: Expected 1 completed goal, got {summary}")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plan_templates():
    """Test plan templates functionality."""
    print("\n" + "=" * 70)
    print("Test 5: Plan Templates")
    print("=" * 70)

    try:
        from rev.execution.plan_templates import (
            TemplateRegistry,
            TemplateCategory,
            apply_template,
        )
        from rev.models.task import ExecutionPlan

        registry = TemplateRegistry()

        # Test TDD template exists
        tdd_template = registry.get("tdd_basic")
        if tdd_template and tdd_template.category == TemplateCategory.TDD:
            print("PASS: TDD template loaded successfully")
        else:
            print("FAIL: TDD template not found or wrong category")
            return False

        # Test template application
        plan = ExecutionPlan()
        result = apply_template("tdd_basic", plan, context={"feature": "test"})

        if result and len(result.tasks) > 0:
            print(f"PASS: TDD template applied successfully ({len(result.tasks)} tasks)")
        else:
            print("FAIL: Template application failed")
            return False

        # Test first task is a test task
        if result.tasks[0].action_type == "test":
            print("PASS: First task is a test task (TDD)")
        else:
            print("FAIL: First task should be a test task for TDD")
            return False

        # Test context variable substitution
        has_feature = any("test" in t.description for t in result.tasks)
        if has_feature:
            print("PASS: Context variables substituted correctly")
        else:
            print("FAIL: Context variable substitution failed")
            return False

        # Test template suggestion
        suggested = registry.suggest_template("Write tests for login")
        if suggested:
            print("PASS: Template suggestion works")
        else:
            print("FAIL: Template suggestion failed")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_taxonomy():
    """Test error taxonomy functionality."""
    print("\n" + "=" * 70)
    print("Test 6: Error Taxonomy")
    print("=" * 70)

    try:
        from rev.tools.errors import (
            ToolErrorType,
            ToolError,
            file_not_found_error,
            permission_denied_error,
            syntax_error,
        )

        # Test error type properties
        if ToolErrorType.NOT_FOUND.is_retryable:
            print("FAIL: NOT_FOUND should not be retryable")
            return False

        if ToolErrorType.TRANSIENT.is_retryable:
            print("PASS: TRANSIENT is correctly marked as retryable")
        else:
            print("FAIL: TRANSIENT should be retryable")
            return False

        # Test error creation
        error = file_not_found_error("test.py")
        if error.error_type == ToolErrorType.NOT_FOUND:
            print("PASS: File not found error created correctly")
        else:
            print("FAIL: File not found error type incorrect")
            return False

        # Test error serialization
        error_dict = error.to_dict()
        if "error" in error_dict and "error_type" in error_dict:
            print("PASS: Error serializes to dict correctly")
        else:
            print("FAIL: Error serialization missing keys")
            return False

        # Test error deserialization
        restored = ToolError.from_dict(error_dict)
        if restored.error_type == error.error_type:
            print("PASS: Error deserializes from dict correctly")
        else:
            print("FAIL: Error deserialization failed")
            return False

        # Test suggested recovery
        if error.suggested_recovery:
            print("PASS: Error includes suggested recovery steps")
        else:
            print("FAIL: Error should include suggested recovery")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_task_state_machine():
    """Test task state machine functionality."""
    print("\n" + "=" * 70)
    print("Test 7: Task State Machine")
    print("=" * 70)

    try:
        from rev.models.task import Task, TaskStatus, TaskStateMachine

        # Test valid transitions
        sm = TaskStateMachine(TaskStatus.PENDING)

        if sm.can_transition(TaskStatus.IN_PROGRESS):
            sm.transition(TaskStatus.IN_PROGRESS)
            print("PASS: PENDING -> IN_PROGRESS transition works")
        else:
            print("FAIL: PENDING -> IN_PROGRESS should be valid")
            return False

        # Test valid transitions (IN_PROGRESS -> COMPLETED is valid)
        if sm.can_transition(TaskStatus.COMPLETED):
            sm.transition(TaskStatus.COMPLETED)
            print("PASS: IN_PROGRESS -> COMPLETED transition is valid")
        else:
            print("FAIL: IN_PROGRESS -> COMPLETED should be valid")
            return False

        # Test COMPLETED -> IN_PROGRESS is invalid (terminal state)
        sm2 = TaskStateMachine(TaskStatus.COMPLETED)
        if not sm2.can_transition(TaskStatus.IN_PROGRESS):
            print("PASS: COMPLETED -> IN_PROGRESS is invalid (correct)")
        else:
            print("FAIL: COMPLETED -> IN_PROGRESS should be invalid")
            return False

        # Test state machine in Task
        task = Task("Test task")
        initial_status = task.status

        task.set_status(TaskStatus.IN_PROGRESS)
        if task.status == TaskStatus.IN_PROGRESS:
            print("PASS: Task state machine updates correctly")
        else:
            print("FAIL: Task state not updated")
            return False

        # Test history tracking
        history = task._state_machine.get_transition_history()
        if len(history) >= 2:  # Initial + IN_PROGRESS
            print(f"PASS: State machine tracks history ({len(history)} transitions)")
        else:
            print("FAIL: State machine not tracking history")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_orchestrator_modules():
    """Test orchestrator module splitting."""
    print("\n" + "=" * 70)
    print("Test 8: Orchestrator Module Splitting")
    print("=" * 70)

    try:
        # Test that new modules exist and are importable
        from rev.execution.task_runner import TaskRunner
        from rev.execution.recovery_manager import RecoveryManager
        from rev.execution.verification_coordinator import VerificationCoordinator

        print("PASS: All orchestrator modules imported")

        # Test that key methods exist
        from rev.execution.orchestrator import Orchestrator

        orchestrator = Orchestrator(Path.cwd())

        if hasattr(orchestrator, 'task_runner'):
            print("PASS: Orchestrator has task_runner instance")
        else:
            print("FAIL: Orchestrator missing task_runner")
            return False

        if hasattr(orchestrator, 'recovery_manager'):
            print("PASS: Orchestrator has recovery_manager instance")
        else:
            print("FAIL: Orchestrator missing recovery_manager")
            return False

        if hasattr(orchestrator, 'verification_coordinator'):
            print("PASS: Orchestrator has verification_coordinator instance")
        else:
            print("FAIL: Orchestrator missing verification_coordinator")
            return False

        return True

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gating_tests():
    """Run all gating tests to ensure no regressions."""
    print("\n" + "=" * 70)
    print("Test 9: Gating Tests")
    print("=" * 70)

    try:
        import unittest
        import sys
        from pathlib import Path

        # Add tests directory to path
        tests_dir = Path(__file__).parent
        if str(tests_dir) not in sys.path:
            sys.path.insert(0, str(tests_dir))

        # Import the gating test module
        import test_gating

        # Load tests
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(test_gating)

        # Run tests
        runner = unittest.TextTestRunner(verbosity=0)
        result = runner.run(suite)

        if result.wasSuccessful():
            print(f"PASS: All {result.testsRun} gating tests passed")
            return True
        else:
            print(f"FAIL: {len(result.failures)} failures, {len(result.errors)} errors")
            for test, traceback in result.failures + result.errors:
                print(f"  {test}")
            return False

    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "=" * 70)
    print("REV INTEGRATION TEST SUITE")
    print("Provider: ollama (glm-4.7:cloud)")
    print("=" * 70)

    start_time = time.time()

    tests = [
        ("Ollama Connection", test_ollama_connection),
        ("REV Imports", test_rev_imports),
        ("Plan Diffing", test_plan_diffing),
        ("GoalTracker", test_goal_tracker),
        ("Plan Templates", test_plan_templates),
        ("Error Taxonomy", test_error_taxonomy),
        ("Task State Machine", test_task_state_machine),
        ("Orchestrator Modules", test_orchestrator_modules),
        ("Gating Tests", test_gating_tests),
    ]

    results = []
    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\nERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
            failed += 1

    duration = time.time() - start_time

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total Tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass Rate: {passed/len(tests)*100:.1f}%")
    print(f"Duration: {duration:.2f}s")
    print("=" * 70)

    if failed > 0:
        print("\nFailed Tests:")
        for name, result in results:
            if not result:
                print(f"  - {name}")
        print("=" * 70)

    # Save results to JSON
    results_file = Path(__file__).parent / "test_results.json"
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "provider": "ollama",
            "model": "glm-4.7:cloud",
            "total": len(tests),
            "passed": passed,
            "failed": failed,
            "duration": duration,
            "pass_rate": passed/len(tests)*100,
            "results": [{"name": name, "passed": result} for name, result in results]
        }, f, indent=2)
    print(f"\nResults saved to: {results_file}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)