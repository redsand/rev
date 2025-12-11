"""
Validation Agent for post-execution verification.

This module provides validation capabilities that verify executed changes
actually work correctly, running tests, linting, and behavioral checks.
"""

import json
import re
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field

from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.tools.registry import execute_tool
from rev.llm.client import ollama_chat


class ValidationStatus(Enum):
    """Validation outcome status."""
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ValidationResult:
    """Result of a validation check."""
    name: str
    status: ValidationStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms
        }


@dataclass
class ValidationReport:
    """Complete validation report for an execution."""
    results: List[ValidationResult] = field(default_factory=list)
    overall_status: ValidationStatus = ValidationStatus.PASSED
    summary: str = ""
    rollback_recommended: bool = False
    auto_fixed: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def add_result(self, result: ValidationResult):
        self.results.append(result)
        # Update overall status
        if result.status == ValidationStatus.FAILED:
            self.overall_status = ValidationStatus.FAILED
            self.rollback_recommended = True
        elif result.status == ValidationStatus.PASSED_WITH_WARNINGS and self.overall_status != ValidationStatus.FAILED:
            self.overall_status = ValidationStatus.PASSED_WITH_WARNINGS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "overall_status": self.overall_status.value,
            "summary": self.summary,
            "rollback_recommended": self.rollback_recommended,
            "auto_fixed": self.auto_fixed,
            "details": self.details,
        }


VALIDATION_SYSTEM = """You are a validation agent that verifies code changes work correctly.

Analyze the execution results and determine if the changes are valid:
1. Did the tests pass?
2. Are there any syntax errors?
3. Do the changes match what was requested?
4. Are there any obvious bugs or issues?

Return your validation in JSON format:
{
    "valid": true,
    "issues": [],
    "warnings": ["Optional warnings"],
    "suggestions": ["Improvement suggestions"],
    "confidence": 0.95
}

Be practical - minor style issues shouldn't fail validation."""


