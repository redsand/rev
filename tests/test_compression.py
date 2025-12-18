#!/usr/bin/env python3

import json
from pathlib import Path

from rev.execution.executor import _tool_message_content
from rev.execution.session import SessionTracker
from rev import config
from rev.execution.redaction import REDACTION_RULES_VERSION


def test_tool_output_compression_writes_artifact_and_inlines_evidence() -> None:
    tracker = SessionTracker(session_id="test_session")
    big = "x" * 10000
    result = json.dumps({"rc": 5, "stdout": big, "stderr": ""})

    content = _tool_message_content(
        "run_tests",
        {"cmd": "pytest -q"},
        result,
        tracker,
        task_id="task123",
    )

    evidence = json.loads(content)
    assert evidence["tool"] == "run_tests"
    assert evidence["result"] in {"success", "error"}
    assert "artifact_ref" in evidence
    assert "artifact_meta" in evidence
    assert evidence["artifact_meta"]["schema_version"].startswith("tool_output@")
    assert evidence["artifact_meta"]["redaction_rules_version"] == REDACTION_RULES_VERSION
    artifact_path = Path(config.ROOT) / evidence["artifact_ref"]
    assert artifact_path.exists()
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8", errors="replace"))
    assert artifact_payload["schema_version"] == evidence["artifact_meta"]["schema_version"]
    assert artifact_payload["redaction_rules_version"] == REDACTION_RULES_VERSION


def test_read_file_is_not_compressed_inline() -> None:
    tracker = SessionTracker(session_id="test_session2")
    output = "print('hello')\n"
    content = _tool_message_content("read_file", {"path": "foo.py"}, output, tracker, task_id="t")
    assert content == output


def test_redaction_scrubs_tokens_in_artifacts() -> None:
    tracker = SessionTracker(session_id="test_session3")
    leaked = "Authorization: Bearer sk-THISISNOTREALBUTSHOULDREDACT\n"
    result = json.dumps({"rc": 1, "stdout": leaked, "stderr": ""})
    content = _tool_message_content("run_tests", {"cmd": "pytest -q"}, result, tracker, task_id="t3")
    evidence = json.loads(content)
    artifact_path = Path(config.ROOT) / evidence["artifact_ref"]
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8", errors="replace"))
    stored = json.dumps(artifact_payload, ensure_ascii=False)
    assert "sk-THISISNOTREAL" not in stored
    assert "Bearer [REDACTED]" in stored or "sk-[REDACTED]" in stored

