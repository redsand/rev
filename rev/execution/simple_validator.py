"""
Simple and effective validation system like Claude Code.

This validator:
1. Runs the actual tests
2. Parses failures (test names, error messages, stack traces)
3. Returns formatted feedback for the LLM
4. Enables retry loop with test feedback

Minimal, focused, and effective.
"""

import re
import json
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Fix Windows encoding issues - only wrap once
if sys.platform == "win32" and not hasattr(sys.stdout, 'encoding') or sys.stdout.encoding != 'utf-8':
    try:
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')
        os.environ["PYTHONIOENCODING"] = "utf-8"
    except (AttributeError, Exception):
        # If stdout doesn't have buffer attribute, skip
        pass


@dataclass
class TestFailure:
    """A single test failure with details."""
    test_name: str
    error_type: str
    error_message: str
    stack_trace: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class ValidationResult:
    """Result of running tests."""
    passed: bool
    total_tests: int
    passed_tests: int
    failed_tests: int
    failures: List[TestFailure]
    raw_output: str
    command: str


class SimpleValidator:
    """Simple test runner and failure parser."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def run_tests(
        self,
        test_cmd: Optional[str] = None,
        timeout: int = 120
    ) -> ValidationResult:
        """Run tests and parse results.

        Args:
            test_cmd: Test command to run. If None, auto-detect.
            timeout: Timeout in seconds.

        Returns:
            ValidationResult with test results and failures.
        """
        # Auto-detect test command if not provided
        if test_cmd is None:
            test_cmd = self._detect_test_command()

        print(f"\n[Validation] Running tests: {test_cmd}")

        try:
            # Use encoding='utf-8' and errors='replace' for Windows compatibility
            result = subprocess.run(
                test_cmd,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                failures=[],
                raw_output=f"Test timeout after {timeout}s",
                command=test_cmd
            )

        # Handle None stdout/stderr
        stdout = result.stdout if result.stdout else ""
        stderr = result.stderr if result.stderr else ""
        raw_output = stdout + "\n" + stderr
        failures = self._parse_test_failures(raw_output)

        # Count tests
        total, passed, failed = self._count_tests(raw_output, len(failures))

        return ValidationResult(
            passed=result.returncode == 0 and len(failures) == 0,
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            failures=failures,
            raw_output=raw_output,
            command=test_cmd
        )

    def _detect_test_command(self) -> str:
        """Auto-detect the appropriate test command."""
        # Look for common test files in root
        root = self.project_root

        # Check for pytest
        if (root / "pytest.ini").exists() or \
           (root / "pyproject.toml").exists() or \
           any(root.glob("test_*.py")) or \
           any((root / "tests").glob("*.py")):
            return "python -m pytest -v"

        # Check for jest
        if (root / "package.json").exists():
            pkg_json = (root / "package.json").read_text()
            if '"test"' in pkg_json or '"jest"' in pkg_json:
                return "npm test"

        # Default to pytest for Python
        return "python -m pytest -v"

    def _parse_test_failures(self, output: str) -> List[TestFailure]:
        """Parse test failures from pytest output.

        Returns list of TestFailure objects.
        """
        failures = []

        # Pattern for pytest failures
        # Looks like:
        # FAILED test_string_utils.py::TestReverseString::test_reverse_string_none
        # assert False
        # E   AssertionError: expected True but got False
        # E   assert reverse_string(None) is True

        # Match: FAILED <file>::<class>::<method>
        failed_test_pattern = r'^FAILED\s+([^\s:]+::[^\s:]+::[^\s:]+)'

        # Find all failed test blocks
        lines = output.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]

            match = re.match(failed_test_pattern, line)
            if match:
                test_name = match.group(1)
                # Extract file from test name
                file_match = re.match(r'^([^:]+)::', test_name)
                file_path = file_match.group(1) if file_match else None

                # Find the error (usually starts with "E   " a few lines later)
                error_type = "Error"
                error_message = ""
                stack_trace = []
                j = i + 1

                while j < min(i + 20, len(lines)):
                    error_line = lines[j]
                    stack_trace.append(error_line)

                    # Error type and message patterns
                    type_msg_match = re.match(r'^\s+E\s+(?:assert|AssertionError|TypeError|AttributeError|ValueError|ImportError|SyntaxError|KeyError|IndexError|NameError|RuntimeError)\s*:(.+)$', error_line)
                    if type_msg_match:
                        parts = error_line.strip().split(maxsplit=2)
                        if len(parts) >= 2:
                            error_type = parts[1].rstrip(':')
                        if len(parts) >= 3:
                            error_message = parts[2]

                    # Stop at next FAILED or test summary
                    if re.match(r'^(FAILED|PASSED|=)', error_line) or 'test session starts' in error_line.lower():
                        break

                    j += 1

                failures.append(TestFailure(
                    test_name=test_name,
                    error_type=error_type,
                    error_message=error_message or "See stack trace",
                    stack_trace='\n'.join(stack_trace),
                    file_path=file_path,
                    line_number=self._extract_line_number(stack_trace)
                ))
                i = j
            else:
                i += 1

        return failures

    def _extract_line_number(self, stack_lines: List[str]) -> Optional[int]:
        """Extract line number from stack trace."""
        for line in stack_lines:
            # Pattern: file.py:123
            match = re.search(r':(\d+)\]', line) or re.search(r'\.py:(\d+)', line)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass
        return None

    def _count_tests(self, output: str, num_failures: int) -> Tuple[int, int, int]:
        """Count total, passed, and failed tests from output."""
        # Look for pytest summary: "23 passed, 5 failed"
        summary_match = re.search(r'(\d+)\s+passed.*?(\d+)\s+failed', output)
        if summary_match:
            passed = int(summary_match.group(1))
            failed = int(summary_match.group(2))
            return passed + failed, passed, failed

        # Fallback: count from failures and assume some passed
        if num_failures > 0:
            return num_failures + 1, 1, num_failures

        # Check for "X passed"
        passed_match = re.search(r'(\d+)\s+passed', output)
        if passed_match:
            passed = int(passed_match.group(1))
            return passed, passed, 0

        # Count FAILED lines
        failed_count = output.count('\nFAILED ')
        if failed_count > 0:
            return failed_count + 1, 1, failed_count

        return 0, 0, 0

    def format_feedback_for_llm(self, result: ValidationResult) -> Optional[str]:
        """Format test failures as feedback for the LLM.

        Returns None if all tests passed.
        """
        if result.passed:
            return None

        lines = [
            "=" * 60,
            "VALIDATION FAILED - TEST RESULTS",
            "=" * 60,
            f"Tests: {result.passed_tests}/{result.total_tests} passed",
            f"Failed: {result.failed_tests}",
            ""
        ]

        if result.failures:
            lines.append("FAILED TESTS:")
            for i, failure in enumerate(result.failures, 1):
                lines.append(f"\n{i}. {failure.test_name}")
                if failure.file_path:
                    lines.append(f"   File: {failure.file_path}")
                    if failure.line_number:
                        lines.append(f"   Line: {failure.line_number}")
                lines.append(f"   Error: {failure.error_type}")
                if failure.error_message and failure.error_message != "See stack trace":
                    lines.append(f"   Message: {failure.error_message}")

                # Show first few lines of stack trace
                if failure.stack_trace:
                    trace_lines = failure.stack_trace.split('\n')[:5]
                    for trace_line in trace_lines:
                        if trace_line.strip():
                            lines.append(f"   {trace_line.strip()}")

        lines.append("")
        lines.append("Please fix these test failures by modifying the code.")
        lines.append("=" * 60)

        return "\n".join(lines)


def validate_and_fix(
    project_root: Path,
    user_request: str,
    test_cmd: Optional[str] = None,
    max_retries: int = 3,
    timeout: int = 120
) -> Tuple[bool, int, List[TestFailure]]:
    """Run validation with automatic retry loop.

    This is the main entry point for the new validation system.

    Args:
        project_root: Path to the project root
        user_request: Original user request for context
        test_cmd: Test command to run (auto-detected if None)
        max_retries: Maximum number of fix attempts
        timeout: Timeout for each test run in seconds

    Returns:
        Tuple of (success, attempts_made, final_failures)
    """
    validator = SimpleValidator(project_root)

    for attempt in range(1, max_retries + 1):
        result = validator.run_tests(test_cmd, timeout)

        if result.passed:
            print(f"\n✅ All tests passed (attempt {attempt})")
            return True, attempt, []

        print(f"\n❌ Tests failed (attempt {attempt}/{max_retries})")

        # Format feedback for LLM
        feedback = validator.format_feedback_for_llm(result)
        print(feedback)

        # Return feedback to caller for LLM to process
        # The caller (orchestrator) will need to pass this to the executor
        return False, attempt, result.failures

    return False, max_retries, []