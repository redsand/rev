import json
from pathlib import Path

from rev.execution import quick_verify


def test_unittest_fallback_converts_module_paths(monkeypatch):
    calls = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({
                "rc": 1,
                "stdout": "Ran 0 tests in 0.000s",
                "stderr": ""
            })
        return json.dumps({"rc": 0, "stdout": "ok", "stderr": ""})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_ensure_tool_available", lambda cmd: True)

    result = quick_verify._run_validation_command(
        ["python", "-m", "unittest", "tests/test_widget.py"],
        use_tests_tool=True,
        timeout=10,
        cwd=Path("tmp_test"),
    )

    assert result.get("rc") == 0
    assert len(calls) == 2
    second_cmd = calls[1]["cmd"]
    assert isinstance(second_cmd, list)
    assert "tests.test_widget" in second_cmd
    assert "tests/test_widget.py" not in second_cmd
