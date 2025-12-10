import pathlib
import sys
import json

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rev.execution import validator
from rev.execution.validator import ValidationStatus


def test_run_test_suite_uses_cmd_and_parses_output(monkeypatch):
    recorded = {}

    def fake_execute_tool(name, args):
        recorded["name"] = name
        recorded["args"] = args
        return json.dumps({
            "cmd": args["cmd"],
            "rc": 0,
            "stdout": "3 passed in 0.01s",
            "stderr": ""
        })

    monkeypatch.setattr(validator, "execute_tool", fake_execute_tool)

    result = validator._run_test_suite()

    assert recorded["name"] == "run_tests"
    assert recorded["args"]["cmd"].startswith("pytest -q tests/")
    assert result.status == ValidationStatus.PASSED
    assert "3" in result.message


def test_check_syntax_uses_cmd(monkeypatch):
    recorded = {}

    def fake_execute_tool(name, args):
        recorded["name"] = name
        recorded["args"] = args
        return json.dumps({"cmd": args["cmd"], "stdout": "", "stderr": ""})

    monkeypatch.setattr(validator, "execute_tool", fake_execute_tool)

    result = validator._check_syntax()

    assert recorded["name"] == "run_cmd"
    assert "py_compile" in recorded["args"]["cmd"]
    assert result.status == ValidationStatus.PASSED


def test_run_linter_uses_cmd(monkeypatch):
    recorded = {}

    def fake_execute_tool(name, args):
        recorded["name"] = name
        recorded["args"] = args
        return json.dumps({"cmd": args["cmd"], "stdout": "[]", "stderr": ""})

    monkeypatch.setattr(validator, "execute_tool", fake_execute_tool)

    result = validator._run_linter()

    assert recorded["name"] == "run_cmd"
    assert "ruff check ." in recorded["args"]["cmd"]
    assert result.status == ValidationStatus.PASSED


def test_attempt_auto_fix_reruns_last_failed_tests(monkeypatch):
    calls = []

    # First two attempts fail, third succeeds
    rc_sequence = [1, 1, 0]

    def fake_execute_tool(name, args):
        calls.append((name, args))
        rc = rc_sequence[len(calls) - 1]
        return json.dumps({"rc": rc, "stdout": "", "stderr": ""})

    monkeypatch.setattr(validator, "execute_tool", fake_execute_tool)

    failed_result = validator.ValidationResult(
        name="test_suite",
        status=validator.ValidationStatus.FAILED,
        message="Tests failed",
        details={"failures": ["tests/test_sample.py::test_one"]},
    )

    assert validator._attempt_auto_fix(failed_result) is True
    assert calls[0][1]["cmd"].startswith("pytest -q tests/test_sample.py")
    assert "--lf" in calls[1][1]["cmd"]
    assert calls[2][1]["cmd"].startswith("pytest -q tests/")
