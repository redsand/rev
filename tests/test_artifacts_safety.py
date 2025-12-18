#!/usr/bin/env python3

import json
import threading
from pathlib import Path

from rev.execution.artifacts import write_tool_output_artifact
from rev import config


def test_failure_path_artifact_written() -> None:
    ref, meta = write_tool_output_artifact(
        tool="run_cmd",
        args={"cmd": "echo hi"},
        output=json.dumps({"error": "boom", "rc": 1, "stdout": "", "stderr": ""}),
        session_id="s",
        task_id="t",
        step_id=1,
        agent_name="tester",
        truncated=False,
    )
    assert Path(config.ROOT, ref.as_posix()).exists()
    assert meta["schema_version"].startswith("tool_output@")


def test_atomic_write_no_tmp_left_behind() -> None:
    before = set(config.TOOL_OUTPUTS_DIR.glob("*.tmp")) if config.TOOL_OUTPUTS_DIR.exists() else set()
    ref, _meta = write_tool_output_artifact(
        tool="search_code",
        args={"pattern": "x"},
        output="some output",
        session_id="s2",
        task_id="t2",
        step_id=2,
        agent_name="tester",
    )
    after = set(config.TOOL_OUTPUTS_DIR.glob("*.tmp")) if config.TOOL_OUTPUTS_DIR.exists() else set()
    assert after == before
    assert Path(config.ROOT, ref.as_posix()).exists()


def test_concurrent_writes_do_not_collide() -> None:
    results: list[str] = []
    lock = threading.Lock()

    def _write(i: int) -> None:
        ref, _ = write_tool_output_artifact(
            tool="run_cmd",
            args={"cmd": f"echo {i}"},
            output=f"out {i}",
            session_id="s3",
            task_id="t3",
            step_id=i,
            agent_name="tester",
        )
        with lock:
            results.append(ref.as_posix())

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == len(set(results))