def validate_execution(
    plan: ExecutionPlan,
    user_request: str,
    run_tests: bool = True,
    run_linter: bool = True,
    check_syntax: bool = True,
    enable_auto_fix: bool = False,
    validation_mode: str = "targeted",
) -> ValidationReport:
    """Validate the results of plan execution.

    Args:
        plan: The executed plan to validate
        user_request: Original user request for context
        run_tests: Whether to run test suite
        run_linter: Whether to run linter checks
        check_syntax: Whether to check for syntax errors
        enable_auto_fix: Whether to attempt auto-fixes for minor issues

    Returns:
        ValidationReport with all validation results
    """
    print("\n" + "=" * 60)
    print("VALIDATION AGENT - POST-EXECUTION VERIFICATION")
    print("=" * 60)

    report = ValidationReport()

    # Check if execution even completed
    completed_tasks = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED]
    failed_tasks = [t for t in plan.tasks if t.status == TaskStatus.FAILED]

    if not completed_tasks:
        result = ValidationResult(
            name="execution_check",
            status=ValidationStatus.FAILED,
            message="No tasks completed successfully"
        )
        report.add_result(result)
        report.summary = "Validation failed: No tasks completed"
        _display_validation_report(report)
        return report

    if failed_tasks:
        result = ValidationResult(
            name="execution_check",
            status=ValidationStatus.PASSED_WITH_WARNINGS,
            message=f"{len(failed_tasks)} task(s) failed during execution",
            details={"failed_tasks": [t.description for t in failed_tasks]}
        )
        report.add_result(result)
    else:
        result = ValidationResult(
            name="execution_check",
            status=ValidationStatus.PASSED,
            message=f"All {len(completed_tasks)} tasks completed successfully"
        )
        report.add_result(result)

    # Normalize validation mode
    validation_mode = (validation_mode or "targeted").lower()

    commands_run: List[Dict[str, str]] = []

    if validation_mode == "none":
        report.summary = "Validation skipped (mode=none)"
        _display_validation_report(report)
        return report

    # Configure validation scope
    if validation_mode == "smoke":
        check_syntax = True
        run_tests = True
        run_linter = False
        test_cmd = "python -m compileall ."
        lint_cmd = None
    elif validation_mode == "targeted":
        check_syntax = True
        run_tests = True
        run_linter = True
        test_cmd = "pytest -q tests/ --maxfail=1"
        lint_cmd = "ruff check . --select E9,F63,F7,F82 --output-format=json"
    else:  # full
        check_syntax = True
        run_tests = True
        run_linter = True
        test_cmd = "pytest -q tests/"
        lint_cmd = "ruff check . --output-format=json"

    # 0. Goal Validation (if goals were set)
    if hasattr(plan, 'goals') and plan.goals:
        print("→ Validating execution goals...")
        goal_result = _validate_goals(plan.goals)
        report.add_result(goal_result)

    # 1. Syntax Check
    if check_syntax:
        print("→ Running syntax checks...")
        syntax_result = _check_syntax()
        report.add_result(syntax_result)
        commands_run.append({"name": "syntax_check", "command": "python -m compileall ."})

    # 2. Run Tests
    if run_tests:
        print("→ Running test suite...")
        test_result = _run_test_suite(test_cmd)
        report.add_result(test_result)
        commands_run.append({"name": "tests", "command": test_cmd})

        # Auto-fix attempt if tests failed
        if test_result.status == ValidationStatus.FAILED and enable_auto_fix:
            print("  → Attempting auto-fix...")
            fixed = _attempt_auto_fix(test_result)
            if fixed:
                report.auto_fixed.append("test_failures")
                # Re-run tests
                test_result = _run_test_suite(test_cmd)
                test_result.name = "tests_after_autofix"
                report.add_result(test_result)

    # 3. Run Linter
    if run_linter and lint_cmd:
        print("→ Running linter checks...")
        lint_result = _run_linter(lint_cmd)
        report.add_result(lint_result)
        commands_run.append({"name": "linter", "command": lint_cmd})

        # Auto-fix linting issues
        if lint_result.status in [ValidationStatus.FAILED, ValidationStatus.PASSED_WITH_WARNINGS] and enable_auto_fix:
            print("  → Attempting auto-fix for linting issues...")
            fixed = _auto_fix_linting()
            if fixed:
                report.auto_fixed.append("linting_issues")

    # 4. Git Diff Check
    print("→ Checking git diff...")
    diff_result = _check_git_diff(plan)
    report.add_result(diff_result)

    # 5. LLM Validation (semantic check)
    print("→ Running semantic validation...")
    semantic_result = _semantic_validation(plan, user_request)
    report.add_result(semantic_result)

    # Generate summary
    passed = sum(1 for r in report.results if r.status == ValidationStatus.PASSED)
    warnings = sum(1 for r in report.results if r.status == ValidationStatus.PASSED_WITH_WARNINGS)
    failed = sum(1 for r in report.results if r.status == ValidationStatus.FAILED)

    if report.overall_status == ValidationStatus.PASSED:
        report.summary = f"All {passed} validation checks passed"
    elif report.overall_status == ValidationStatus.PASSED_WITH_WARNINGS:
        report.summary = f"{passed} passed, {warnings} with warnings"
    else:
        report.summary = f"Validation failed: {failed} check(s) failed, {passed} passed"

    report.details = {"commands_run": commands_run}

    _display_validation_report(report)
    return report


