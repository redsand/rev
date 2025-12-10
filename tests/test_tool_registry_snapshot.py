import json
from pathlib import Path

import pytest

from rev.tools import registry


def test_tool_registry_snapshot_preserved():
    """Ensure existing tools remain available after changes."""
    snapshot_path = Path(registry.__file__).with_name("_tool_registry_snapshot.json")
    snapshot = set(json.loads(snapshot_path.read_text())['tool_names'])

    tools = registry.get_available_tools()
    available = {tool.get('function', {}).get('name') for tool in tools}

    assert snapshot.issubset(available)


def test_registry_guard_blocks_missing_tool(monkeypatch):
    """Guard should raise when a previously registered tool is missing."""
    monkeypatch.setattr(registry, "_load_registry_snapshot", lambda: {"nonexistent_tool"})

    with pytest.raises(RuntimeError):
        registry.get_available_tools()
