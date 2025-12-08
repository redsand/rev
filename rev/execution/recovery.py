#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recovery pattern for exception handling and graceful degradation.

This module implements the Exception Handling & Recovery pattern from Agentic
Design Patterns, providing systematic failure detection, structured recovery
strategies, and rollback capabilities.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

from rev.models.task import Task


class RecoveryStrategy(Enum):
    """Types of recovery strategies."""
    ROLLBACK = "rollback"  # Undo changes (git reset, restore files)
    RETRY = "retry"  # Try the operation again
    ALTERNATIVE = "alternative"  # Try a different approach
    MANUAL = "manual"  # Requires human intervention
    SKIP = "skip"  # Skip this task and continue
    ABORT = "abort"  # Stop execution entirely


@dataclass
class RecoveryAction:
    """A specific recovery action that can be executed.

    Recovery actions are concrete steps to handle a failure, such as
    running git commands, restoring files, or applying fixes.
    """
    description: str
    strategy: RecoveryStrategy
    commands: List[str] = field(default_factory=list)
    requires_approval: bool = True  # Whether human approval is needed
    risk_level: str = "medium"  # low, medium, high, critical
    estimated_success_rate: float = 0.5  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "description": self.description,
            "strategy": self.strategy.value,
            "commands": self.commands,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "estimated_success_rate": self.estimated_success_rate,
            "metadata": self.metadata
        }


class RecoveryPlanner:
    """Plans and executes recovery strategies for failed tasks.

    The RecoveryPlanner analyzes task failures and generates appropriate
    recovery actions based on the failure type, task characteristics, and
    system state.
    """

    def build_recovery_actions(self, task: Task, error_message: str = None) -> List[RecoveryAction]:
        """Build recovery actions for a failed task.

        Args:
            task: The failed task
            error_message: Optional error message describing the failure

        Returns:
            List of RecoveryAction objects, ordered by priority
        """
        actions = []

        # Strategy 1: Use explicit rollback plan if available
        if task.rollback_plan:
            actions.append(RecoveryAction(
                description=f"Execute rollback plan for task {task.task_id}",
                strategy=RecoveryStrategy.ROLLBACK,
                commands=self._parse_rollback_commands(task.rollback_plan),
                requires_approval=True,
                risk_level="high",
                estimated_success_rate=0.8,
                metadata={"rollback_plan": task.rollback_plan}
            ))

        # Strategy 2: Git-based recovery
        actions.extend(self._build_git_recovery_actions(task, error_message))

        # Strategy 3: Retry with modified approach
        if error_message:
            actions.extend(self._build_retry_actions(task, error_message))

        # Strategy 4: Skip and continue (for non-critical tasks)
        if task.risk_level.value in ["low", "medium"]:
            actions.append(RecoveryAction(
                description=f"Skip task {task.task_id} and continue with remaining tasks",
                strategy=RecoveryStrategy.SKIP,
                commands=[],
                requires_approval=False,
                risk_level="low",
                estimated_success_rate=1.0,
                metadata={"skipped_task_id": task.task_id}
            ))

        # Strategy 5: Manual intervention (always available as last resort)
        actions.append(RecoveryAction(
            description="Pause execution for manual review and intervention",
            strategy=RecoveryStrategy.MANUAL,
            commands=[],
            requires_approval=True,
            risk_level="low",
            estimated_success_rate=0.9,
            metadata={"manual_intervention_required": True}
        ))

        return actions

    def _parse_rollback_commands(self, rollback_plan: str) -> List[str]:
        """Parse commands from a rollback plan text.

        Extracts executable commands from rollback plan documentation.
        """
        commands = []
        for line in rollback_plan.splitlines():
            line = line.strip()

            # Look for command-like patterns (starting with known commands)
            if any(line.startswith(cmd) for cmd in ["git ", "rm ", "mv ", "cp ", "pytest ", "npm "]):
                commands.append(line)

        return commands

    def _build_git_recovery_actions(self, task: Task, error_message: str = None) -> List[RecoveryAction]:
        """Build git-based recovery actions."""
        actions = []

        # For edit/delete operations, offer git reset
        if task.action_type in ["edit", "delete"]:
            actions.append(RecoveryAction(
                description="Reset uncommitted changes using git",
                strategy=RecoveryStrategy.ROLLBACK,
                commands=[
                    "git status",  # Check status first
                    "git diff",    # Show changes
                    "git reset --hard HEAD"  # Reset (requires approval)
                ],
                requires_approval=True,
                risk_level="high",
                estimated_success_rate=0.95,
                metadata={"git_operation": "hard_reset"}
            ))

        # For add operations, offer git clean
        if task.action_type == "add":
            actions.append(RecoveryAction(
                description="Remove untracked files using git clean",
                strategy=RecoveryStrategy.ROLLBACK,
                commands=[
                    "git status",
                    "git clean -n",  # Dry run first
                    "git clean -fd"  # Force delete (requires approval)
                ],
                requires_approval=True,
                risk_level="medium",
                estimated_success_rate=0.9,
                metadata={"git_operation": "clean"}
            ))

        # Offer stash as a safer alternative
        actions.append(RecoveryAction(
            description="Stash changes for later review",
            strategy=RecoveryStrategy.ROLLBACK,
            commands=[
                "git stash push -m 'Recovery stash from failed task'"
            ],
            requires_approval=False,
            risk_level="low",
            estimated_success_rate=1.0,
            metadata={"git_operation": "stash"}
        ))

        return actions

    def _build_retry_actions(self, task: Task, error_message: str) -> List[RecoveryAction]:
        """Build retry-based recovery actions."""
        actions = []

        error_lower = error_message.lower() if error_message else ""

        # Test failures -> retry with --verbose
        if "test" in error_lower or "pytest" in error_lower:
            actions.append(RecoveryAction(
                description="Retry tests with verbose output for better diagnosis",
                strategy=RecoveryStrategy.RETRY,
                commands=["pytest -vv"],
                requires_approval=False,
                risk_level="low",
                estimated_success_rate=0.3,
                metadata={"retry_type": "verbose_tests"}
            ))

        # Import errors -> retry with dependency check
        if "import" in error_lower or "module" in error_lower:
            actions.append(RecoveryAction(
                description="Check and install missing dependencies",
                strategy=RecoveryStrategy.ALTERNATIVE,
                commands=[
                    "pip list",
                    "pip install -r requirements.txt"
                ],
                requires_approval=False,
                risk_level="low",
                estimated_success_rate=0.6,
                metadata={"retry_type": "dependency_fix"}
            ))

        # Syntax errors -> retry with linter auto-fix
        if "syntax" in error_lower or "invalid syntax" in error_lower:
            actions.append(RecoveryAction(
                description="Attempt auto-fix with code formatter",
                strategy=RecoveryStrategy.ALTERNATIVE,
                commands=["ruff check --fix ."],
                requires_approval=False,
                risk_level="low",
                estimated_success_rate=0.4,
                metadata={"retry_type": "auto_format"}
            ))

        return actions


