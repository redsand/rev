from rev.agents.research import _has_empty_path_arg


def test_empty_path_guard_triggers_for_blank_paths():
    assert _has_empty_path_arg("read_file", {"path": ""}) is True
    assert _has_empty_path_arg("read_file", {"path": "   "}) is True


def test_empty_path_guard_ignores_valid_or_other_tools():
    assert _has_empty_path_arg("read_file", {"path": "src/app.ts"}) is False
    assert _has_empty_path_arg("search_code", {"pattern": "foo"}) is False
