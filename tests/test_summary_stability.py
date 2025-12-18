#!/usr/bin/env python3

import json
from rev.execution.session import SessionTracker


def test_running_summary_contains_sections_and_open_threads() -> None:
    tracker = SessionTracker(session_id="sum_test")
    tracker.track_task_started("Do thing A")
    tracker.track_task_failed("Do thing A", "boom")
    tracker.track_task_started("Do thing B")
    tracker.track_task_completed("Do thing B")
    tracker.track_tool_call("write_file", {"path": "a.py"})
    tracker.track_tool_call("replace_in_file", {"path": "b.py"})
    tracker.track_test_results(json.dumps({"rc": 1, "stdout": "fail", "stderr": ""}))

    # Simulate evidence added.
    tracker.track_evidence({"tool": "run_tests", "artifact_ref": ".rev/artifacts/tool_outputs/x.json"})

    summary = tracker.get_summary(detailed=False)
    assert "Running:" in summary
    assert "What changed:" in summary or "modified:" in summary or "created:" in summary
    assert "Open Threads" in summary
    assert "Fix failing tests" in summary

