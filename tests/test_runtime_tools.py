import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rev.tools.runtime_analysis as rt


@pytest.fixture(autouse=True)
def _patch_paths(tmp_path, monkeypatch):
    def fake_safe_path(p):
        pp = Path(p)
        return pp if pp.is_absolute() else tmp_path / pp

    monkeypatch.setattr(rt, "_safe_path", fake_safe_path)
    monkeypatch.setattr(rt, "ROOT", tmp_path)
    return tmp_path


def test_analyze_runtime_logs(tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        "2025-12-09T00:00:01 WARNING something odd\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "ValueError: boom\n",
        encoding="utf-8",
    )
    result = json.loads(rt.analyze_runtime_logs([str(log)], None))
    kinds = {issue["kind"] for issue in result["issues"]}
    assert "warning" in kinds
    assert "traceback" in kinds


def test_analyze_error_traces(tmp_path):
    log = tmp_path / "errors.log"
    log.write_text(
        "Traceback (most recent call last):\n"
        '  File "a.py", line 1, in <module>\n'
        "ZeroDivisionError: div\n",
        encoding="utf-8",
    )
    result = json.loads(rt.analyze_error_traces([str(log)], max_traces=5))
    assert result["clusters"][0]["count"] == 1
    assert "a.py" in result["clusters"][0]["suspected_files"][0]


def test_analyze_performance_regression(monkeypatch, tmp_path):
    stdout = "test_func  10.0 ms\n"

    def fake_run(cmd, timeout=1200):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(rt, "_run_shell", fake_run)
    baseline = {"test_func": 0.005}  # 5ms baseline
    baseline_file = tmp_path / "perf-baseline.json"
    baseline_file.write_text(json.dumps(baseline), encoding="utf-8")

    result = json.loads(rt.analyze_performance_regression("dummy", str(baseline_file), tolerance_pct=50.0))
    assert result["regressions"][0]["name"] == "test_func"
