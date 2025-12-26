from pathlib import Path
import uuid

from rev.retrieval.context_builder import ContextBuilder
from rev.tools.registry import get_available_tools


def _sources(bundle) -> set[str]:
    return {str(chunk.source).lower() for chunk in bundle.selected_docs_chunks}


def _make_root() -> Path:
    root = Path("tmp_test") / "instruction_context" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_instruction_files_included_in_build() -> None:
    root = _make_root()
    (root / "AGENTS.md").write_text("Agent instructions", encoding="utf-8")
    (root / "gemini.md").write_text("Gemini instructions", encoding="utf-8")

    builder = ContextBuilder(root)
    tools = get_available_tools()
    bundle = builder.build(
        query="unrelated query",
        tool_universe=tools,
        tool_candidates=[t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
        top_k_tools=1,
        top_k_code=0,
        top_k_docs=1,
        top_k_memory=0,
    )

    sources = _sources(bundle)
    assert any(src.endswith("agents.md") for src in sources)
    assert any(src.endswith("gemini.md") for src in sources)


def test_instruction_files_included_in_build_minimal() -> None:
    root = _make_root()
    (root / "claude.md").write_text("Claude instructions", encoding="utf-8")

    builder = ContextBuilder(root)
    tools = get_available_tools()
    bundle = builder.build_minimal(
        query="irrelevant",
        tool_universe=tools,
        tool_candidates=[t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
        target_paths=[],
        config_paths=[],
        top_k_tools=1,
        top_k_memory=0,
    )

    sources = _sources(bundle)
    assert any(src.endswith("claude.md") for src in sources)
