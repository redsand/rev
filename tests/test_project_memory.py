#!/usr/bin/env python3

from pathlib import Path
import shutil
import uuid

from rev import config
from rev.memory.project_memory import (
    ensure_project_memory_file,
    record_recent_changes,
    record_failure_mode,
)
from rev.retrieval.context_builder import ContextBuilder
from rev.tools.registry import get_available_tools


def test_project_memory_file_created_and_updated() -> None:
    # Windows sandbox environments may deny access to system temp dirs;
    # use a workspace-local temp directory.
    tmp_dir = config.ROOT / f"tmp_memory_test_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    mem_file = tmp_dir / "project_summary.md"
    ensure_project_memory_file(mem_file)
    assert mem_file.exists()

    record_recent_changes(
        files_created=["a.py"],
        files_modified=["b.py"],
        files_deleted=[],
        path=mem_file,
        stamp="2025-01-01 00:00Z",
    )
    txt = mem_file.read_text(encoding="utf-8", errors="replace")
    assert "Recently Changed Files" in txt
    assert "created: a.py" in txt
    assert "modified: b.py" in txt

    record_failure_mode(
        title="X failure",
        symptom="bad thing",
        fix="do good thing",
        evidence_ref=".rev/artifacts/tool_outputs/x.json",
        path=mem_file,
    )
    txt2 = mem_file.read_text(encoding="utf-8", errors="replace")
    assert "Known Failure Modes" in txt2
    assert "X failure" in txt2
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_memory_retrieval_selects_relevant_snippet() -> None:
    # Ensure memory exists in default location for the retriever.
    ensure_project_memory_file()
    record_failure_mode(
        title="Workspace path outside allowed roots",
        symptom="outside workspace",
        fix="use /add-dir",
        evidence_ref=None,
        path=config.PROJECT_MEMORY_FILE,
    )

    builder = ContextBuilder(Path.cwd())
    tools = get_available_tools()
    bundle = builder.build(
        query="tool failed because path was outside allowed workspace roots; how to fix",
        tool_universe=tools,
        tool_candidates=[t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
        top_k_memory=3,
        top_k_tools=3,
        top_k_code=1,
        top_k_docs=1,
    )
    assert any("Workspace path outside allowed roots" in c.content for c in bundle.selected_memory_items)
