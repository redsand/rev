import json
from pathlib import Path

from rev.execution import quick_verify


def test_go_test_fallback_uses_package_dir(monkeypatch):
    calls = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({
                "rc": 1,
                "stdout": "no test files",
                "stderr": ""
            })
        return json.dumps({"rc": 0, "stdout": "ok", "stderr": ""})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_ensure_tool_available", lambda cmd: True)

    result = quick_verify._run_validation_command(
        ["go", "test", "pkg/foo_test.go"],
        use_tests_tool=True,
        timeout=10,
        cwd=Path("tmp_test"),
    )

    assert result.get("rc") == 0
    assert len(calls) == 2
    second_cmd = calls[1]["cmd"]
    assert isinstance(second_cmd, list)
    assert "pkg/foo_test.go" not in second_cmd
    assert "./pkg" in second_cmd
