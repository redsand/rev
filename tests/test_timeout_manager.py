import pytest
import time
from unittest.mock import Mock, call
from rev.execution.timeout_manager import TimeoutManager, TimeoutConfig, _is_transient_error

@pytest.fixture
def mock_transient_error_func():
    """A mock function that fails with a transient error a few times."""
    func = Mock()
    func.side_effect = [
        ConnectionResetError("Connection reset"),
        TimeoutError("Timed out"),
        "Success!",
    ]
    return func

@pytest.fixture
def mock_persistent_error_func():
    """A mock function that always fails."""
    func = Mock(side_effect=ValueError("Persistent error"))
    return func

def test_is_transient_error():
    assert _is_transient_error(ConnectionResetError("Connection reset by peer")) is True
    assert _is_transient_error(TimeoutError("Request timed out")) is True
    assert _is_transient_error(Exception("503 Service Unavailable")) is True
    assert _is_transient_error(ValueError("Invalid value")) is False
    assert _is_transient_error(TypeError("Wrong type")) is False

def test_retry_on_transient_error_succeeds(mock_transient_error_func):
    """Verify that the function is retried on transient errors and eventually succeeds."""
    config = TimeoutConfig(max_attempts=5, base_backoff_ms=1)
    manager = TimeoutManager(config)

    result = manager.execute_with_retry(mock_transient_error_func, "test")

    assert mock_transient_error_func.call_count == 3
    assert result == "Success!"

def test_no_retry_on_persistent_error(mock_persistent_error_func):
    """Verify that non-transient errors are not retried."""
    config = TimeoutConfig(max_attempts=5, base_backoff_ms=1)
    manager = TimeoutManager(config)

    with pytest.raises(ValueError, match="Persistent error"):
        manager.execute_with_retry(mock_persistent_error_func, "test")
    
    assert mock_persistent_error_func.call_count == 1

def test_max_retries_exhausted():
    """Verify that execution stops after max attempts are exhausted."""
    config = TimeoutConfig(max_attempts=3, base_backoff_ms=1)
    manager = TimeoutManager(config)
    
    func = Mock(side_effect=ConnectionAbortedError("Connection aborted"))
    
    with pytest.raises(ConnectionAbortedError):
        manager.execute_with_retry(func, "test")
    
    assert func.call_count == 3

def test_exponential_backoff_and_jitter(mocker):
    """Verify that backoff and jitter are applied correctly."""
    # Mock time.sleep to avoid actual delays in tests
    mock_sleep = mocker.patch("time.sleep")
    
    config = TimeoutConfig(
        max_attempts=4,
        base_backoff_ms=100,
        max_backoff_ms=500,
        jitter_fraction=1.0
    )
    manager = TimeoutManager(config)
    func = Mock(side_effect=TimeoutError("Timed out"))

    with pytest.raises(TimeoutError):
        manager.execute_with_retry(func, "test")

    assert func.call_count == 4
    
    # Check sleep calls
    # Attempt 1: fails, no sleep yet
    # Attempt 2: fails, sleep before retry 3
    # Attempt 3: fails, sleep before retry 4
    # Attempt 4: fails, raises exception
    assert mock_sleep.call_count == 3
    
    # Backoff for attempt 1 (before retry 2)
    # base * (2**(1-1)) = 100 * 1 = 100
    sleep_duration1 = mock_sleep.call_args_list[0].args[0]
    assert 100 / 1000 <= sleep_duration1 <= (100 + 100) / 1000

    # Backoff for attempt 2 (before retry 3)
    # base * (2**(2-1)) = 100 * 2 = 200
    sleep_duration2 = mock_sleep.call_args_list[1].args[0]
    assert 200 / 1000 <= sleep_duration2 <= (200 + 200) / 1000
    
    # Backoff for attempt 3 (before retry 4)
    # base * (2**(3-1)) = 100 * 4 = 400
    sleep_duration3 = mock_sleep.call_args_list[2].args[0]
    assert 400 / 1000 <= sleep_duration3 <= (400 + 400) / 1000
