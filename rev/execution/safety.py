"""
Safety checks and destructive operation validation for execution mode.

This module provides utilities for identifying and confirming potentially
destructive operations that require user approval.
"""

from typing import Dict, Any

# ANSI color codes for highlighting patch previews
_COLOR_RED = "\033[31m"
_COLOR_GREEN = "\033[32m"
_COLOR_CYAN = "\033[36m"
_COLOR_RESET = "\033[0m"

# Patch preview configuration
_PATCH_PREVIEW_LINES = 60
_PATCH_INDENT = "    "

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


def _color_line(line: str) -> str:
    """Apply simple coloring to diff lines for terminal display."""

    if line.startswith("+++") or line.startswith("---"):
        return f"{_COLOR_CYAN}{line}{_COLOR_RESET}"
    if line.startswith("@@"):
        return f"{_COLOR_CYAN}{line}{_COLOR_RESET}"
    if line.startswith("+"):
        return f"{_COLOR_GREEN}{line}{_COLOR_RESET}"
    if line.startswith("-"):
        return f"{_COLOR_RED}{line}{_COLOR_RESET}"
    return line


def _format_apply_patch_operation(args: Dict[str, Any]) -> str:
    """Create a readable, colorized description for apply_patch operations."""

    patch = str(args.get("patch", ""))
    dry_run = args.get("dry_run", False)

    if not patch.strip():
        return "apply_patch(no patch content)"

    lines = patch.splitlines()
    preview = lines[:_PATCH_PREVIEW_LINES]
    hidden = lines[_PATCH_PREVIEW_LINES:]

    total_additions = sum(1 for l in lines if l.startswith("+"))
    total_subtractions = sum(1 for l in lines if l.startswith("-"))
    hidden_additions = sum(1 for l in hidden if l.startswith("+"))
    hidden_subtractions = sum(1 for l in hidden if l.startswith("-"))

    header = f"apply_patch{' (dry run)' if dry_run else ''}"
    description = [f"{header} patch preview (showing {len(preview)} of {len(lines)} lines)"]

    for line in preview:
        description.append(f"{_PATCH_INDENT}{_color_line(line)}")

    if hidden:
        description.append(
            f"{_PATCH_INDENT}… (hidden {len(hidden)} lines: +{hidden_additions}/-{hidden_subtractions})"
        )

    description.append(
        f"{_PATCH_INDENT}Totals in patch: +{total_additions}/-{total_subtractions}"
    )

    return "\n".join(description)


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


def format_operation_description(tool_name: str, args: Dict[str, Any]) -> str:
    """Generate a readable description for scary-operation prompts."""

    if tool_name == "apply_patch":
        return _format_apply_patch_operation(args)

    # Fallback to a simple representation for other tools
    return f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(args.items())[:3])})"


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
    operation_display = operation if "\n" not in operation else f"\n{operation}"
    print(f"Operation: {operation_display}")
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
