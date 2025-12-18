#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical workspace path resolution for tools and verifiers.

All filesystem tools and verification steps should resolve paths through this
module to ensure consistent behavior and prevent "apply succeeded / verify
failed" split-brain path handling.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Union

from rev.config import ROOT, get_allowed_roots


class WorkspacePathError(ValueError):
    """Raised when a path is invalid or outside allowed roots."""


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    """A validated workspace path."""

    abs_path: Path
    rel_path: str
    allowed_root: Path


def _clean_path_input(path: Union[str, Path]) -> str:
    raw = str(path).strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()
    if not raw:
        raise WorkspacePathError("Empty path")
    return raw


def _is_within_root(candidate: Path, root: Path) -> bool:
    """Return True if candidate is within root (case-insensitive on Windows)."""

    try:
        candidate_rel = candidate.relative_to(root)
        _ = candidate_rel  # appease linters
        return True
    except Exception:
        # Windows: use normcase string prefix as a fallback for drive/case semantics.
        cand = os.path.normcase(str(candidate))
        base = os.path.normcase(str(root))
        if cand == base:
            return True
        return cand.startswith(base + os.sep)


def resolve_workspace_path(
    path: Union[str, Path],
    *,
    purpose: str = "access",
) -> ResolvedWorkspacePath:
    """Resolve a path to an allowed absolute path within the workspace/allowlist.

    Args:
        path: Incoming path (relative or absolute).
        purpose: Optional short label to improve error messages (e.g., "edit", "read").

    Returns:
        ResolvedWorkspacePath containing absolute path, a log-friendly rel_path,
        and the allowed root that contains it.

    Raises:
        WorkspacePathError: if the path is outside allowed roots.
    """

    raw = _clean_path_input(path)
    # Guard against a common LLM/pathing mistake: prefixing a workspace-relative path
    # with the workspace folder name (e.g., running inside `C:\repo\redtrade` but
    # emitting `redtrade/lib/...`). That creates nested paths like `<ROOT>/redtrade/lib`.
    #
    # If the incoming path is relative and starts with "<ROOT.name>/", strip that prefix.
    try:
        raw_norm = raw.replace("\\", "/")
        if not Path(raw).is_absolute():
            root_name = ROOT.name
            if raw_norm.lower() == root_name.lower():
                raw = "."
            elif raw_norm.lower().startswith(root_name.lower() + "/"):
                raw = raw_norm[len(root_name) + 1 :]
    except Exception:
        pass
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate

    # strict=False: allow resolving paths that don't exist yet (create/write flows).
    abs_path = candidate.resolve(strict=False)

    allowed_roots = [r.resolve() for r in get_allowed_roots()]
    for allowed_root in allowed_roots:
        if _is_within_root(abs_path, allowed_root):
            try:
                rel = abs_path.relative_to(ROOT).as_posix()
            except Exception:
                # For additional roots, keep a relative view from ROOT for log consistency.
                rel = os.path.relpath(abs_path, ROOT).replace("\\", "/")
            return ResolvedWorkspacePath(abs_path=abs_path, rel_path=rel, allowed_root=allowed_root)

    allowed_list = ", ".join(str(r) for r in allowed_roots)
    raise WorkspacePathError(
        f"Path is outside allowed workspace roots for {purpose}: '{raw}'. "
        f"Allowed roots: {allowed_list}. "
        "Run rev from the target repo root, or re-run with '--workspace <repo_root>', or add an allowed root via '/add-dir <path>'."
    )