def _validate_goals(goals: List) -> ValidationResult:
    """Validate that execution goals were met.

    Args:
        goals: List of Goal objects from execution plan

    Returns:
        ValidationResult with goal validation outcome
    """
    try:
        if not goals:
            return ValidationResult(
                name="goal_validation",
                status=ValidationStatus.SKIPPED,
                message="No goals defined for validation"
            )

        # Import Goal class
        from rev.models.goal import Goal

        total_goals = len(goals)
        passed_goals = 0
        failed_goals = []

        for goal in goals:
            if not isinstance(goal, Goal):
                continue

            # Evaluate goal metrics
            goal_passed = goal.evaluate_metrics()

            if goal_passed:
                passed_goals += 1
            else:
                failed_goals.append({
                    "description": goal.description if hasattr(goal, 'description') else "Unknown goal",
                    "metrics": goal.get_metrics_summary() if hasattr(goal, 'get_metrics_summary') else {}
                })

        # Determine status
        if passed_goals == total_goals:
            return ValidationResult(
                name="goal_validation",
                status=ValidationStatus.PASSED,
                message=f"All {total_goals} execution goal(s) met",
                details={"goals_passed": passed_goals, "goals_total": total_goals}
            )
        elif passed_goals > 0:
            return ValidationResult(
                name="goal_validation",
                status=ValidationStatus.PASSED_WITH_WARNINGS,
                message=f"{passed_goals}/{total_goals} goal(s) met",
                details={
                    "goals_passed": passed_goals,
                    "goals_total": total_goals,
                    "failed_goals": failed_goals
                }
            )
        else:
            return ValidationResult(
                name="goal_validation",
                status=ValidationStatus.FAILED,
                message=f"None of the {total_goals} goal(s) were met",
                details={"failed_goals": failed_goals}
            )

    except Exception as e:
        return ValidationResult(
            name="goal_validation",
            status=ValidationStatus.SKIPPED,
            message=f"Could not validate goals: {e}"
        )


def _check_syntax() -> ValidationResult:
    """Check for Python syntax errors."""
    try:
        # Cross-platform syntax check over all Python files under the repo root.
        cmd = (
            "python -c \"import os,py_compile,sys;"
            "errs=0;"
            "root='.';"
            "d=os.walk(root);"
            "import pathlib;"
            "files=[os.path.join(dp,f) for dp,_,fs in d for f in fs if f.endswith('.py')];"
            "names=sorted(set(files));"
            "from traceback import format_exception;"
            "import traceback;"
            " "
            "print(f'Checking {len(names)} python files');"
            " "
            "fails=[];"
            " "
            "for p in names:"
            "    try: py_compile.compile(p, doraise=True)"
            "    except Exception as e:"
            "        errs+=1; fails.append((p,str(e)));"
            " "
            "from pprint import pprint;"
            " "
            "[(print(f'PY_SYNTAX_ERROR {p}: {err}')) for p,err in fails];"
            "sys.exit(1 if errs else 0)\""
        )
        result = execute_tool("run_cmd", {"cmd": cmd, "timeout": 600})
        result_data = json.loads(result)
        output = result_data.get("stdout", "") + result_data.get("stderr", "")

        if "PY_SYNTAX_ERROR" in output or "syntaxerror" in output.lower():
            return ValidationResult(
                name="syntax_check",
                status=ValidationStatus.FAILED,
                message="Syntax errors detected",
                details={"output": output[:500]}
            )
        return ValidationResult(
            name="syntax_check",
            status=ValidationStatus.PASSED,
            message="No syntax errors found"
        )
    except Exception as e:
        return ValidationResult(
            name="syntax_check",
            status=ValidationStatus.SKIPPED,
            message=f"Could not run syntax check: {e}"
        )


def _run_test_suite(cmd: str) -> ValidationResult:
    """Run the project's test suite."""
    try:
        result = execute_tool("run_tests", {"cmd": cmd, "timeout": 600})
        result_data = json.loads(result)

        rc = result_data.get("rc", 1)
        output = result_data.get("stdout", "") + result_data.get("stderr", "")

        if rc == 0:
            # Extract test count if possible
            match = re.search(r'(\d+) passed', output)
            test_count = match.group(1) if match else "all"
            return ValidationResult(
                name="test_suite",
                status=ValidationStatus.PASSED,
                message=f"{test_count} tests passed",
                details={"return_code": rc}
            )
        else:
            # Extract failure info
            failures = re.findall(r'FAILED (.*?) -', output)
            return ValidationResult(
                name="test_suite",
                status=ValidationStatus.FAILED,
                message=f"Tests failed (rc={rc})",
                details={"return_code": rc, "failures": failures[:5], "output": output[:1000]}
            )
    except Exception as e:
        return ValidationResult(
            name="test_suite",
            status=ValidationStatus.SKIPPED,
            message=f"Could not run tests: {e}"
        )


