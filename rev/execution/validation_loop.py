"""
Validation Loop - Simple and effective test-driven development.

This module provides the main validation retry loop that:
1. Runs tests after code execution
2. Parses test failures
3. Passes feedback to the executor for fixes
4. Retries until tests pass or max retries reached

This is the replacement for the over-engineered validator.py
"""

from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass

from rev.execution.simple_validator import (
    SimpleValidator,
    ValidationResult,
    TestFailure,
    validate_and_fix,
)
from rev.execution.executor import fix_validation_failures
from rev.tools.registry import get_available_tools


@dataclass
class ValidationLoopResult:
    """Result of the validation loop."""
    success: bool
    attempts_made: int
    final_failures: List[TestFailure]
    message: str


def run_validation_loop(
    project_root: Path,
    user_request: str,
    test_cmd: Optional[str] = None,
    max_retries: int = 3,
    timeout: int = 120,
    enable_fix: bool = True,
) -> ValidationLoopResult:
    """Run the validation loop with automatic fix retry.

    This is the main entry point for validation.

    Args:
        project_root: Path to the project root
        user_request: Original user request for context
        test_cmd: Test command to run (auto-detected if None)
        max_retries: Maximum number of fix attempts
        timeout: Timeout for each test run in seconds
        enable_fix: Whether to attempt automatic fixes

    Returns:
        ValidationLoopResult with the outcome
    """
    validator = SimpleValidator(project_root)

    print("\n" + "=" * 60)
    print("VALIDATION LOOP")
    print("=" * 60)

    for attempt in range(1, max_retries + 1):
        print(f"\n[Validation] Attempt {attempt}/{max_retries}")

        # Run tests
        result = validator.run_tests(test_cmd, timeout)

        if result.passed:
            print(f"\n✅ All {result.total_tests} tests passed!")
            return ValidationLoopResult(
                success=True,
                attempts_made=attempt,
                final_failures=[],
                message=f"All {result.total_tests} tests passed",
            )

        # Tests failed - show feedback
        print(f"\n❌ {result.failed_tests}/{result.total_tests} tests failed")

        feedback = validator.format_feedback_for_llm(result)
        print(feedback)

        # If this is the last attempt or fixes are disabled, return failure
        if attempt >= max_retries or not enable_fix:
            return ValidationLoopResult(
                success=False,
                attempts_made=attempt,
                final_failures=result.failures,
                message=f"Validation failed after {attempt} attempts",
            )

        # Attempt automatic fix
        print(f"\n[Validation] Attempting automatic fix...")
        fix_success = fix_validation_failures(
            validation_feedback=feedback,
            user_request=user_request,
            tools=get_available_tools(),
            enable_action_review=False,  # Auto-fix should not require review
            max_fix_attempts=5,  # Give LLM more chances to make fixes
            coding_mode=False,
        )

        if not fix_success:
            print(f"\n✗ Auto-fix attempt failed")
            # Continue to next attempt if we have retries left

    # Should not reach here, but handle gracefully
    return ValidationLoopResult(
        success=False,
        attempts_made=max_retries,
        final_failures=[],
        message="Validation loop completed",
    )


def quick_validate(
    project_root: Path,
    test_cmd: Optional[str] = None,
    timeout: int = 60
) -> ValidationResult:
    """Quick validation - just run tests once, no retry loop.

    Args:
        project_root: Path to the project root
        test_cmd: Test command to run (auto-detected if None)
        timeout: Timeout for test run in seconds

    Returns:
        ValidationResult with test results
    """
    validator = SimpleValidator(project_root)
    return validator.run_tests(test_cmd, timeout)


def format_test_summary(result: ValidationResult) -> str:
    """Format test result as a summary string.

    Args:
        result: ValidationResult to format

    Returns:
        Formatted summary string
    """
    if result.passed:
        return f"✅ All {result.total_tests} tests passed"

    details = []
    details.append(f"❌ {result.passed_tests}/{result.total_tests} tests passed")

    if result.failures:
        details.append("\nFailed tests:")
        for failure in result.failures[:5]:  # Show first 5 failures
            details.append(f"  - {failure.test_name}: {failure.error_type}")

    return "\n".join(details)