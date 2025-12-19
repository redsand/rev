#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical workspace path resolution for tools and verifiers.

All filesystem tools and verification steps should resolve paths through this
module to ensure consistent behavior and prevent "apply succeeded / verify
failed" split-brain path handling.

This module delegates to the Workspace singleton (rev.workspace) for the actual
path resolution logic. It re-exports the key classes for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

# Re-export classes from workspace module for backward compatibility
from rev.workspace import (
    WorkspacePathError,
    ResolvedWorkspacePath,
    get_workspace,
    normalize_path,
    normalize_to_workspace_relative,
    is_path_within_workspace,
    maybe_fix_tool_paths,
)

__all__ = [
    "WorkspacePathError",
    "ResolvedWorkspacePath",
    "resolve_workspace_path",
    "normalize_path",
    "normalize_to_workspace_relative",
    "is_path_within_workspace",
    "maybe_fix_tool_paths",
]


def resolve_workspace_path(
    path: Union[str, Path],
    *,
    purpose: str = "access",
) -> ResolvedWorkspacePath:
    """Resolve a path to an allowed absolute path within the workspace/allowlist.

    This function delegates to the Workspace singleton's resolve_path() method.

    Args:
        path: Incoming path (relative or absolute).
        purpose: Optional short label to improve error messages (e.g., "edit", "read").

    Returns:
        ResolvedWorkspacePath containing absolute path, a log-friendly rel_path,
        and the allowed root that contains it.

    Raises:
        WorkspacePathError: if the path is outside allowed roots.
    """
    return get_workspace().resolve_path(path, purpose=purpose)
