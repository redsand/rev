#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workspace: single source of truth for path handling in rev.

This module provides a centralized Workspace class that manages:
- Tool execution base directory
- Verifier base directory
- Path normalization rules (Windows/POSIX)
- Allowlist for external paths (via additional_roots)

All path validation flows through the Workspace to ensure consistent behavior
across tools, verifiers, and other components.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union


class WorkspacePathError(ValueError):
    """Raised when a path is invalid or outside allowed workspace roots."""


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    """A validated workspace path.

    Attributes:
        abs_path: Absolute path after resolution.
        rel_path: Relative path for logging (uses forward slashes).
        allowed_root: Which allowed root contains this path.
    """

    abs_path: Path
    rel_path: str
    allowed_root: Path


@dataclass
class Workspace:
    """Single source of truth for workspace path handling.

    Attributes:
        root: Primary workspace root directory.
        allow_external_paths: Whether to allow absolute paths outside the primary
            root (must still be in additional_roots allowlist).
        additional_roots: List of additional allowed directories (allowlist).
    """

    root: Path
    allow_external_paths: bool = False
    additional_roots: List[Path] = field(default_factory=list)

    # Derived paths (computed in __post_init__)
    rev_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)
    checkpoints_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    sessions_dir: Path = field(init=False)
    memory_dir: Path = field(init=False)
    metrics_dir: Path = field(init=False)
    artifacts_dir: Path = field(init=False)
    tool_outputs_dir: Path = field(init=False)
    project_memory_file: Path = field(init=False)
    settings_file: Path = field(init=False)
    test_marker_file: Path = field(init=False)
    history_file: Path = field(init=False)

    def __post_init__(self) -> None:
        """Compute derived paths from root."""
        # Ensure root is resolved
        object.__setattr__(self, "root", self.root.expanduser().resolve())

        # Auto-register additional roots from environment (REV_ADDITIONAL_ROOTS)
        # Accept a pathsep-separated list of directories.
        extra_roots_env = os.getenv("REV_ADDITIONAL_ROOTS", "")
        if extra_roots_env:
            for raw_path in extra_roots_env.split(os.pathsep):
                candidate = raw_path.strip()
                if not candidate:
                    continue
                try:
                    self.register_additional_root(Path(candidate))
                except Exception:
                    # Ignore invalid entries; workspace resolution will still validate paths.
                    pass

        # Compute derived paths
        rev_dir = self.root / ".rev"
        object.__setattr__(self, "rev_dir", rev_dir)
        object.__setattr__(self, "cache_dir", rev_dir / "cache")
        object.__setattr__(self, "checkpoints_dir", rev_dir / "checkpoints")
        object.__setattr__(self, "logs_dir", rev_dir / "logs")
        object.__setattr__(self, "sessions_dir", rev_dir / "sessions")
        object.__setattr__(self, "memory_dir", rev_dir / "memory")
        object.__setattr__(self, "metrics_dir", rev_dir / "metrics")
        object.__setattr__(self, "artifacts_dir", rev_dir / "artifacts")
        object.__setattr__(self, "tool_outputs_dir", rev_dir / "artifacts" / "tool_outputs")
        object.__setattr__(self, "project_memory_file", rev_dir / "memory" / "project_summary.md")
        object.__setattr__(self, "settings_file", rev_dir / "settings.json")
        object.__setattr__(self, "test_marker_file", rev_dir / "test")
        object.__setattr__(self, "history_file", rev_dir / "history")

    def get_allowed_roots(self) -> List[Path]:
        """Return the primary root plus any additional allowed roots."""
        return [self.root, *self.additional_roots]

    def register_additional_root(self, path: Path) -> None:
        """Register an additional root directory that tools may access.

        Args:
            path: Directory to add to the allowlist.

        Raises:
            ValueError: If the path is not a directory.
        """
        resolved = path.resolve()
        if not resolved.is_dir():
            raise ValueError(f"Additional root must be a directory: {path}")
        if resolved not in self.additional_roots:
            self.additional_roots.append(resolved)

    def is_path_allowed(self, abs_path: Path) -> bool:
        """Check if an absolute path is within any allowed root.

        Args:
            abs_path: Absolute path to check.

        Returns:
            True if the path is within an allowed root, False otherwise.
        """
        for allowed_root in self.get_allowed_roots():
            if _is_within_root(abs_path, allowed_root):
                return True
        return False

    def resolve_path(
        self,
        path: Union[str, Path],
        *,
        purpose: str = "access",
    ) -> ResolvedWorkspacePath:
        """Resolve a path to an allowed absolute path within the workspace/allowlist.

        Args:
            path: Incoming path (relative or absolute).
            purpose: Optional short label to improve error messages.

        Returns:
            ResolvedWorkspacePath containing absolute path, log-friendly rel_path,
            and the allowed root that contains it.

        Raises:
            WorkspacePathError: If the path is outside allowed roots.
        """
        raw = _clean_path_input(path)

        # Guard against LLM "nesting" mistake: prefixing workspace-relative path
        # with the workspace folder name (e.g., in `C:\repo\project` emitting
        # `project/src/...` which creates `<ROOT>/project/src`).
        try:
            raw_norm = raw.replace("\\", "/")
            if not Path(raw).is_absolute():
                root_name = self.root.name
                if raw_norm.lower() == root_name.lower():
                    raw = "."
                elif raw_norm.lower().startswith(root_name.lower() + "/"):
                    raw = raw_norm[len(root_name) + 1 :]
        except Exception:
            pass

        candidate = Path(raw)
        is_absolute_input = candidate.is_absolute()

        if not is_absolute_input:
            candidate = self.root / candidate

        # strict=False: allow resolving paths that don't exist yet (create/write flows).
        abs_path = candidate.resolve(strict=False)

        deduped = _dedupe_redundant_prefix_path(abs_path, self.root)
        if deduped and deduped != abs_path:
            abs_path = deduped

        # Check if path is within allowed roots
        allowed_roots = [r.resolve() for r in self.get_allowed_roots()]
        for allowed_root in allowed_roots:
            if _is_within_root(abs_path, allowed_root):
                try:
                    rel = abs_path.relative_to(self.root).as_posix()
                except Exception:
                    # For additional roots, keep relative view from root for log consistency.
                    rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
                return ResolvedWorkspacePath(
                    abs_path=abs_path, rel_path=rel, allowed_root=allowed_root
                )

        # Path is outside allowed roots - determine the right error message
        if is_absolute_input and not self.allow_external_paths:
            # Absolute path but external paths not enabled
            raise WorkspacePathError(
                f"Path is outside the current workspace: '{raw}'. "
                f"Provide --workspace {abs_path.parent} or enable external paths via --allow-external-paths."
            )
        else:
            # Either relative path that escaped, or external paths enabled but not in allowlist
            allowed_list = ", ".join(str(r) for r in allowed_roots)
            if self.allow_external_paths:
                raise WorkspacePathError(
                    f"Path is outside allowed workspace roots for {purpose}: '{raw}'. "
                    f"Allowed roots: {allowed_list}. "
                    "Add an allowed root via '/add-dir <path>'."
                )
            else:
                raise WorkspacePathError(
                    f"Path is outside the current workspace: '{raw}'. "
                    f"Provide --workspace {abs_path.parent} or enable external paths via --allow-external-paths."
                )