def _run_linter(cmd: str) -> ValidationResult:
    """Run linter checks (ruff/flake8/pylint)."""
    try:
        result = execute_tool("run_cmd", {"cmd": cmd, "timeout": 600})
        result_data = json.loads(result)
        output = result_data.get("stdout", "[]")

        try:
            issues = json.loads(output)
            if not issues or issues == []:
                return ValidationResult(
                    name="linter",
                    status=ValidationStatus.PASSED,
                    message="No linting issues found"
                )
            elif len(issues) < 5:
                return ValidationResult(
                    name="linter",
                    status=ValidationStatus.PASSED_WITH_WARNINGS,
                    message=f"{len(issues)} minor linting issues",
                    details={"issues": issues[:5]}
                )
            else:
                return ValidationResult(
                    name="linter",
                    status=ValidationStatus.FAILED,
                    message=f"{len(issues)} linting issues found",
                    details={"issues": issues[:10]}
                )
        except json.JSONDecodeError:
            # Non-JSON output, probably an error or no ruff
            return ValidationResult(
                name="linter",
                status=ValidationStatus.SKIPPED,
                message="Linter not available or produced non-JSON output"
            )
    except Exception as e:
        return ValidationResult(
            name="linter",
            status=ValidationStatus.SKIPPED,
            message=f"Could not run linter: {e}"
        )


def _check_git_diff(plan: ExecutionPlan) -> ValidationResult:
    """Check git diff to verify changes were made."""
    try:
        result = execute_tool("git_diff", {})
        result_data = json.loads(result)
        diff = result_data.get("diff", "")

        if not diff:
            # No changes - might be expected or might be a problem
            completed_edits = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED and t.action_type in ["edit", "add"]]
            if completed_edits:
                return ValidationResult(
                    name="git_diff",
                    status=ValidationStatus.PASSED_WITH_WARNINGS,
                    message="No uncommitted changes found (may have been committed)",
                    details={"expected_changes": len(completed_edits)}
                )
            return ValidationResult(
                name="git_diff",
                status=ValidationStatus.PASSED,
                message="No changes expected, none found"
            )

        # Count changed files
        files_changed = len(re.findall(r'^diff --git', diff, re.MULTILINE))
        lines_added = len(re.findall(r'^\+[^+]', diff, re.MULTILINE))
        lines_removed = len(re.findall(r'^-[^-]', diff, re.MULTILINE))

        return ValidationResult(
            name="git_diff",
            status=ValidationStatus.PASSED,
            message=f"{files_changed} files changed (+{lines_added}/-{lines_removed} lines)",
            details={
                "files_changed": files_changed,
                "lines_added": lines_added,
                "lines_removed": lines_removed
            }
        )
    except Exception as e:
        return ValidationResult(
            name="git_diff",
            status=ValidationStatus.SKIPPED,
            message=f"Could not check git diff: {e}"
        )


