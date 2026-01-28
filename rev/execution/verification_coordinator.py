"""
VerificationCoordinator - Handles verification and validation coordination.

This module is responsible for:
- Test signature tracking
- Verification result processing
- Test blocking/deduplication logic
- Code state tracking for test deduplication
"""

import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path

from rev.models.task import Task, TaskStatus
from rev.execution.quick_verify import VerificationResult
from rev.core.context import RevContext
from rev.workspace import get_workspace
from rev.terminal.formatting import colorize, Colors, Symbols


@dataclass
class TestSignature:
    """Represents a test signature for tracking."""
    signature: str
    seen_at: int
    last_result: str
    code_hash: Optional[str] = None
    blocked: bool = False
    blocked_reason: str = ""


@dataclass
class CodeStateSnapshot:
    """Snapshot of code state for tracking changes."""
    hash_value: str
    modified_files: List[str]
    timestamp: float


class VerificationCoordinator:
    """Coordinates verification and validation activities."""

    def __init__(self, orchestrator):
        """Initialize VerificationCoordinator with reference to orchestrator.

        Args:
            orchestrator: The Orchestrator instance for accessing shared state
        """
        self.orchestrator = orchestrator

    def compute_code_state_hash(self, modified_files: List[str] = None) -> str:
        """Compute a hash of the current code state based on modified files.

        Args:
            modified_files: List of files that were modified (default: all tracked files)

        Returns:
            A short hash (16 characters) representing the code state
        """
        workspace = get_workspace()
        root = workspace.root
        hasher = hashlib.sha256()

        if modified_files:
            # Hash only specific files
            for file_path in modified_files:
                try:
                    full_path = root / file_path
                    if full_path.exists():
                        content = full_path.read_text()
                        hasher.update(content.encode())
                except Exception:
                    pass
        else:
            # Hash all Python files in the repo
            for py_file in root.rglob("*.py"):
                # Skip test files and __pycache__
                if "__pycache__" in str(py_file) or "test" in py_file.name.lower():
                    continue
                try:
                    content = py_file.read_text()
                    hasher.update(content.encode())
                except Exception:
                    pass

        return hasher.hexdigest()[:16]

    def get_test_signature(self, task: Task) -> Optional[str]:
        """Generate a signature for a test task.

        Args:
            task: The task to generate a signature for

        Returns:
            A unique signature string, or None if not a test task
        """
        if task.action_type != "test":
            return None

        # Create signature from task description and action_type
        signature_parts = [task.description or "", task.action_type or ""]

        # Add any key parameters if they exist (optional attribute)
        if hasattr(task, 'parameters') and task.parameters:
            sorted_params = sorted(task.parameters.items())
            signature_parts.extend([f"{k}={v}" for k, v in sorted_params])

        return "||".join(signature_parts)

    def record_test_signature(self, context: RevContext, signature: str,
                             result: VerificationResult, code_hash: str = None) -> None:
        """Record a test signature for deduplication tracking.

        Args:
            context: The RevContext
            signature: The test signature
            result: The verification result
            code_hash: Optional code state hash at the time of test
        """
        seen_tests_key = "seen_test_signatures"
        seen_tests = context.agent_state.get(seen_tests_key, {})

        if not isinstance(seen_tests, dict):
            seen_tests = {}

        seen_tests[signature] = {
            "seen_at": context.agent_state.get("current_iteration", 0),
            "last_result": "pass" if result.passed else "fail",
            "code_hash": code_hash or self.compute_code_state_hash(),
        }

        context.set_agent_state(seen_tests_key, seen_tests)

    def is_test_blocked(self, context: RevContext, signature: str) -> bool:
        """Check if a test signature is blocked.

        A test is blocked if:
        1. It has been seen before
        2. The code state hasn't changed (same code hash)
        3. It was blocked previously

        Args:
            context: The RevContext
            signature: The test signature to check

        Returns:
            True if the test is blocked
        """
        seen_tests_key = "seen_test_signatures"
        seen_tests = context.agent_state.get(seen_tests_key, {})

        if not isinstance(seen_tests, dict) or signature not in seen_tests:
            return False

        seen_data = seen_tests[signature]
        current_code_hash = self.compute_code_state_hash()
        seen_code_hash = seen_data.get("code_hash") if isinstance(seen_data, dict) else None
        last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
        current_iteration = context.agent_state.get("current_iteration", 0)

        # Allow first-run tests; only dedupe when code hash matches
        if (
            isinstance(last_code_change_iteration, int)
            and isinstance(seen_data, dict)
            and last_code_change_iteration >= 0
            and last_code_change_iteration == seen_data.get("seen_at")
            and seen_code_hash is not None
            and seen_code_hash == current_code_hash
        ):
            # Same code state - block duplicate test
            return True

        # Check if explicitly blocked
        blocked_tests = context.agent_state.get("blocked_test_signatures", {})
        if isinstance(blocked_tests, dict) and signature in blocked_tests:
            return True

        return False

    def block_test_signature(self, context: RevContext, signature: str, reason: str = "") -> None:
        """Mark a test signature as blocked.

        Args:
            context: The RevContext
            signature: The test signature to block
            reason: Optional reason for blocking
        """
        blocked_tests_key = "blocked_test_signatures"
        blocked_tests = context.agent_state.get(blocked_tests_key, {})

        if not isinstance(blocked_tests, dict):
            blocked_tests = {}

        blocked_tests[signature] = {
            "blocked_iteration": context.agent_state.get("current_iteration"),
            "code_change_iteration": context.agent_state.get("last_code_change_iteration", -1),
            "reason": reason,
        }

        context.set_agent_state(blocked_tests_key, blocked_tests)

    def get_failing_test_file(self, verification_result: VerificationResult) -> Optional[str]:
        """Extract the failing test file from a verification result.

        Args:
            verification_result: The VerificationResult to analyze

        Returns:
            The path to the failing test file, or None if not found
        """
        if not verification_result:
            return None

        # Check details for test file information
        details = verification_result.details or {}
        if isinstance(details, dict):
            # Check for explicit test file field
            if "test_file" in details:
                return details["test_file"]

            # Check output for test file patterns
            output = details.get("output", "")
            if isinstance(output, str):
                # Look for patterns like "test_foo.py", "tests/bar.py", etc.
                import re
                test_file_match = re.search(r'([\w/\\]+test_\w+\.py|[\w/\\]+\w+_test\.py)', output)
                if test_file_match:
                    return test_file_match.group(1)

            # Check stderr for pytest failure patterns
            stderr = details.get("stderr", "")
            if isinstance(stderr, str):
                test_file_match = re.search(r'([\w/\\]+test_\w+\.py|[\w/\\]+\w+_test\.py)', stderr)
                if test_file_match:
                    return test_file_match.group(1)

        return None

    def record_code_change(self, context: RevContext, modified_files: List[str] = None) -> None:
        """Record a code change for test deduplication.

        Args:
            context: The RevContext
            modified_files: List of files that were modified
        """
        current_iteration = context.agent_state.get("current_iteration", 0)
        context.set_agent_state("last_code_change_iteration", current_iteration)

        # Record the code state hash
        code_hash = self.compute_code_state_hash(modified_files)
        context.set_agent_state("current_code_hash", code_hash)

    def should_skip_test(self, context: RevContext, task: Task) -> bool:
        """Determine if a test should be skipped based on deduplication logic.

        Args:
            context: The RevContext
            task: The test task to check

        Returns:
            True if the test should be skipped
        """
        signature = self.get_test_signature(task)
        if not signature:
            return False

        return self.is_test_blocked(context, signature)

    def display_verification_summary(self, result: VerificationResult, task: Task = None):
        """Display a summary of verification results.

        Args:
            result: The VerificationResult to display
            task: Optional task that was verified
        """
        if result.passed:
            print(f"  {colorize('✓', Colors.BRIGHT_GREEN)} {colorize('Verification Passed', Colors.BRIGHT_GREEN)}")
        elif getattr(result, 'inconclusive', False):
            print(f"  {colorize('?', Colors.BRIGHT_YELLOW)} {colorize('Verification Inconclusive', Colors.BRIGHT_YELLOW)}")
        else:
            print(f"  {colorize('✗', Colors.BRIGHT_RED)} {colorize('Verification Failed', Colors.BRIGHT_RED)}")

        if task:
            print(f"    Task: {task.description or 'N/A'}")

        if result.message:
            print(f"    {result.message}")