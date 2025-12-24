import json
from pathlib import Path

from rev.execution import quick_verify


def test_run_validation_command_retries_jest_no_tests(monkeypatch):
    calls = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({
                "rc": 1,
                "stdout": "No tests found, exiting with code 1",
                "stderr": ""
            })
        return json.dumps({"rc": 0, "stdout": "ok", "stderr": ""})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_ensure_tool_available", lambda cmd: True)

    result = quick_verify._run_validation_command(
        ["jest", "tests/app.test.ts"],
        use_tests_tool=True,
        timeout=10,
        cwd=Path("tmp_test"),
    )

    assert result.get("rc") == 0
    assert len(calls) == 2
    second_cmd = calls[1]["cmd"]
    assert isinstance(second_cmd, list)
    assert "--runTestsByPath" in second_cmd
    assert "tests/app.test.ts" in second_cmd
