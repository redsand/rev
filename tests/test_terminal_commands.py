import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rev.terminal.commands import AddDirCommand, StatusCommand
from rev.settings_manager import get_default_mode


def _build_session_context():
    mode_name, mode_config = get_default_mode()
    return {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": "",
        "token_usage": {"total": 0, "prompt": 0, "completion": 0},
        "execution_mode": mode_name,
        "mode_config": mode_config,
        "additional_dirs": [],
    }


def test_add_dir_tracks_directories_in_session(tmp_path):
    session_context = _build_session_context()
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()

    result = AddDirCommand().execute([str(extra_dir)], session_context)

    assert "Added directories" in result
    assert str(extra_dir.resolve()) in session_context["additional_dirs"]

    repeat_result = AddDirCommand().execute([str(extra_dir)], session_context)

    assert repeat_result == "No new directories added (already tracked)"
    assert session_context["additional_dirs"].count(str(extra_dir.resolve())) == 1


def test_add_dir_rejects_missing_path(tmp_path):
    session_context = _build_session_context()
    missing = tmp_path / "missing"

    result = AddDirCommand().execute([str(missing)], session_context)

    assert result == f"Error: Directory not found: {missing}"
    assert session_context["additional_dirs"] == []


def test_status_lists_additional_directories(tmp_path):
    session_context = _build_session_context()
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    session_context["additional_dirs"].append(str(extra_dir.resolve()))

    output = StatusCommand().execute([], session_context)

    assert "Additional directories" in output
    assert str(extra_dir.resolve()) in output