def _dedupe_redundant_prefix_path(abs_path: Path, root: Path) -> Optional[Path]:
    """
    Collapse accidental repeated leading segments like
    '<root>/src/module/src/module/__init__.py' into the shortest suffix.
    This prevents agents from drifting into nested duplicates when they keep
    appending the same subpath.
    """
    rel_parts = list(abs_path.relative_to(root).parts)
    prefix_parts = abs_path.parts[: len(abs_path.parts) - len(rel_parts)]

    # Need at least X/Y/X/Y (4 segments) to consider it a duplicated prefix.
    # A single repeat like lib/lib (2 segments) is too risky to auto-dedupe.
    if len(rel_parts) < 4:
        return None

    parts = rel_parts
    changed = False
    while len(parts) >= 4:
        reduced = False
        for prefix_len in range(1, len(parts) // 2 + 1):
            prefix = parts[:prefix_len]
            if parts[prefix_len : 2 * prefix_len] == prefix:
                parts = parts[prefix_len:]
                changed = True
                reduced = True
                break
        if not reduced:
            break

    if not changed:
        return None

    dedup_rel = Path(*parts)
    if prefix_parts:
        dedup_abs = Path(*prefix_parts) / dedup_rel
    else:
        dedup_abs = root / dedup_rel

    return dedup_abs.resolve(strict=False)


def maybe_fix_tool_paths(args: dict) -> dict:
    """
    Best-effort fix for common path drift (e.g., duplicated prefixes like src/module/src/module).
    Returns a new args dict with normalized paths; non-path entries unchanged.
    """
    if not isinstance(args, dict):
        return args

    keys = {"path", "file", "file_path", "directory", "dir"}
    list_keys = {"paths", "files"}

    def _fix_one(val: str) -> str:
        try:
            ws = get_workspace()
            norm = normalize_path(val)
            p = Path(norm.replace("/", os.sep))
            if not p.is_absolute():
                p = ws.root / p
            dedup = _dedupe_redundant_prefix_path(p, ws.root)
            target = dedup or p
            try:
                rel = target.relative_to(ws.root).as_posix()
                return rel
            except Exception:
                return str(target).replace("\\", "/")
        except Exception:
            return val

    fixed = dict(args)
    for k, v in list(args.items()):
        if k in keys and isinstance(v, str):
            fixed[k] = _fix_one(v)
        if k in list_keys and isinstance(v, list):
            fixed[k] = [_fix_one(x) if isinstance(x, str) else x for x in v]
    return fixed


# ---------------------------------------------------------------------------
# Module-level singleton and accessors
# ---------------------------------------------------------------------------

_WORKSPACE: Optional[Workspace] = None


def get_workspace() -> Workspace:
    """Get the current workspace singleton.

    If no workspace has been initialized, creates a default workspace
    using the current working directory.

    Returns:
        The current Workspace instance.
    """
    global _WORKSPACE
    if _WORKSPACE is None:
        allow_external = os.getenv("REV_ALLOW_EXTERNAL_PATHS", "").lower() == "true"
        _WORKSPACE = Workspace(
            root=Path.cwd(),
            allow_external_paths=allow_external,
        )
    return _WORKSPACE


def set_workspace(workspace: Workspace) -> None:
    """Set the workspace singleton.

    Use this for testing or to override the default workspace.

    Args:
        workspace: The Workspace instance to use.
    """
    global _WORKSPACE
    _WORKSPACE = workspace


def init_workspace(
    root: Optional[Path] = None,
    allow_external: bool = False,
) -> Workspace:
    """Initialize the workspace singleton with the given settings.

    This should be called early in CLI startup, before caches/tools initialize.

    Args:
        root: Workspace root directory. Defaults to current working directory.
        allow_external: Whether to allow external absolute paths.

    Returns:
        The initialized Workspace instance.
    """
    global _WORKSPACE
    _WORKSPACE = Workspace(
        root=root or Path.cwd(),
        allow_external_paths=allow_external,
    )
    return _WORKSPACE


def reset_workspace() -> None:
    """Reset the workspace singleton to None.

    Primarily for testing purposes.
    """
    global _WORKSPACE
    _WORKSPACE = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _clean_path_input(path: Union[str, Path]) -> str:
    """Clean incoming path input by stripping quotes, whitespace, and trailing slashes.

    Args:
        path: Raw path string or Path object.

    Returns:
        Cleaned path string.

    Raises:
        WorkspacePathError: If the path is empty after cleaning.
    """
    raw = str(path).strip()
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        raw = raw[1:-1].strip()
    
    # Remove trailing slashes to avoid issues on Windows directory resolution
    if len(raw) > 1:
        raw = raw.rstrip("/\\")
        
    if not raw:
        raise WorkspacePathError("Empty path")
    return raw


def _is_within_root(candidate: Path, root: Path) -> bool:
    """Check if candidate path is within root (case-insensitive on Windows).

    Args:
        candidate: Path to check.
        root: Root directory to check against.

    Returns:
        True if candidate is within root, False otherwise.
    """
    try:
        candidate.relative_to(root)
        return True
    except Exception:
        # Windows: use normcase string prefix as fallback for drive/case semantics.
        cand = os.path.normcase(str(candidate))
        base = os.path.normcase(str(root))
        if cand == base:
            return True
        return cand.startswith(base + os.sep)


# ---------------------------------------------------------------------------
# Public path normalization functions
# ---------------------------------------------------------------------------


def normalize_path(path: Union[str, Path]) -> str:
    """Normalize a path string for consistent handling across tools and verifier.

    This function provides a single source of truth for path normalization:
    - Converts backslashes to forward slashes
    - Resolves . and .. components
    - Strips leading/trailing whitespace
    - Removes redundant separators

    This DOES NOT validate the path against the workspace - use resolve_workspace_path
    for that. This is purely for normalization.

    Args:
        path: Path string or Path object to normalize.

    Returns:
        Normalized path string with forward slashes.
    """
    if not path:
        return ""

    raw = str(path).strip()
    if not raw:
        return ""

    # Strip quotes if present
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        raw = raw[1:-1].strip()

    # Convert to Path for normalization, then back to string with forward slashes
    # Using PurePosixPath normalization rules via as_posix()
    try:
        # Convert backslashes to forward slashes first
        raw = raw.replace("\\", "/")

        # Handle Windows drive letters (e.g., C:/)
        # Check if this looks like an absolute Windows path
        is_windows_absolute = len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()

        if is_windows_absolute:
            # Preserve the drive letter and normalize the rest
            drive = raw[:2]
            rest = raw[2:].lstrip("/")
            # Normalize path components
            parts = [p for p in rest.split("/") if p and p != "."]
            # Resolve .. by walking the parts
            resolved = []
            for part in parts:
                if part == "..":
                    if resolved:
                        resolved.pop()
                else:
                    resolved.append(part)
            return drive + "/" + "/".join(resolved) if resolved else drive + "/"
        else:
            # Unix-style path or relative path
            # Normalize path components
            parts = raw.split("/")
            is_absolute = raw.startswith("/")

            # Handle . and .. and empty parts
            resolved = []
            for part in parts:
                if part == "" or part == ".":
                    continue
                elif part == "..":
                    if resolved and resolved[-1] != "..":
                        resolved.pop()
                    elif not is_absolute:
                        resolved.append(part)
                else:
                    resolved.append(part)

            result = "/".join(resolved)
            if is_absolute:
                result = "/" + result
            return result if result else "."
    except Exception:
        # Fallback: just replace backslashes
        return raw.replace("\\", "/")


def normalize_to_workspace_relative(
    path: Union[str, Path],
    workspace_root: Optional[Path] = None,
) -> str:
    """Normalize a path and make it relative to the workspace root.

    This function:
    1. Normalizes the path (converts \\ to /, resolves ..)
    2. If the path is absolute and within workspace, makes it relative
    3. Returns a consistent forward-slash relative path

    Args:
        path: Path to normalize and make relative.
        workspace_root: Workspace root to make path relative to.
                       If None, uses the current workspace root.

    Returns:
        Normalized path relative to workspace, or the original normalized path
        if it cannot be made relative.
    """
    if not path:
        return ""

    raw = str(path).strip()
    if not raw:
        return ""

    # Get workspace root
    if workspace_root is None:
        workspace_root = get_workspace().root

    # Normalize the path first
    normalized = normalize_path(raw)
    if not normalized:
        return ""

    # Convert to Path for relative calculation
    try:
        p = Path(normalized.replace("/", os.sep))

        # If not absolute, resolve relative to workspace
        if not p.is_absolute():
            p = (workspace_root / p).resolve()
        else:
            p = p.resolve()

        # Try to make it relative to workspace
        try:
            rel = p.relative_to(workspace_root)
            return str(rel).replace("\\", "/")
        except ValueError:
            # Not within workspace, return normalized absolute path
            return str(p).replace("\\", "/")
    except Exception:
        return normalized


def is_path_within_workspace(
    path: Union[str, Path],
    workspace_root: Optional[Path] = None,
) -> bool:
    """Check if a path is within the workspace (without raising exceptions).

    This is a safe check that normalizes the path and validates it against
    the workspace root.

    Args:
        path: Path to check.
        workspace_root: Workspace root to check against.
                       If None, uses the current workspace root.

    Returns:
        True if the path is within the workspace, False otherwise.
    """
    if not path:
        return False

    raw = str(path).strip()
    if not raw:
        return False

    if workspace_root is None:
        workspace_root = get_workspace().root

    try:
        # Normalize and resolve
        normalized = normalize_path(raw)
        p = Path(normalized.replace("/", os.sep))

        if not p.is_absolute():
            p = (workspace_root / p).resolve()
        else:
            p = p.resolve()

        return _is_within_root(p, workspace_root.resolve())
    except Exception:
        return False
