"""Tests for debug action planning behavior."""

from rev.execution import planner as planner_mod


def test_debug_action_inserts_write_tool_when_path_present():
    task = {
        "description": "Fix bug in src/app.py",
        "action_type": "debug",
    }
    updated = planner_mod._coerce_actionable_task(task, project_type="python")

    assert updated["action_type"] == "debug"
    assert "use replace_in_file" in updated["description"]


def test_debug_action_without_path_coerces_to_review():
    task = {
        "description": "Fix login bug in auth handler",
        "action_type": "debug",
    }
    updated = planner_mod._coerce_actionable_task(task, project_type="python")

    assert updated["action_type"] == "review"
