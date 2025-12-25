import json
import os
import shutil
import time
import uuid
from pathlib import Path

import pytest

from rev import config
from rev.execution import quick_verify


@pytest.fixture
def temp_workspace():
    root = Path("tmp_test").resolve() / f"install_guard_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    old_root = config.ROOT
    config.set_workspace_root(root)
    try:
        yield root
    finally:
        config.set_workspace_root(old_root)
        shutil.rmtree(root, ignore_errors=True)


def test_auto_install_guard_skips_repeated_attempts(temp_workspace, monkeypatch):
    (temp_workspace / "requirements.txt").write_text("pytest==7.0.0")
    calls: list[dict] = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        return json.dumps({"rc": 1})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_INSTALL_GUARD_STATE", {})

    assert quick_verify._try_auto_install("pytest") is False
    assert quick_verify._try_auto_install("pytest") is False
    assert len(calls) == 1


def test_auto_install_guard_allows_on_dependency_change(temp_workspace, monkeypatch):
    req_path = temp_workspace / "requirements.txt"
    req_path.write_text("pytest==7.0.0")
    calls: list[dict] = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        return json.dumps({"rc": 1})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_INSTALL_GUARD_STATE", {})

    assert quick_verify._try_auto_install("pytest") is False

    req_path.write_text("pytest==7.1.0")
    now = time.time() + 5
    os.utime(req_path, (now, now))

    assert quick_verify._try_auto_install("pytest") is False
    assert len(calls) == 2


def test_npm_repair_guard_skips_repeated_install(temp_workspace, monkeypatch):
    package_json = temp_workspace / "package.json"
    package_json.write_text(json.dumps({"devDependencies": {"eslint": "^9.0.0"}}))
    calls: list[dict] = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        return json.dumps({"rc": 0})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_INSTALL_GUARD_STATE", {})

    assert quick_verify._try_npm_repair("eslint") is False
    assert quick_verify._try_npm_repair("eslint") is False
    assert len(calls) == 1