def create_git_snapshot(description: str = "Pre-task snapshot") -> Optional[str]:
    """Create a git snapshot (tag or branch) before executing risky operations.

    This provides an easy rollback point if things go wrong.

    Args:
        description: Description for the snapshot

    Returns:
        Snapshot reference (tag or branch name), or None if failed
    """
    import subprocess
    from datetime import datetime

    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        # Create a lightweight tag for easy reference
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag_name = f"rev_snapshot_{timestamp}"

        result = subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", description],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return tag_name
        else:
            return None

    except Exception:
        return None


def apply_recovery_action(action: RecoveryAction, dry_run: bool = False) -> Dict[str, Any]:
    """Apply a recovery action.

    Args:
        action: The recovery action to apply
        dry_run: If True, simulate without executing

    Returns:
        Result dictionary with status and details
    """
    import subprocess

    result = {
        "success": False,
        "action": action.description,
        "strategy": action.strategy.value,
        "commands_executed": [],
        "outputs": [],
        "errors": []
    }

    if dry_run:
        result["success"] = True
        result["dry_run"] = True
        return result

    # Execute commands
    for cmd in action.commands:
        try:
            proc_result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )

            result["commands_executed"].append(cmd)
            result["outputs"].append(proc_result.stdout)

            if proc_result.returncode != 0:
                result["errors"].append({
                    "command": cmd,
                    "stderr": proc_result.stderr,
                    "returncode": proc_result.returncode
                })
                # Stop on first failure
                return result

        except subprocess.TimeoutExpired:
            result["errors"].append({
                "command": cmd,
                "error": "Command timeout"
            })
            return result
        except Exception as e:
            result["errors"].append({
                "command": cmd,
                "error": str(e)
            })
            return result

    # All commands succeeded
    result["success"] = True
    return result
