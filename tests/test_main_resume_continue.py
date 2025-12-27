"""CLI resume-continue behavior tests."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_resume_continue_uses_orchestrator_in_subagent(monkeypatch):
    import rev.main as main

    class DummyPlan:
        def __init__(self):
            self.tasks = []

        def get_summary(self):
            return "dummy plan"

    monkeypatch.setattr(main.ExecutionPlan, "load_checkpoint", lambda _path: DummyPlan())
    monkeypatch.setattr(main.config, "get_execution_mode", lambda: "sub-agent")
    monkeypatch.setattr(main.config, "SESSIONS_DIR", Path.cwd() / "_no_sessions")

    called = {}

    def fake_run_orchestrated(user_request, project_root, **kwargs):
        called["user_request"] = user_request
        called["resume"] = kwargs.get("resume")
        called["resume_plan"] = kwargs.get("resume_plan")
        return SimpleNamespace(success=True)

    def fail_legacy(*_args, **_kwargs):
        raise AssertionError("legacy execution path should not run")

    monkeypatch.setattr(main, "run_orchestrated", fake_run_orchestrated)
    monkeypatch.setattr(main, "execution_mode", fail_legacy)
    monkeypatch.setattr(main, "concurrent_execution_mode", fail_legacy)

    monkeypatch.setattr(
        sys,
        "argv",
        ["rev", "--resume", "dummy.chk", "--resume-continue"],
    )

    with pytest.raises(SystemExit):
        main.main()

    assert "user_request" in called
    assert called["resume"] is True
    assert called["resume_plan"] is True
