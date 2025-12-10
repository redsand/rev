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


def test_registry_snapshot_auto_updates(monkeypatch, tmp_path):
    """Snapshot should auto-append new tools instead of requiring manual edits."""
    fake_snapshot = tmp_path / "_tool_registry_snapshot.json"
    fake_snapshot.write_text(json.dumps({"tool_names": ["read_file"]}))

    monkeypatch.setattr(registry, "_SNAPSHOT_PATH", fake_snapshot)

    tools = registry.get_available_tools()

    snapshot = set(json.loads(fake_snapshot.read_text())['tool_names'])
    current_tools = {tool.get('function', {}).get('name') for tool in tools}

    assert "read_file" in snapshot  # original baseline preserved
    assert current_tools.issubset(snapshot)  # snapshot expands to include new tools
