import json
from pathlib import Path
import uuid

from rev.execution import quick_verify


def test_run_validation_command_discovers_tests_on_no_tests(monkeypatch) -> None:
    root = Path("tmp_test") / "no_tests_fallback" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    test_dir = root / "tests"
    test_dir.mkdir()
    test_file = test_dir / "sample.test.js"
    test_file.write_text("test('x', () => {})\n", encoding="utf-8")

    calls = []

    def fake_execute_tool(tool, args, agent_name=None):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({"rc": 1, "stdout": "No tests found, exiting with code 1", "stderr": ""})
        return json.dumps({"rc": 0, "stdout": "ok", "stderr": ""})

    monkeypatch.setattr(quick_verify, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(quick_verify, "_ensure_tool_available", lambda cmd: True)

    result = quick_verify._run_validation_command(
        ["jest"],
        use_tests_tool=True,
        timeout=10,
        cwd=root,
    )

    assert result.get("rc") == 0
    assert len(calls) == 2
    second_cmd = calls[1]["cmd"]
    assert isinstance(second_cmd, list)
    assert "--runTestsByPath" in second_cmd
    normalized = [str(part).replace("\\", "/") for part in second_cmd]
    assert "tests/sample.test.js" in normalized