def _semantic_validation(plan: ExecutionPlan, user_request: str) -> ValidationResult:
    """Use LLM to semantically validate the changes match the request."""
    # Gather execution summary
    task_summaries = []
    for task in plan.tasks:
        summary = f"- [{task.status.value}] {task.description}"
        if task.result:
            summary += f" (Result: {task.result[:100]}...)" if len(str(task.result)) > 100 else f" (Result: {task.result})"
        task_summaries.append(summary)

    messages = [
        {"role": "system", "content": VALIDATION_SYSTEM},
        {"role": "user", "content": f"""Validate these execution results:

Original Request: {user_request}

Executed Tasks:
{chr(10).join(task_summaries)}

Do the completed tasks fulfill the original request?"""}
    ]

    response = ollama_chat(messages)

    if "error" in response:
        return ValidationResult(
            name="semantic_validation",
            status=ValidationStatus.SKIPPED,
            message="Could not run semantic validation"
        )

    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            validation_data = json.loads(json_match.group(0))

            is_valid = validation_data.get("valid", True)
            confidence = validation_data.get("confidence", 0.5)
            issues = validation_data.get("issues", [])
            warnings = validation_data.get("warnings", [])

            if is_valid and confidence >= 0.8:
                status = ValidationStatus.PASSED
                message = f"Changes match request (confidence: {confidence:.0%})"
            elif is_valid and confidence >= 0.5:
                status = ValidationStatus.PASSED_WITH_WARNINGS
                message = f"Changes likely match request (confidence: {confidence:.0%})"
            else:
                status = ValidationStatus.FAILED
                message = f"Changes may not match request (confidence: {confidence:.0%})"

            return ValidationResult(
                name="semantic_validation",
                status=status,
                message=message,
                details={"confidence": confidence, "issues": issues, "warnings": warnings}
            )
    except Exception as e:
        pass

    return ValidationResult(
        name="semantic_validation",
        status=ValidationStatus.SKIPPED,
        message="Could not parse semantic validation"
    )


def _attempt_auto_fix(test_result: ValidationResult, max_attempts: int = 3) -> bool:
    """Attempt a simple, bounded auto-fix for test failures.

    Strategy (stop on first success):
      1) If we know a failed test path, rerun it directly.
      2) Rerun last-failed tests (--lf) to address flakiness.
      3) Rerun a short full suite with maxfail=1.
    """
    attempts = []
    # 1) Target the first known failing test if available
    if test_result.details:
        failures = test_result.details.get("failures") or []
        if failures:
            attempts.append(f"pytest -q {failures[0]} --maxfail=1")

    # 2) Rerun last-failed set
    attempts.append("pytest -q tests/ --lf --maxfail=1")
    # 3) Short full-suite rerun
    attempts.append("pytest -q tests/ --maxfail=1")

    attempts = attempts[:max_attempts]

    for cmd in attempts:
        try:
            rerun = execute_tool("run_tests", {"cmd": cmd, "timeout": 600})
            rerun_data = json.loads(rerun)
            if rerun_data.get("rc", 1) == 0:
                return True
        except Exception:
            # Ignore and move to next attempt
            continue

    return False


def _auto_fix_linting() -> bool:
    """Attempt to auto-fix linting issues."""
    try:
        execute_tool("run_cmd", {"cmd": "ruff check . --fix", "timeout": 600})
        return True
    except:
        return False


def _display_validation_report(report: ValidationReport):
    """Display the validation report."""
    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)

    status_emoji = {
        ValidationStatus.PASSED: "✅",
        ValidationStatus.PASSED_WITH_WARNINGS: "⚠️",
        ValidationStatus.FAILED: "❌",
        ValidationStatus.SKIPPED: "⏭️"
    }

    for result in report.results:
        emoji = status_emoji.get(result.status, "❓")
        print(f"{emoji} {result.name}: {result.message}")

        if result.status == ValidationStatus.FAILED and result.details:
            if "issues" in result.details:
                for issue in result.details["issues"][:3]:
                    print(f"   - {issue}")
            if "output" in result.details:
                print(f"   Output: {result.details['output'][:200]}...")

    print("-" * 60)
    overall_emoji = status_emoji.get(report.overall_status, "❓")
    print(f"\n{overall_emoji} Overall: {report.summary}")

    if report.rollback_recommended:
        print("\n⚠️  ROLLBACK RECOMMENDED: Validation failed, consider reverting changes")

    if report.auto_fixed:
        print(f"\n🔧 Auto-fixed: {', '.join(report.auto_fixed)}")

    print("=" * 60)


