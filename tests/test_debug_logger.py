from pathlib import Path

import pytest

from rev.debug_logger import DebugLogger


@pytest.fixture(autouse=True)
def reset_debug_logger():
    """Reset the singleton logger before and after each test."""
    DebugLogger._instance = None
    DebugLogger._loggers = {}
    yield
    instance = DebugLogger._instance
    if instance and instance.enabled:
        instance.close()
    DebugLogger._instance = None
    DebugLogger._loggers = {}


def test_plain_logging_helpers_write_when_enabled(tmp_path: Path):
    logger = DebugLogger.initialize(enabled=True, log_dir=tmp_path)

    logger.info("info message")
    logger.warning("warn %s", "message")
    logger.error("error message")
    logger.debug("debug message")
    logger.close()

    log_file = logger.log_file_path
    assert log_file is not None
    assert log_file.exists()

    content = log_file.read_text()
    assert "rev.general" in content
    assert "info message" in content
    assert "warn message" in content
    assert "error message" in content
    assert "debug message" in content


def test_plain_logging_helpers_are_noops_when_disabled(tmp_path: Path):
    logger = DebugLogger.initialize(enabled=False, log_dir=tmp_path)

    logger.info("info message")
    logger.warning("warn message")
    logger.error("error message")
    logger.debug("debug message")

    assert logger.log_file_path is None
    assert not any(tmp_path.iterdir())
