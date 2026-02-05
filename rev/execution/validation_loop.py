"""
Validation Loop - Simple and effective test-driven development.

This module provides the main validation retry loop that:
1. Runs tests after code execution
2. Parses test failures
3. Passes feedback to the executor for fixes
4. Retries until tests pass or max retries reached

This is the replacement for the over-engineered validator.py
"""

import json
import os
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass

from rev import config
from rev.llm.client import ollama_chat
from rev.tools.file_ops import write_file
from rev.terminal.formatting import colorize, Colors

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


def _consult_llm_for_validation(user_request: str, project_root: Path) -> Optional[dict]:
    """Ask LLM for a validation strategy if no tests are found."""
    # Gather minimal context about the project structure
    try:
        files = []
        for p in project_root.rglob("*"):
            if len(files) > 50:
                break
            if p.is_file() and not any(part.startswith(".") for part in p.parts) and "node_modules" not in p.parts and "vendor" not in p.parts:
                files.append(str(p.relative_to(project_root)))
        files_str = "\n".join(files)
    except Exception:
        files_str = "(Unable to list files)"

    system_prompt = (
        "You are a QA Lead. The user has implemented a feature but no standard tests (pytest/npm test) were detected. "
        "Decide if a custom verification step is needed. "
        "Return ONLY JSON."
    )
    
    user_prompt = f"""
    User Request: "{user_request}"
    
    Project Files (partial):
    {files_str}
    
    Task:
    1. Determine if we should verify the changes.
    2. If yes, provide a shell command to run. 
    3. You can optionally request to create a temporary test file (e.g. verify.py, test_check.php) to be run by that command.
    
    Output JSON format:
    {{
        "needed": boolean,
        "reason": "Short explanation",
        "command": "Command to run (e.g. 'python verify.py' or 'php artisan test')",
        "create_file": {{ "path": "filename", "content": "file content" }} (OPTIONAL, null if not needed)
    }}
    """
    
    try:
        response = ollama_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model=config.PLANNING_MODEL or config.EXECUTION_MODEL,
            temperature=0.2,
            supports_tools=False
        )
        
        if response and "message" in response and "content" in response["message"]:
            content = response["message"]["content"]
            # Extract JSON if wrapped in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
                
            return json.loads(content)
    except Exception as e:
        print(f"Error consulting LLM for validation: {e}")
        return None
    
    return None


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

        # Dynamic Validation Plan Injection: If no tests detected on first attempt
        if attempt == 1 and result.passed and result.command == "<none>":
            print(f"\n{colorize('?', Colors.BRIGHT_MAGENTA)} No standard tests found. Asking AI for a verification plan...")
            plan = _consult_llm_for_validation(user_request, project_root)
            
            if plan and plan.get("needed"):
                print(f"{colorize('!', Colors.BRIGHT_MAGENTA)} AI proposed verification: {plan.get('reason')}")
                
                # Create verification file if needed
                create_file_info = plan.get("create_file")
                if create_file_info:
                    path = create_file_info.get("path")
                    content = create_file_info.get("content")
                    if path and content:
                        print(f"  + Creating verification script: {path}")
                        try:
                            write_file(str(project_root / path), content)
                        except Exception as e:
                            print(f"  ! Failed to create verification script: {e}")
                
                test_cmd = plan.get("command")
                print(f"  -> Executing: {test_cmd}")
                
                # Rerun detection/execution with the new command
                result = validator.run_tests(test_cmd, timeout)
            else:
                 print(f"  -> AI decided no verification needed.")

        if result.passed:
            if result.total_tests == 0:
                print(f"\n✅ Validation skipped (no tests detected or run)")
                return ValidationLoopResult(
                    success=True,
                    attempts_made=attempt,
                    final_failures=[],
                    message="Validation skipped (no tests detected)",
                )
            
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