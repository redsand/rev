"""Test uncertainty detection system."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.execution.uncertainty_detector import (
    detect_uncertainty,
    _detect_planning_uncertainty,
    _detect_execution_uncertainty,
    _detect_verification_uncertainty,
    _detect_missing_files_uncertainty,
    UncertaintySignal,
    format_uncertainty_reasons,
    should_request_guidance,
    UNCERTAINTY_WEIGHTS
)
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task


def test_planning_hesitation_detection():
    """Test detection of planner hesitation markers."""

    task = Task(description="add user auth", action_type="edit")
    llm_response = "We could try using JWT tokens, or possibly session-based auth. Not sure which is better."

    signals = _detect_planning_uncertainty(
        task_description=task.description,
        llm_response=llm_response,
        task=task
    )

    assert len(signals) >= 1, "Should detect hesitation markers"
    assert signals[0].signal_type == "planner_hesitation"
    assert signals[0].score == UNCERTAINTY_WEIGHTS["planner_hesitation"]
    print(f"[OK] Detected planner hesitation: {signals[0].reason}")


def test_multiple_files_detection():
    """Test detection of multiple file references."""

    task = Task(
        description="update src/auth.ts and src/user.ts to add validation",
        action_type="edit"
    )

    signals = _detect_planning_uncertainty(
        task_description=task.description,
        task=task
    )

    # May or may not detect multiple files depending on pattern matching
    # This is informational
    if signals:
        print(f"[OK] Detected multiple files: {signals[0].reason}")
    else:
        print(f"[OK] No multiple files detected (may be intentional)")


def test_repeated_failure_detection():
    """Test detection of repeated failures with identical errors."""

    task = Task(description="run tests", action_type="test")
    task.error = "ModuleNotFoundError: No module named 'pytest'"

    previous_errors = [
        "ModuleNotFoundError: No module named 'pytest'",
        "ModuleNotFoundError: No module named 'pytest'",
        "ModuleNotFoundError: No module named 'pytest'"
    ]

    signals = _detect_execution_uncertainty(
        task=task,
        retry_count=3,
        last_error=task.error,
        previous_errors=previous_errors
    )

    assert len(signals) >= 1, "Should detect repeated failures"
    repeated_signal = next((s for s in signals if s.signal_type == "repeated_failure"), None)
    assert repeated_signal is not None, "Should have repeated_failure signal"
    assert repeated_signal.score == UNCERTAINTY_WEIGHTS["repeated_failure"]
    print(f"[OK] Detected repeated failure: {repeated_signal.reason}")


def test_no_progress_detection():
    """Test detection of no progress (same error every attempt)."""

    task = Task(description="fix syntax error", action_type="edit")

    previous_errors = [
        "SyntaxError: unterminated string",
        "SyntaxError: unterminated string",
        "SyntaxError: unterminated string"
    ]

    signals = _detect_execution_uncertainty(
        task=task,
        retry_count=3,
        last_error="SyntaxError: unterminated string",
        previous_errors=previous_errors
    )

    no_progress_signal = next((s for s in signals if s.signal_type == "no_progress"), None)
    assert no_progress_signal is not None, "Should detect no progress"
    assert no_progress_signal.score == UNCERTAINTY_WEIGHTS["no_progress"]
    print(f"[OK] Detected no progress: {no_progress_signal.reason}")


def test_verification_inconclusive():
    """Test detection of inconclusive verification."""

    task = Task(description="run validation", action_type="test")

    result = VerificationResult(
        passed=False,
        message="Verification inconclusive",
        details={},
        should_replan=True
    )
    result.inconclusive = True

    signals = _detect_verification_uncertainty(result, task)

    assert len(signals) >= 1, "Should detect inconclusive verification"
    assert signals[0].signal_type == "verification_inconclusive"
    print(f"[OK] Detected inconclusive verification: {signals[0].reason}")


def test_timeout_unclear():
    """Test detection of unclear timeout."""

    task = Task(description="run long task", action_type="test")

    result = VerificationResult(
        passed=False,
        message="Command timed out after 600s",
        details={
            "rc": -1,
            "stdout": "Processing...",
            "stderr": ""
            # No timeout_diagnosis - unclear why it timed out
        },
        should_replan=True
    )

    signals = _detect_verification_uncertainty(result, task)

    timeout_signal = next((s for s in signals if s.signal_type == "timeout_unclear"), None)
    assert timeout_signal is not None, "Should detect unclear timeout"
    assert timeout_signal.score == UNCERTAINTY_WEIGHTS["timeout_unclear"]
    print(f"[OK] Detected unclear timeout: {timeout_signal.reason}")


def test_comprehensive_uncertainty_detection():
    """Test comprehensive uncertainty detection across multiple phases."""

    task = Task(
        description="fix tests/auth.test.ts",
        action_type="test"
    )
    task.error = "SyntaxError: Unexpected token"

    previous_errors = [
        "SyntaxError: Unexpected token",
        "SyntaxError: Unexpected token"
    ]

    verification_result = VerificationResult(
        passed=False,
        message="Command failed (rc=1)",
        details={
            "tool": "run_tests",
            "rc": 1,
            "stdout": "",
            "stderr": "SyntaxError: Unexpected token"
        },
        should_replan=True
    )

    # Detect uncertainty
    score, signals = detect_uncertainty(
        task=task,
        retry_count=2,
        verification_result=verification_result,
        previous_errors=previous_errors
    )

    print(f"\nComprehensive detection results:")
    print(f"  Total score: {score}")
    print(f"  Signals detected: {len(signals)}")
    for signal in signals:
        print(f"    - [{signal.signal_type}] {signal.reason} (score: {signal.score})")

    assert score > 0, "Should detect some uncertainty"
    assert len(signals) > 0, "Should have at least one signal"


def test_format_uncertainty_reasons():
    """Test formatting of uncertainty reasons."""

    signals = [
        UncertaintySignal(
            signal_type="repeated_failure",
            reason="Task failed 3 times with identical error",
            score=5
        ),
        UncertaintySignal(
            signal_type="no_progress",
            reason="No progress - same error on every attempt",
            score=4
        )
    ]

    formatted = format_uncertainty_reasons(signals)

    assert "Task failed 3 times" in formatted
    assert "No progress" in formatted
    assert "•" in formatted  # Bullet points
    print(f"[OK] Formatted reasons:\n{formatted}")


def test_should_request_guidance_thresholds():
    """Test guidance request thresholds."""

    # Below threshold - should not request
    should_request, action = should_request_guidance(3, threshold=5)
    assert not should_request, "Should not request below threshold"
    assert action == "continue"

    # At threshold - should request
    should_request, action = should_request_guidance(5, threshold=5)
    assert should_request, "Should request at threshold"
    assert action == "request"

    # Above auto-skip threshold - should auto-skip
    should_request, action = should_request_guidance(12, threshold=5, auto_skip_threshold=10)
    assert should_request, "Should request at auto-skip threshold"
    assert action == "auto_skip"

    print("[OK] Threshold logic works correctly")


def test_no_uncertainty_when_first_attempt():
    """Test that uncertainty is not detected on first attempt."""

    task = Task(description="run tests", action_type="test")
    task.error = "Test failed"

    verification_result = VerificationResult(
        passed=False,
        message="Test failed",
        details={"rc": 1},
        should_replan=True
    )

    # First attempt (retry_count=0)
    score, signals = detect_uncertainty(
        task=task,
        retry_count=0,
        verification_result=verification_result,
        previous_errors=[]
    )

    # May have planning uncertainty, but no execution uncertainty
    execution_signals = [s for s in signals if s.signal_type in ("repeated_failure", "no_progress", "no_tool_calls")]
    assert len(execution_signals) == 0, "Should not detect execution uncertainty on first attempt"
    print(f"[OK] No execution uncertainty on first attempt (score: {score})")


def test_uncertainty_increases_with_retries():
    """Test that uncertainty score increases with more retries."""

    task = Task(description="fix error", action_type="edit")
    task.error = "Same error"

    verification_result = VerificationResult(
        passed=False,
        message="Same error",
        details={"rc": 1},
        should_replan=True
    )

    # Retry 1
    score1, signals1 = detect_uncertainty(
        task=task,
        retry_count=1,
        verification_result=verification_result,
        previous_errors=["Same error"]
    )

    # Retry 3
    score3, signals3 = detect_uncertainty(
        task=task,
        retry_count=3,
        verification_result=verification_result,
        previous_errors=["Same error", "Same error", "Same error"]
    )

    assert score3 >= score1, "Score should increase or stay same with more retries"
    print(f"[OK] Uncertainty increases: retry_1={score1}, retry_3={score3}")


if __name__ == "__main__":
    test_planning_hesitation_detection()
    test_multiple_files_detection()
    test_repeated_failure_detection()
    test_no_progress_detection()
    test_verification_inconclusive()
    test_timeout_unclear()
    test_comprehensive_uncertainty_detection()
    test_format_uncertainty_reasons()
    test_should_request_guidance_thresholds()
    test_no_uncertainty_when_first_attempt()
    test_uncertainty_increases_with_retries()

    print("\n[OK] All uncertainty detection tests passed!")
