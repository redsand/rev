"""
RecoveryManager - Handles error recovery and circuit breaking.

This module is responsible for:
- Per-error-type recovery budget tracking
- Circuit breaker triggering
- Generic repair task generation
- Failure summary generation
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from rev.models.task import Task
from rev.execution.quick_verify import VerificationResult
from rev.tools.errors import ToolErrorType
from rev.terminal.formatting import colorize, Colors, Symbols


@dataclass
class RecoveryBudget:
    """Tracks recovery budget for a specific error type and signature."""
    budget_key: str
    error_type: ToolErrorType
    current_attempts: int
    max_attempts: int

    @property
    def exhausted(self) -> bool:
        """Check if the recovery budget is exhausted."""
        return self.current_attempts >= self.max_attempts

    @property
    def remaining(self) -> int:
        """Get remaining recovery attempts."""
        return max(0, self.max_attempts - self.current_attempts)


class RecoveryManager:
    """Manages error recovery budgets and circuit breaking logic."""

    # Default max attempts per error type
    MAX_ATTEMPTS_PER_ERROR_TYPE = {
        # Transient errors - allow more retries
        ToolErrorType.TRANSIENT: 8,
        ToolErrorType.TIMEOUT: 5,
        ToolErrorType.NETWORK: 5,

        # Recoverable errors - moderate retries
        ToolErrorType.NOT_FOUND: 3,
        ToolErrorType.SYNTAX_ERROR: 3,
        ToolErrorType.VALIDATION_ERROR: 3,

        # Non-recoverable errors - minimal retries
        ToolErrorType.PERMISSION_DENIED: 1,
        ToolErrorType.CONFLICT: 2,

        # Unknown - be conservative
        ToolErrorType.UNKNOWN: 5,
    }

    def __init__(self, orchestrator):
        """Initialize RecoveryManager with reference to orchestrator.

        Args:
            orchestrator: The Orchestrator instance for accessing shared state
        """
        self.orchestrator = orchestrator

    def classify_error(self, verification_result: Optional[VerificationResult],
                      task: Optional[Task] = None) -> ToolErrorType:
        """Classify a verification result into a ToolErrorType for budget tracking.

        Args:
            verification_result: The VerificationResult from quick_verify
            task: Optional task being executed (for additional context)

        Returns:
            ToolErrorType enum value indicating the error type
        """
        if not verification_result:
            return ToolErrorType.UNKNOWN

        # Get error details - check message first, then details
        message = str(verification_result.message).lower() if verification_result.message else ""
        details = str(verification_result.details).lower() if verification_result.details else ""

        # Special case: HTTP 404 with route/endpoint context is SYNTAX_ERROR (routing issue)
        if '404' in message and ('route' in message or 'endpoint' in message):
            return ToolErrorType.SYNTAX_ERROR

        # Define all error type patterns (without 404 in NOT_FOUND since we handle it specially)
        ERROR_PATTERNS = [
            (ToolErrorType.PERMISSION_DENIED, [
                'permission denied',
                'access denied',
                'eacces',
                'eperm',
                'forbidden',
                'unauthorized',
            ]),
            (ToolErrorType.NOT_FOUND, [
                'not found',
                'no such file',
                'file does not exist',
                'enoent',
                'cannot find module',
                'module not found',
                "cannot import",
            ]),
            (ToolErrorType.TIMEOUT, [
                'timeout',
                'timed out',
                'deadline exceeded',
                'operation timed out',
                'timeouterror',
            ]),
            (ToolErrorType.NETWORK, [
                'network',
                'connection refused',
                'connection reset',
                'connection timeout',
                'econnrefused',
                'econnreset',
                'enotunreach',
                'dns error',
                'host unreachable',
                'server unavailable',
            ]),
            (ToolErrorType.SYNTAX_ERROR, [
                'syntaxerror',
                'syntax error',
                'indentationerror',
                'unexpected token',
                'invalid syntax',
                'parse error',
                'unexpected indent',
            ]),
            (ToolErrorType.VALIDATION_ERROR, [
                'validation',
                'invalid input',
                'invalid argument',
                'type error',
                'typeerror',
                'value error',
                'valueerror',
                'validation error',
            ]),
            (ToolErrorType.CONFLICT, [
                'conflict',
                'duplicate',
                'already exists',
                'primary key',
                'unique constraint',
                'eexist',
            ]),
            (ToolErrorType.TRANSIENT, [
                'temporary',
                'temporarily',
                'service unavailable',
                '503',
                'too many requests',
                '429',
                'rate limit',
                'database is locked',
                'database busy',
                'deadlock',
            ]),
        ]

        # Helper to check patterns in a string
        def check_patterns(patterns: List[str], text: str) -> Optional[str]:
            for pattern in patterns:
                if pattern in text:
                    return pattern
            return None

        # Check message first (higher priority)
        for error_type, patterns in ERROR_PATTERNS:
            if check_patterns(patterns, message):
                return error_type

        # Fallback to checking details
        for error_type, patterns in ERROR_PATTERNS:
            if check_patterns(patterns, details):
                return error_type

        # Default to unknown
        return ToolErrorType.UNKNOWN

    def build_failure_summary(self, task: Task, verification_result,
                            failure_sig: str, failure_count: int) -> str:
        """Build a detailed failure summary for circuit breaker context.

        Args:
            task: The task that failed
            verification_result: The verification result showing failure details
            failure_sig: The error signature for this failure
            failure_count: How many times this error has occurred

        Returns:
            A detailed failure summary string
        """
        # Build a comprehensive summary
        parts = [
            f"Task: {task.description or 'N/A'}",
            f"Action Type: {task.action_type or 'N/A'}",
            f"Error Signature: {failure_sig}",
            f"Failure Count: {failure_count}",
        ]

        # Add error message if available
        if verification_result:
            if verification_result.message:
                parts.append(f"Error: {verification_result.message}")
            if verification_result.details:
                details_str = str(verification_result.details)
                if len(details_str) > 200:
                    details_str = details_str[:200] + "..."
                parts.append(f"Details: {details_str}")

        # Add task-specific info
        if task.error:
            error_str = task.error
            if len(error_str) > 200:
                error_str = error_str[:200] + "..."
            parts.append(f"Task Error: {error_str}")

        return "\n".join(parts)

    def get_recovery_budget(self, context, budget_key: str,
                           error_type: ToolErrorType) -> RecoveryBudget:
        """Get the recovery budget for a specific error signature.

        Args:
            context: The RevContext
            budget_key: The budget key (format: "{error_type.value}::{failure_sig}")
            error_type: The error type for this failure

        Returns:
            A RecoveryBudget object tracking the state
        """
        recovery_budgets_key = "recovery_budgets"
        recovery_budgets = context.agent_state.get(recovery_budgets_key, {})
        current_attempts = recovery_budgets.get(budget_key, 0)

        max_attempts = self.MAX_ATTEMPTS_PER_ERROR_TYPE.get(error_type, 5)

        return RecoveryBudget(
            budget_key=budget_key,
            error_type=error_type,
            current_attempts=current_attempts,
            max_attempts=max_attempts
        )

    def increment_recovery_budget(self, context, budget_key: str) -> int:
        """Increment the recovery budget for a specific error signature.

        Args:
            context: The RevContext
            budget_key: The budget key to increment

        Returns:
            The new attempt count
        """
        recovery_budgets_key = "recovery_budgets"
        recovery_budgets = context.agent_state.get(recovery_budgets_key, {})
        current_attempts = recovery_budgets.get(budget_key, 0)

        new_attempts = current_attempts + 1
        recovery_budgets[budget_key] = new_attempts
        context.set_agent_state(recovery_budgets_key, recovery_budgets)

        return new_attempts

    def should_trigger_circuit_breaker(self, budget: RecoveryBudget) -> bool:
        """Check if circuit breaker should be triggered for this budget.

        Args:
            budget: The RecoveryBudget to check

        Returns:
            True if circuit breaker should be triggered
        """
        return budget.exhausted

    def display_verification_failure(self, verification_result: VerificationResult):
        """Handle and display detailed information about verification failures.

        P0-6: Distinguish inconclusive results from actual failures.

        Args:
            verification_result: The VerificationResult to display
        """
        # P0-6: Use different colors/symbols for inconclusive vs failed
        if getattr(verification_result, 'inconclusive', False):
            print(f"\n{colorize('  ' + Symbols.WARNING + ' Verification Inconclusive', Colors.BRIGHT_YELLOW, bold=True)}")
            message_color = Colors.BRIGHT_YELLOW
        else:
            print(f"\n{colorize('  ' + Symbols.CROSS + ' Verification Details', Colors.BRIGHT_RED, bold=True)}")
            message_color = Colors.BRIGHT_RED

        # Display main message (which includes issue descriptions)
        if verification_result.message:
            print(f"    {colorize(verification_result.message, message_color)}")

        # Display debug information if available
        if verification_result.details and "debug" in verification_result.details:
            debug_info = verification_result.details["debug"]
            for key, value in debug_info.items():
                print(f"    {colorize(key + ':', Colors.BRIGHT_BLACK)} {value}")

        # Display test output for failed tests (from test execution)
        details = verification_result.details or {}
        test_output = details.get("output", "")
        if test_output and isinstance(test_output, str) and test_output.strip():
            print(f"\n    {colorize('Test Output:', Colors.BRIGHT_BLACK)}")
            # Show last 15 lines of test output for context
            for line in test_output.strip().splitlines()[-15:]:
                print(f"      {line}")

        # Display strict/validation command outputs (compileall/pytest/etc)
        for block_key in ("strict", "validation"):
            block = details.get(block_key)
            if not isinstance(block, dict) or not block:
                continue
            for label, res in block.items():
                if not isinstance(res, dict):
                    continue
                rc = res.get("rc")
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()

                if rc is not None and rc != 0:
                    print(f"    {colorize('[' + label + '] failed (rc=' + str(rc) + ')', Colors.BRIGHT_YELLOW)}")
                    if stdout:
                        for line in str(stdout).splitlines()[-5:]: # Only show last 5 lines
                            print(f"      {colorize('stdout:', Colors.BRIGHT_BLACK)} {line}")
                    if stderr:
                        for line in str(stderr).splitlines()[-5:]:
                            print(f"      {colorize('stderr:', Colors.BRIGHT_BLACK)} {line}")

        # P0-6: Different message for inconclusive vs failed
        if getattr(verification_result, 'inconclusive', False):
            print("\n[NEXT ACTION: Run validation to confirm changes are correct (tests/syntax checks)...]\n")
        else:
            print("\n[NEXT ACTION: Adjusting approach based on feedback...]\n")