from pathlib import Path
import uuid

from rev.agents import context_provider
from rev.core.context import RevContext
from rev.models.task import Task
from rev.tools.registry import get_available_tools


def test_minimal_context_includes_target_and_config(monkeypatch) -> None:
    root = Path("tmp_test") / "context_minimal" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    src_dir = root / "src"
    src_dir.mkdir()
    target = src_dir / "app.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    config = root / "pyproject.toml"
    config.write_text("[tool]\nname = 'demo'\n", encoding="utf-8")

    other = root / "other.py"
    other.write_text("pass\n", encoding="utf-8")

    monkeypatch.chdir(root)
    context_provider._BUILDER = None

    task = Task(description="Edit src/app.py to add logic", action_type="edit")
    context = RevContext(user_request="update app")

    tools = get_available_tools()
    candidate = [t.get("function", {}).get("name") for t in tools if isinstance(t, dict)]
    rendered, schemas, bundle = context_provider.build_context_and_tools(
        task,
        context,
        tool_universe=tools,
        candidate_tool_names=candidate,
        max_tools=4,
    )

    locations = [chunk.location for chunk in bundle.selected_code_chunks]
    assert any(loc.startswith("src/app.py") for loc in locations)
    assert any("pyproject.toml" in loc for loc in locations)
    assert not any("other.py" in loc for loc in locations)
    assert "Selected code" in rendered
