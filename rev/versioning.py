#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Version helpers for rev."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

from rev._version import REV_VERSION


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


def build_version_output(model: str, system_info: Dict[str, str]) -> str:
    """Format detailed version information for display."""

    version = get_version()

    output = ["\nRev - Autonomous AI Development System"]
    output.append("=" * 60)
    output.append(f"  Version:          {version}")
    output.append("  Architecture:     Multi-Agent Orchestration")
    output.append(f"  Model:            {model}")
    output.append("\nSystem:")
    output.append(f"  OS:               {system_info['os']} {system_info['os_release']}")
    output.append(f"  Architecture:     {system_info['architecture']}")
    output.append(f"  Python:           {system_info['python_version']}")

    return "\n".join(output)

