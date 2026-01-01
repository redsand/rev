"""Action-scoped tool constraints for recovery and validation."""

from __future__ import annotations

from typing import Iterable, Optional, Set


WRITE_ACTIONS: Set[str] = {
    "add",
    "create",
    "debug",
    "edit",
    "refactor",
    "delete",
    "rename",
    "move",
    "fix",
    "create_directory",
}

WRITE_TOOLS: Set[str] = {
    "write_file",
    "append_to_file",
    "replace_in_file",
    "apply_patch",
    "delete_file",
    "move_file",
    "copy_file",
    "create_directory",
    "split_python_module_classes",
    "rewrite_python_imports",
    "rewrite_python_keyword_args",
    "rename_imported_symbols",
    "move_imported_symbols",
    "rewrite_python_function_parameters",
    "remove_unused_imports",
}


def allowed_tools_for_action(action_type: Optional[str]) -> Optional[Set[str]]:
    """Return the allowed tool names for a given action type.

    Returns None when no constraint should be enforced.
    """
    action = (action_type or "").lower()
    if action in WRITE_ACTIONS:
        return set(WRITE_TOOLS)
    return None


def has_write_tool(tool_names: Iterable[str]) -> bool:
    """Return True if the tool list contains a write-capable tool."""
    for name in tool_names:
        if (name or "").lower() in WRITE_TOOLS:
            return True
    return False
