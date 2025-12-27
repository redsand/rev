from pathlib import Path
import uuid

from rev.retrieval.context_builder import ContextBuilder
from rev.tools.registry import get_available_tools


def test_context_builder_includes_non_python_code() -> None:
    root = Path("tmp_test") / "context_builder" / uuid.uuid4().hex
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "app.js").write_text("function hello() { return 'hello'; }\n", encoding="utf-8")

    builder = ContextBuilder(root)
    tools = get_available_tools()
    bundle = builder.build(
        query="hello",
        tool_universe=tools,
        tool_candidates=[t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
        top_k_code=2,
        top_k_docs=0,
        top_k_tools=1,
        top_k_memory=0,
    )

    sources = {chunk.source for chunk in bundle.selected_code_chunks}
    assert "src/app.js" in sources
