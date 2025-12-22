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


def test_llm_transaction_logging(tmp_path: Path, monkeypatch):
    from rev import config
    
    # Configure transaction log path to be in tmp_path
    log_path = tmp_path / "llm_transactions.log"
    monkeypatch.setattr(config, "LLM_TRANSACTION_LOG_ENABLED", True)
    monkeypatch.setattr(config, "LLM_TRANSACTION_LOG_PATH", str(log_path))
    
    logger = DebugLogger.initialize(enabled=True, log_dir=tmp_path)
    
    # Simulate logging an LLM transcript
    logger.log_llm_transcript(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        response={"message": {"role": "assistant", "content": "hi"}}
    )
    
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "LLM TRANSCRIPT" in content
    assert "test-model" in content
    assert "hello" in content
    assert "hi" in content
