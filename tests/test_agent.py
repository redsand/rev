import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

import rev as agent


def test_safe_path_blocks_escape():
    """Test that _safe_path prevents directory traversal."""
    with pytest.raises(ValueError):
        agent._safe_path("../../..")


@pytest.mark.broken
def test_write_file_guard_stops_noninteractive():
    """BROKEN: non_interactive parameter no longer exists in current API."""
    pytest.skip("non_interactive parameter removed from API")


def test_read_file_roundtrip(tmp_path):
    d = agent.ROOT / "tests_tmp_" / f"rt_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        f = d / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        content = agent.read_file(str(f.relative_to(agent.ROOT)))
        assert content.startswith("hello world")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_run_cmd_blocks_disallowed():
    """Test that disallowed commands are blocked."""
    res = json.loads(agent.run_cmd("ls -la", timeout=5))
    assert "blocked" in res


def test_run_cmd_allows_python_version():
    """Test that allowed commands like python work."""
    res = json.loads(agent.run_cmd("python --version", timeout=20))
    assert res.get("rc") == 0
    # python --version may print to stderr depending on platform
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    assert "Python" in out


@pytest.mark.broken
def test_search_code_and_replace(tmp_path):
    """BROKEN: search_replace function no longer exists in current API."""
    pytest.skip("search_replace removed from API - use replace_in_file instead")


@pytest.mark.broken
def test_bw_get_locked(monkeypatch):
    """BROKEN: bw_get function no longer exists in current API."""
    pytest.skip("bw_get removed from API")


def test_get_repo_context():
    res = json.loads(agent.get_repo_context())
    assert set(["status", "log", "top_level"]).issubset(res.keys())


@pytest.mark.broken
def test_http_request_mock(monkeypatch):
    """BROKEN: http_request function no longer exists in current API."""
    pytest.skip("http_request removed from API - use web_fetch instead")


@pytest.mark.broken
def test_secret_redaction():
    """BROKEN: _register_secret and _redact_text functions no longer exist."""
    pytest.skip("Secret redaction functions removed from API")


def test_run_tests_blocked_command():
    res = json.loads(agent.run_tests("echo hi"))
    assert res.get("blocked") == "echo"


@pytest.mark.broken
def test_format_code_guard_stops_noninteractive():
    """BROKEN: format_code function no longer exists in current API."""
    pytest.skip("format_code removed from API")
