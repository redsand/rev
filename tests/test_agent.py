import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

import rev as agent


def test_safe_path_blocks_escape():
    with pytest.raises(ValueError):
        agent._safe_path("../../..")


def test_write_file_guard_stops_noninteractive():
    res = json.loads(agent.write_file("tests/tmp_guard.txt", "x", non_interactive=True))
    assert res.get("user_decision") == "stop"


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
    res = json.loads(agent.run_cmd("ls -la", timeout=5, non_interactive=True))
    assert "blocked" in res


def test_run_cmd_allows_python_version():
    res = json.loads(agent.run_cmd("python --version", timeout=20, non_interactive=True))
    assert res.get("rc") == 0
    # python --version may print to stderr depending on platform
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    assert "Python" in out


def test_search_code_and_replace(tmp_path):
    d = agent.ROOT / "tests_tmp_" / f"sr_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        f = d / "sample.txt"
        f.write_text("MAGIC_TOKEN foo foo", encoding="utf-8")
        # search
        sres = json.loads(agent.search_code("MAGIC_TOKEN", include=str(d.relative_to(agent.ROOT)) + "/**/*"))
        matches = sres.get("matches", [])
        assert any(m["file"].endswith("sample.txt") for m in matches)
        # replace (dry-run)
        rres = json.loads(agent.search_replace("foo", "bar", include=str(d.relative_to(agent.ROOT)) + "/**/*", dry_run=True))
        changed = rres.get("changed", [])
        assert any(c["file"].endswith("sample.txt") and c["replacements"] == 2 for c in changed)
        # Ensure file not modified in dry-run
        assert f.read_text(encoding="utf-8") == "MAGIC_TOKEN foo foo"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_bw_get_locked(monkeypatch):
    monkeypatch.delenv("BITWARDEN_SESSION", raising=False)
    monkeypatch.delenv("BW_SESSION", raising=False)
    monkeypatch.delenv("BW_SESSION_TOKEN", raising=False)
    res = json.loads(agent.bw_get("password", "dummy"))
    assert "error" in res


def test_get_repo_context():
    res = json.loads(agent.get_repo_context())
    assert set(["status", "log", "top_level"]).issubset(res.keys())


def test_http_request_mock(monkeypatch):
    class FakeResp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Content-Type": "text/plain"}
            self.text = "ok"
    
    def fake_request(method, url, headers=None, params=None, json=None, data=None, timeout=30, verify=True, auth=None):
        return FakeResp()

    # If requests is not installed, http_request will early-return with error
    if "requests" in getattr(agent, "_REQ_ERR", {}):
        pytest.skip("requests not installed in this environment")

    monkeypatch.setattr(agent, "requests", type("R", (), {"request": staticmethod(fake_request)}))
    res = json.loads(agent.http_request("GET", "https://example.com"))
    assert res.get("status") == 200
    assert res.get("body") == "ok"


def test_secret_redaction():
    secret = "s3cr3t-token-xyz"
    agent._register_secret(secret)
    redacted = agent._redact_text(f"prefix {secret} suffix")
    assert secret not in redacted
    assert "********" in redacted


def test_run_tests_blocked_command():
    res = json.loads(agent.run_tests("echo hi"))
    assert res.get("blocked") == "echo"


def test_format_code_guard_stops_noninteractive():
    res = json.loads(agent.format_code("ruff", non_interactive=True))
    assert res.get("user_decision") == "stop"
