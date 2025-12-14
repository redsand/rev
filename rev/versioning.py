#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Version helpers for rev."""

from __future__ import annotations

import re
from pathlib import Path
import subprocess
from typing import Dict, Optional

from rev._version import REV_VERSION, REV_GIT_COMMIT


def _version_from_setup() -> Optional[str]:
    """Extract the package version from setup.py if available."""

    setup_path = Path(__file__).resolve().parent.parent / "setup.py"
    if not setup_path.exists():
        return None

    setup_text = setup_path.read_text(encoding="utf-8")
    match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", setup_text)
    if match:
        return match.group(1)
    return None


def get_version() -> str:
    """Return the package version using the single source of truth."""

    setup_version = _version_from_setup()
    if setup_version and setup_version != REV_VERSION:
        return setup_version

    if REV_VERSION:
        return REV_VERSION

    try:
        from importlib.metadata import version  # type: ignore

        return version("rev")
    except Exception:
        return "unknown"


def get_git_commit(short: bool = True) -> Optional[str]:
    """Return the git commit hash, preferring the build-time value if present."""
    if REV_GIT_COMMIT and REV_GIT_COMMIT != "unknown":
        return REV_GIT_COMMIT[:7] if short else REV_GIT_COMMIT

    try:
        repo_root = Path(__file__).resolve().parent.parent
        if short:
            cmd = ["git", "rev-parse", "--short", "HEAD"]
        else:
            cmd = ["git", "rev-parse", "HEAD"]
        commit = subprocess.check_output(cmd, cwd=repo_root, stderr=subprocess.DEVNULL)
        return commit.decode().strip()
    except Exception:
        return None


def build_version_output(model: str, system_info: Dict[str, str]) -> str:
    """Format detailed version information for display."""

    version = get_version()
    commit = get_git_commit(short=True)

    output = ["\nRev - Autonomous AI Development System"]
    output.append("=" * 60)
    if commit:
        output.append(f"  Version:          {version} (commit {commit})")
    else:
        output.append(f"  Version:          {version}")
    output.append("  Architecture:     Multi-Agent Orchestration")
    output.append(f"  Model:            {model}")
    output.append("\nSystem:")
    output.append(f"  OS:               {system_info['os']} {system_info['os_release']}")
    output.append(f"  Architecture:     {system_info['architecture']}")
    output.append(f"  Python:           {system_info['python_version']}")

    return "\n".join(output)
