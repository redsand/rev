from rev.execution.orchestrator import _order_available_actions, _is_goal_achieved_response


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


def test_goal_achieved_response_is_detected():
    variants = [
        "GOAL ACHIEVED",
        "[GOAL_ACHIEVED]",
        "goal_achieved",
        "goal achieved - stopping now",
        "Goal",
    ]
    for text in variants:
        assert _is_goal_achieved_response(text)
    assert not _is_goal_achieved_response("keep going")
