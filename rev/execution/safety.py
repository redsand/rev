"""
Safety checks and destructive operation validation for execution mode.

This module provides utilities for identifying and confirming potentially
destructive operations that require user approval.
"""

from typing import Dict, Any

# Cache of user decisions for scary operations. This avoids repeatedly prompting
# the user when the exact same potentially destructive action is attempted
# multiple times in a session.
_PROMPT_DECISIONS: Dict[tuple[str, str], bool] = {}


# Destructive operations that require confirmation
SCARY_OPERATIONS = {
    "keywords": ["delete", "remove", "rm ", "clean", "reset", "force", "destroy", "drop", "truncate"],
    "git_commands": ["reset --hard", "clean -f", "clean -fd", "push --force", "push -f"],
    "action_types": ["delete"]  # Task action types that are destructive
}


def is_scary_operation(tool_name: str, args: Dict[str, Any], action_type: str = "") -> tuple[bool, str]:
    """
    Check if an operation is potentially destructive and requires confirmation.

    Args:
        tool_name: Name of the tool being executed
        args: Dictionary of tool arguments
        action_type: Type of task action being performed

    Returns:
        (is_scary: bool, reason: str) - Tuple indicating if operation is scary and why
    """
    # Check action type
    if action_type in SCARY_OPERATIONS["action_types"]:
        return True, f"Destructive action type: {action_type}"

    # Check for file deletion
    if tool_name == "run_cmd":
        cmd = args.get("cmd", "").lower()

        # Check for dangerous git commands
        for git_cmd in SCARY_OPERATIONS["git_commands"]:
            if git_cmd in cmd:
                return True, f"Dangerous git command: {git_cmd}"

        # Check for scary keywords
        for keyword in SCARY_OPERATIONS["keywords"]:
            if keyword in cmd:
                return True, f"Potentially destructive command contains: {keyword}"

    # Check for patch operations without dry-run
    if tool_name == "apply_patch" and not args.get("dry_run", False):
        return True, "Applying patch (not dry-run)"

    return False, ""


def clear_prompt_decisions() -> None:
    """Clear cached scary-operation decisions (useful for tests)."""

    _PROMPT_DECISIONS.clear()


def prompt_scary_operation(operation: str, reason: str) -> bool:
    """
    Prompt user to confirm a scary operation.

    Args:
        operation: Description of the operation to confirm
        reason: Reason why this operation is considered dangerous

    Returns:
        True if user approves, False otherwise
    """
    key = (operation, reason)
    if key in _PROMPT_DECISIONS:
        return _PROMPT_DECISIONS[key]

    print(f"\n{'='*60}")
    print(f"⚠️  POTENTIALLY DESTRUCTIVE OPERATION DETECTED")
    print(f"{'='*60}")
    print(f"Operation: {operation}")
    print(f"Reason: {reason}")
    print(f"{'='*60}")

    try:
        response = input("Continue with this operation? [y/N]: ").strip().lower()
        decision = response in ["y", "yes"]
        _PROMPT_DECISIONS[key] = decision
        return decision
    except (KeyboardInterrupt, EOFError):
        print("\n[Cancelled by user]")
        _PROMPT_DECISIONS[key] = False
        return False
