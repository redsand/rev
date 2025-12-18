#!/usr/bin/env python3

import json
from pathlib import Path

from rev.retrieval.context_builder import ContextBuilder
from rev.tools.registry import get_available_tools


def test_tool_retrieval_limits_and_examples() -> None:
    tools = get_available_tools()
    builder = ContextBuilder(Path.cwd())
    bundle = builder.build(
        query="create a new directory for analysts and then update imports in a python file",
        tool_universe=tools,
        tool_candidates=[t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
        top_k_tools=7,
        top_k_code=2,
        top_k_docs=2,
    )

    assert 1 <= len(bundle.selected_tool_schemas) <= 7
    names = [t.name for t in bundle.selected_tool_schemas]
    assert "create_directory" in names

    # Examples are valid JSON with tool_name and arguments.
    for tool in bundle.selected_tool_schemas:
        payload = json.loads(tool.example)
        assert payload.get("tool_name") == tool.name
        assert "arguments" in payload


def test_tool_candidate_filtering() -> None:
    tools = get_available_tools()
    builder = ContextBuilder(Path.cwd())
    bundle = builder.build(
        query="search for a symbol usage and show me occurrences",
        tool_universe=tools,
        tool_candidates=["search_code", "find_symbol_usages", "rag_search"],
        top_k_tools=3,
        top_k_code=1,
        top_k_docs=1,
    )
    names = [t.name for t in bundle.selected_tool_schemas]
    assert set(names).issubset({"search_code", "find_symbol_usages", "rag_search"})
    assert len(names) <= 3

