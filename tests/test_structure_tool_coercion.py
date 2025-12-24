from rev.agents import research


def test_coerce_structure_tool_to_tree_view():
    tool_name, args, coerced = research._coerce_structure_tool(
        "Show me the project structure for the frontend directory",
        "analyze_code_structures",
        {"path": "frontend"},
    )
    assert coerced is True
    assert tool_name == "tree_view"
    assert args["path"] == "frontend"
    assert args["max_depth"] == 2


def test_coerce_structure_tool_to_list_dir():
    tool_name, args, coerced = research._coerce_structure_tool(
        "List files under src",
        "analyze_code_structures",
        {"path": "src"},
    )
    assert coerced is True
    assert tool_name == "list_dir"
    assert args["pattern"] == "src/**"


def test_no_coerce_for_deep_structure():
    tool_name, args, coerced = research._coerce_structure_tool(
        "Analyze code structure and dependencies",
        "analyze_code_structures",
        {"path": "."},
    )
    assert coerced is False
    assert tool_name == "analyze_code_structures"
    assert args["path"] == "."
