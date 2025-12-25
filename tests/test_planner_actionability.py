from rev.execution import planner


def test_review_task_injects_list_dir_tool():
    tasks = [{"description": "Review existing code patterns", "action_type": "review", "complexity": "low"}]
    updated = planner._ensure_actionable_subtasks(tasks, "request")

    desc = updated[0]["description"].lower()
    assert "list_dir" in desc
    assert "on ." in desc


def test_edit_task_without_path_becomes_review_search():
    tasks = [{"description": "Update authentication logic", "action_type": "edit", "complexity": "medium"}]
    updated = planner._ensure_actionable_subtasks(tasks, "request")

    desc = updated[0]["description"].lower()
    assert updated[0]["action_type"] == "review"
    assert "search_code" in desc


def test_edit_task_with_path_appends_tool():
    tasks = [{"description": "Update src/app.py to use new config", "action_type": "edit", "complexity": "low"}]
    updated = planner._ensure_actionable_subtasks(tasks, "request")

    desc = updated[0]["description"].lower()
    assert updated[0]["action_type"] == "edit"
    assert "replace_in_file" in desc


def test_add_directory_task_uses_create_directory():
    tasks = [{"description": "Create directory src/components", "action_type": "add", "complexity": "low"}]
    updated = planner._ensure_actionable_subtasks(tasks, "request")

    desc = updated[0]["description"].lower()
    assert updated[0]["action_type"] == "add"
    assert "create_directory" in desc


def test_test_task_infers_default_command(monkeypatch):
    monkeypatch.setattr(planner, "detect_project_type", lambda _: "python")
    tasks = [{"description": "Run tests", "action_type": "test", "complexity": "low"}]
    updated = planner._ensure_actionable_subtasks(tasks, "request")

    desc = updated[0]["description"].lower()
    assert updated[0]["action_type"] == "test"
    assert "run_tests" in desc
    assert "pytest -q" in desc
