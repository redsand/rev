"""MCP startup and shutdown behavior tests for rev CLI."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _stub_logger():
    return SimpleNamespace(
        log=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
        log_workflow_phase=lambda *args, **kwargs: None,
        close=lambda: None,
        log_file_path="",
    )


def _stub_run_log(monkeypatch):
    """Disable run log file writes during tests."""
    monkeypatch.setattr("rev.run_log.start_run_log", lambda: None)
    monkeypatch.setattr("rev.run_log.write_run_log_line", lambda *_args, **_kwargs: None)


def _stub_caches(monkeypatch):
    monkeypatch.setattr("rev.cache.initialize_caches", lambda *_args, **_kwargs: None)


@pytest.fixture(autouse=True)
def cleanup_sys_argv(monkeypatch):
    original = list(sys.argv)
    yield
    sys.argv[:] = original


def test_mcp_enabled_starts_and_stops(monkeypatch):
    import rev.main as main
    from rev.mcp.client import mcp_client

    _stub_run_log(monkeypatch)
    _stub_caches(monkeypatch)
    monkeypatch.setattr(main.DebugLogger, "initialize", lambda enabled=False: _stub_logger())

    # Track MCP lifecycle calls
    calls = {"start": None, "stop": None, "load_defaults": 0}

    def fake_start(root, enable=True, register=True):
        calls["start"] = {"root": root, "enable": enable, "register": register}
        return ["p1"]

    def fake_stop(procs):
        calls["stop"] = list(procs)

    def fake_load_defaults():
        calls["load_defaults"] += 1
        mcp_client.servers["default"] = {"command": "npx"}

    # Patch MCP hooks
    monkeypatch.setattr(main, "start_mcp_servers", fake_start)
    monkeypatch.setattr(main, "stop_mcp_servers", fake_stop)
    monkeypatch.setattr(mcp_client, "_load_default_servers", fake_load_defaults)
    monkeypatch.setattr(main, "run_orchestrated", lambda *args, **kwargs: SimpleNamespace(success=True))

    # Minimal task; run_orchestrated stub returns quickly
    sys.argv = ["rev", "--workspace", str(Path.cwd()), "noop-task"]
    with pytest.raises(SystemExit):
        main.main()

    assert calls["start"] is not None, "MCP startup should be invoked"
    assert calls["start"]["register"] is True
    assert calls["stop"] == ["p1"], "MCP processes should be cleaned up"
    assert calls["load_defaults"] == 1, "Default servers should be loaded into registry"
    assert "default" in mcp_client.servers


def test_mcp_disabled_skips_start(monkeypatch):
    import rev.main as main
    from rev.mcp.client import mcp_client

    _stub_run_log(monkeypatch)
    _stub_caches(monkeypatch)
    monkeypatch.setattr(main.DebugLogger, "initialize", lambda enabled=False: _stub_logger())

    calls = {"start": 0, "stop": 0}

    def fail_start(*_args, **_kwargs):
        calls["start"] += 1

    def fail_stop(*_args, **_kwargs):
        calls["stop"] += 1

    # Seed registry to ensure it remains untouched
    mcp_client.servers.clear()
    mcp_client.servers["existing"] = {"command": "keep"}

    monkeypatch.setattr(main, "start_mcp_servers", fail_start)
    monkeypatch.setattr(main, "stop_mcp_servers", fail_stop)
    monkeypatch.setattr(main, "run_orchestrated", lambda *args, **kwargs: SimpleNamespace(success=True))

    sys.argv = ["rev", "--workspace", str(Path.cwd()), "noop-task", "--no-mcp"]
    with pytest.raises(SystemExit):
        main.main()

    assert calls["start"] == 0, "MCP startup should be skipped when --no-mcp is set"
    assert calls["stop"] == 0, "No MCP processes to stop when disabled"
    assert "existing" in mcp_client.servers, "Registry should remain unchanged when MCP disabled"
