from rev.execution.orchestrator import _order_available_actions


def test_available_actions_prioritize_read_analyze_first():
    ordered = _order_available_actions(
        [
            "refactor",
            "edit",
            "test",
            "read",
            "analyze",
            "create_directory",
            "add",
            "research",
        ]
    )
    assert ordered[:4] == ["read", "analyze", "research", "create_directory"]


def test_available_actions_keep_unknown_actions_but_late():
    ordered = _order_available_actions(["edit", "read", "zany_action"])
    assert ordered[0] == "read"
    assert ordered[-1] == "zany_action"