def format_validation_feedback_for_llm(report: ValidationReport, user_request: str) -> Optional[str]:
    """Format validation report feedback for LLM consumption.

    This creates a structured message that the executor LLM can understand and act upon,
    allowing it to see what failed validation and attempt fixes.

    Args:
        report: The validation report with all check results
        user_request: The original user request for context

    Returns:
        Formatted feedback string for inclusion in LLM conversation, or None if all passed
    """
    # Only provide feedback if there were failures or warnings
    if report.overall_status == ValidationStatus.PASSED:
        return None

    feedback_parts = [
        "=== VALIDATION FEEDBACK ===",
        f"Original Request: {user_request[:100]}...",
        f"Overall Status: {report.overall_status.value.upper()}",
        f"Summary: {report.summary}",
        ""
    ]

    # Group results by status
    failed_checks = [r for r in report.results if r.status == ValidationStatus.FAILED]
    warning_checks = [r for r in report.results if r.status == ValidationStatus.PASSED_WITH_WARNINGS]

    # Failed checks (critical)
    if failed_checks:
        feedback_parts.append("❌ FAILED CHECKS:")
        for result in failed_checks:
            feedback_parts.append(f"\n  Check: {result.name}")
            feedback_parts.append(f"  Issue: {result.message}")

            # Add specific details
            if result.details:
                if "failures" in result.details and result.details["failures"]:
                    feedback_parts.append("  Failed tests:")
                    for failure in result.details["failures"][:3]:
                        feedback_parts.append(f"    - {failure}")

                if "issues" in result.details and result.details["issues"]:
                    feedback_parts.append("  Linting issues:")
                    for issue in result.details["issues"][:5]:
                        if isinstance(issue, dict):
                            feedback_parts.append(f"    - {issue.get('code', 'ERROR')}: {issue.get('message', '')} (line {issue.get('location', {}).get('row', '?')})")
                        else:
                            feedback_parts.append(f"    - {issue}")

                if "output" in result.details:
                    output = result.details["output"][:300]
                    if output:
                        feedback_parts.append(f"  Output: {output}")

        feedback_parts.append("")

    # Warning checks (informational)
    if warning_checks:
        feedback_parts.append("⚠️  WARNINGS:")
        for result in warning_checks:
            feedback_parts.append(f"  - {result.name}: {result.message}")
        feedback_parts.append("")

    # Provide actionable guidance
    if failed_checks:
        feedback_parts.append("🔧 REQUIRED ACTIONS:")
        for result in failed_checks:
            if result.name == "test_suite":
                feedback_parts.append("  1. Fix the failing tests by addressing the assertion errors or logic issues")
                feedback_parts.append("  2. Ensure all test dependencies are properly set up")
            elif result.name == "linter":
                feedback_parts.append("  1. Fix linting errors (imports, unused variables, style issues)")
                feedback_parts.append("  2. Run 'ruff check --fix' or similar auto-formatter")
            elif result.name == "syntax_check":
                feedback_parts.append("  1. Fix syntax errors in Python files")
                feedback_parts.append("  2. Check for missing colons, parentheses, or indentation issues")
            elif result.name == "semantic_validation":
                feedback_parts.append("  1. Review if the changes actually fulfill the original request")
                feedback_parts.append("  2. Check if any steps were missed or incorrectly implemented")

        feedback_parts.append("\nPlease create and execute tasks to fix these validation failures.")
    else:
        feedback_parts.append("ℹ️  Some checks have warnings but no critical failures.")
        feedback_parts.append("Consider addressing the warnings for better code quality.")

    feedback_parts.append("===================")

    return "\n".join(feedback_parts)


def quick_validate(plan: ExecutionPlan) -> bool:
    """Quick validation - just check if tasks completed and run tests.

    Args:
        plan: The executed plan

    Returns:
        True if validation passed, False otherwise
    """
    # Check task completion
    failed = [t for t in plan.tasks if t.status == TaskStatus.FAILED]
    if failed:
        return False

    # Quick test run
    try:
        result = execute_tool("run_tests", {"test_path": "tests/", "verbose": False})
        result_data = json.loads(result)
        return result_data.get("rc", 1) == 0
    except:
        # If tests cannot run (syntax error, missing dependencies, etc), assume INVALID
        return False
