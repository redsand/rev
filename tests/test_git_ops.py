#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for git_ops run_cmd behavior."""

import json
import shutil
import uuid
from pathlib import Path

from rev.tools import git_ops


def _sandbox_root() -> Path:
    """Create a writable sandbox directory inside the repo for tests."""
    base = Path("build") / "test_git_ops"
    base.mkdir(parents=True, exist_ok=True)
    return base / str(uuid.uuid4())


def test_run_cmd_skips_existing_clone(monkeypatch):
    """git clone to an existing destination should be skipped."""
    sandbox = _sandbox_root()
    sandbox.mkdir(parents=True, exist_ok=True)
    dest = sandbox / "external_repo"
    dest.mkdir()

    # Point ROOT to sandbox for the duration of this test
    monkeypatch.setattr(git_ops, "ROOT", sandbox)

    result = json.loads(git_ops.run_cmd("git clone https://example.com/repo.git external_repo"))
    try:
        assert result.get("skipped") is True
        assert "destination already exists" in result.get("reason", "")
        assert result.get("rc") == 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_run_cmd_allows_clone_when_missing(monkeypatch):
    """git clone should proceed when destination does not exist."""
    sandbox = _sandbox_root()
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(git_ops, "ROOT", sandbox)

    result = json.loads(git_ops.run_cmd("git clone https://example.com/repo.git external_repo"))

    try:
        # If the command actually ran, rc will be non-zero; if blocked, 'skipped' will be absent.
        assert "skipped" not in result
        assert result.get("cmd") == "git clone https://example.com/repo.git external_repo"
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
