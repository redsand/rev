"""Regression tests for tool registry imports.

These tests ensure importing the tool registry does not trigger the
previous circular import error with the planner module.
"""

from __future__ import annotations

import subprocess
import sys


def test_registry_and_planner_importable() -> None:
    """Ensure registry and planner modules import cleanly in isolation."""
    script = (
        "from rev.tools.registry import get_available_tools; "
        "from rev.execution.planner import PLANNING_SYSTEM; "
        "print(len(get_available_tools()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip().isdigit()
