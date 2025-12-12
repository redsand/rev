import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rev import config
from rev import settings_manager


@pytest.fixture(autouse=True)
def restore_runtime_settings(monkeypatch):
    """Restore runtime settings and related env var after each test."""

    snapshot = {
        key: setting.getter() for key, setting in settings_manager.RUNTIME_SETTINGS.items()
    }
    private_mode_env = os.environ.get("REV_PRIVATE_MODE")
    yield
    for key, value in snapshot.items():
        settings_manager.RUNTIME_SETTINGS[key].setter(value)
    if private_mode_env is None:
        os.environ.pop("REV_PRIVATE_MODE", None)
    else:
        os.environ["REV_PRIVATE_MODE"] = private_mode_env


def test_set_runtime_setting_updates_value_and_parses_bool():
    updated = settings_manager.set_runtime_setting("execution_supports_tools", "false")

    assert updated is False
    assert config.EXECUTION_SUPPORTS_TOOLS is False


def test_apply_runtime_settings_ignores_invalid_and_unknown():
    original_reads = config.MAX_READ_FILE_PER_TASK

    settings_manager.apply_runtime_settings(
        {
            "max_read_file_per_task": "0",  # invalid (must be >=1)
            "prefer_reuse": "no",  # valid boolean parsing
            "unknown_setting": "ignored",
        }
    )

    assert config.MAX_READ_FILE_PER_TASK == original_reads
    assert config.PREFER_REUSE is False


def test_reset_runtime_settings_restores_defaults_and_env(monkeypatch):
    settings_manager.set_runtime_setting("max_run_cmd_per_task", 42)
    settings_manager.set_runtime_setting("private_mode", True)

    settings_manager.reset_runtime_settings()

    assert (
        config.MAX_RUN_CMD_PER_TASK
        == settings_manager.RUNTIME_SETTINGS["max_run_cmd_per_task"].default
    )
    assert config.get_private_mode() == settings_manager.RUNTIME_SETTINGS[
        "private_mode"
    ].default
    assert os.environ.get("REV_PRIVATE_MODE") == (
        "true"
        if settings_manager.RUNTIME_SETTINGS["private_mode"].default
        else "false"
    )
