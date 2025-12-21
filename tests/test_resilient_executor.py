#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for resilient tool executor."""

import pytest
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from rev.tools.resilient_executor import (
    ResilientExecutor,
    RetryConfig,
    RetryPolicy,
    JitterStrategy,
    ToolCallResult,
    IdempotencyStore,
    create_default_executor,
    resilient
)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    workspace = Path(tempfile.mkdtemp())
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def retry_config():
    """Create a basic retry configuration."""
    return RetryConfig(
        max_attempts=3,
        base_ms=10,  # Fast for testing
        max_ms=100,
        jitter=JitterStrategy.NONE  # Deterministic for testing
    )


@pytest.fixture
def executor(retry_config):
    """Create a resilient executor."""
    return ResilientExecutor(retry_config=retry_config)


class TestRetryLogic:
    """Test retry logic and backoff."""

    def test_successful_call_no_retry(self, executor):
        """Successful call should not retry."""
        call_count = 0

        def successful_fn():
            nonlocal call_count
            call_count += 1
            return "success"

        result = executor.execute(successful_fn)

        assert result.success
        assert result.result == "success"
        assert result.attempts == 1
        assert call_count == 1

    def test_transient_failure_retries(self, executor):
        """Transient failure should trigger retries."""
        call_count = 0

        def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Transient error")
            return "success"

        result = executor.execute(flaky_fn)

        assert result.success
        assert result.result == "success"
        assert result.attempts == 3
        assert call_count == 3

    def test_persistent_failure_exhausts_retries(self, executor):
        """Persistent failure should exhaust all retries."""
        call_count = 0

        def failing_fn():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Persistent error")

        result = executor.execute(failing_fn)

        assert not result.success
        assert "Persistent error" in result.error
        assert result.attempts == executor.retry_config.max_attempts
        assert call_count == executor.retry_config.max_attempts

    def test_non_retryable_exception_fails_immediately(self, executor):
        """Non-retryable exceptions should not trigger retries."""
        call_count = 0

        def bad_fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("Bad input")  # Not in retry_on_exceptions

        result = executor.execute(bad_fn)

        assert not result.success
        assert "Bad input" in result.error
        assert result.attempts == 1
        assert call_count == 1


class TestBackoffCalculation:
    """Test backoff time calculation."""

    def test_exponential_backoff(self):
        """Exponential backoff should double each time."""
        config = RetryConfig(
            backoff_policy=RetryPolicy.EXPONENTIAL_BACKOFF,
            base_ms=100,
            max_ms=10000,
            jitter=JitterStrategy.NONE
        )
        executor = ResilientExecutor(retry_config=config)

        assert executor._calculate_backoff(1) == 100
        assert executor._calculate_backoff(2) == 200
        assert executor._calculate_backoff(3) == 400
        assert executor._calculate_backoff(4) == 800

    def test_linear_backoff(self):
        """Linear backoff should increase linearly."""
        config = RetryConfig(
            backoff_policy=RetryPolicy.LINEAR_BACKOFF,
            base_ms=100,
            max_ms=10000,
            jitter=JitterStrategy.NONE
        )
        executor = ResilientExecutor(retry_config=config)

        assert executor._calculate_backoff(1) == 100
        assert executor._calculate_backoff(2) == 200
        assert executor._calculate_backoff(3) == 300
        assert executor._calculate_backoff(4) == 400

    def test_fixed_backoff(self):
        """Fixed backoff should always be the same."""
        config = RetryConfig(
            backoff_policy=RetryPolicy.FIXED_BACKOFF,
            base_ms=100,
            max_ms=10000,
            jitter=JitterStrategy.NONE
        )
        executor = ResilientExecutor(retry_config=config)

        assert executor._calculate_backoff(1) == 100
        assert executor._calculate_backoff(2) == 100
        assert executor._calculate_backoff(3) == 100

    def test_backoff_capped_at_max(self):
        """Backoff should be capped at max_ms."""
        config = RetryConfig(
            backoff_policy=RetryPolicy.EXPONENTIAL_BACKOFF,
            base_ms=100,
            max_ms=500,
            jitter=JitterStrategy.NONE
        )
        executor = ResilientExecutor(retry_config=config)

        # Would be 800 without cap
        assert executor._calculate_backoff(4) == 500
        assert executor._calculate_backoff(10) == 500


class TestJitterStrategy:
    """Test jitter strategies."""

    def test_no_jitter(self):
        """No jitter should return exact backoff."""
        config = RetryConfig(jitter=JitterStrategy.NONE)
        executor = ResilientExecutor(retry_config=config)

        backoff = executor._apply_jitter(1000)
        assert backoff == 1000

    def test_full_jitter(self):
        """Full jitter should be random between 0 and backoff."""
        config = RetryConfig(jitter=JitterStrategy.FULL)
        executor = ResilientExecutor(retry_config=config)

        for _ in range(10):
            backoff = executor._apply_jitter(1000)
            assert 0 <= backoff <= 1000

    def test_equal_jitter(self):
        """Equal jitter should be random between half and full backoff."""
        config = RetryConfig(jitter=JitterStrategy.EQUAL)
        executor = ResilientExecutor(retry_config=config)

        for _ in range(10):
            backoff = executor._apply_jitter(1000)
            assert 500 <= backoff <= 1000

    def test_decorrelated_jitter(self):
        """Decorrelated jitter should vary widely."""
        config = RetryConfig(
            jitter=JitterStrategy.DECORRELATED,
            base_ms=100
        )
        executor = ResilientExecutor(retry_config=config)

        # Decorrelated can exceed base backoff
        backoffs = [executor._apply_jitter(1000) for _ in range(10)]
        assert any(b < 1000 for b in backoffs)  # Some below
        # Note: May or may not exceed 1000 depending on random


class TestIdempotency:
    """Test idempotency key generation and caching."""

    def test_same_call_returns_cached_result(self, executor):
        """Same call should return cached result without re-execution."""
        call_count = 0

        def expensive_fn():
            nonlocal call_count
            call_count += 1
            return "result"

        # First call
        result1 = executor.execute(expensive_fn, idempotency_key="test-key")
        assert result1.success
        assert call_count == 1

        # Second call (should be cached)
        result2 = executor.execute(expensive_fn, idempotency_key="test-key")
        assert result2.success
        assert call_count == 1  # Not called again!

    def test_different_key_executes_again(self, executor):
        """Different key should execute again."""
        call_count = 0

        def expensive_fn():
            nonlocal call_count
            call_count += 1
            return "result"

        result1 = executor.execute(expensive_fn, idempotency_key="key1")
        result2 = executor.execute(expensive_fn, idempotency_key="key2")

        assert result1.success
        assert result2.success
        assert call_count == 2

    def test_auto_generated_idempotency_key(self, executor):
        """Auto-generated key should be consistent for same call."""
        def fn_with_args(x, y):
            return x + y

        # Same args should generate same key
        result1 = executor.execute(fn_with_args, 1, 2)
        result2 = executor.execute(fn_with_args, 1, 2)

        assert result1.idempotency_key == result2.idempotency_key

    def test_different_args_generate_different_keys(self, executor):
        """Different args should generate different keys."""
        def fn_with_args(x, y):
            return x + y

        result1 = executor.execute(fn_with_args, 1, 2)
        result2 = executor.execute(fn_with_args, 3, 4)

        assert result1.idempotency_key != result2.idempotency_key


class TestIdempotencyStore:
    """Test idempotency store persistence."""

    def test_store_get_set(self, temp_workspace):
        """Store should save and retrieve results."""
        store = IdempotencyStore()

        result = ToolCallResult(success=True, result="test", idempotency_key="key1")
        store.set("key1", result)

        retrieved = store.get("key1")
        assert retrieved is not None
        assert retrieved.success
        assert retrieved.idempotency_key == "key1"

    def test_store_persistence(self, temp_workspace):
        """Store should persist to disk."""
        storage_path = temp_workspace / "idempotency.json"

        # Create store and save result
        store1 = IdempotencyStore(storage_path=storage_path)
        result = ToolCallResult(success=True, error=None, idempotency_key="key1")
        store1.set("key1", result)

        # Create new store (should load from disk)
        store2 = IdempotencyStore(storage_path=storage_path)
        retrieved = store2.get("key1")

        assert retrieved is not None
        assert retrieved.success

    def test_store_clear(self, temp_workspace):
        """Clear should remove all cached results."""
        storage_path = temp_workspace / "idempotency.json"
        store = IdempotencyStore(storage_path=storage_path)

        store.set("key1", ToolCallResult(success=True, idempotency_key="key1"))
        store.set("key2", ToolCallResult(success=True, idempotency_key="key2"))

        store.clear()

        assert store.get("key1") is None
        assert store.get("key2") is None
        assert not storage_path.exists()


class TestResumeCapability:
    """Test resumable tool calls with checkpoints."""

    def test_execute_with_resume_calls_checkpoint(self, executor):
        """Execute with resume should call checkpoint function."""
        checkpoints = []

        def checkpoint_fn(result):
            checkpoints.append(result)

        def tool_fn():
            return "result"

        result = executor.execute_with_resume(tool_fn, checkpoint_fn)

        assert result.success
        assert len(checkpoints) == 1
        assert checkpoints[0] == "result"

    def test_execute_with_resume_no_checkpoint(self, executor):
        """Execute with resume should work without checkpoint function."""
        def tool_fn():
            return "result"

        result = executor.execute_with_resume(tool_fn, checkpoint_fn=None)

        assert result.success
        assert result.result == "result"


class TestResilientDecorator:
    """Test @resilient decorator."""

    def test_decorator_makes_function_resilient(self):
        """Decorator should add retry logic to function."""
        call_count = 0

        @resilient(max_attempts=3, base_ms=1)
        def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Flaky")
            return "success"

        result = flaky_fn()

        assert result == "success"
        assert call_count == 2

    def test_decorator_raises_on_failure(self):
        """Decorator should raise exception on persistent failure."""
        @resilient(max_attempts=2, base_ms=1)
        def failing_fn():
            raise ConnectionError("Always fails")

        with pytest.raises(Exception, match="Always fails"):
            failing_fn()


class TestDefaultExecutor:
    """Test default executor creation."""

    def test_create_default_executor(self, temp_workspace):
        """Should create executor with default config."""
        executor = create_default_executor(workspace_root=temp_workspace)

        assert executor.retry_config.max_attempts == 8
        assert executor.retry_config.base_ms == 250
        assert executor.retry_config.max_ms == 5000
        assert executor.retry_config.jitter == JitterStrategy.FULL

    def test_default_executor_works(self, temp_workspace):
        """Default executor should work correctly."""
        executor = create_default_executor(workspace_root=temp_workspace)

        def test_fn():
            return "test"

        result = executor.execute(test_fn)

        assert result.success
        assert result.result == "test"


class TestErrorMetadata:
    """Test error metadata collection."""

    def test_result_includes_exception_type(self, executor):
        """Failed result should include exception type."""
        def failing_fn():
            raise ValueError("Bad value")

        result = executor.execute(failing_fn)

        assert not result.success
        assert result.metadata["exception_type"] == "ValueError"

    def test_result_includes_timing(self, executor):
        """Result should include execution time."""
        def slow_fn():
            time.sleep(0.01)
            return "done"

        result = executor.execute(slow_fn)

        assert result.success
        assert result.total_time_ms > 10  # At least 10ms


class TestRetryableExceptions:
    """Test custom retryable exceptions."""

    def test_custom_retryable_exception(self):
        """Should retry on custom exception types."""
        config = RetryConfig(
            max_attempts=3,
            base_ms=1,
            retry_on_exceptions=[RuntimeError, ValueError]
        )
        executor = ResilientExecutor(retry_config=config)

        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("Custom error")
            return "success"

        result = executor.execute(fn)

        assert result.success
        assert call_count == 2

    def test_http_status_code_retry(self):
        """Should retry on specific HTTP status codes."""
        config = RetryConfig(
            max_attempts=3,
            base_ms=1,
            retry_on_status_codes=[500, 502, 503]
        )
        executor = ResilientExecutor(retry_config=config)

        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1

            class HTTPError(Exception):
                def __init__(self, status_code):
                    self.status_code = status_code
                    super().__init__(f"HTTP {status_code}")

            if call_count < 2:
                raise HTTPError(503)
            return "success"

        result = executor.execute(fn)

        assert result.success
        assert call_count == 2


class TestConcurrentCalls:
    """Test behavior with concurrent tool calls."""

    def test_idempotency_with_concurrent_calls(self, executor):
        """Idempotency should prevent duplicate execution of same call."""
        call_count = 0

        def expensive_fn():
            nonlocal call_count
            call_count += 1
            time.sleep(0.01)
            return "result"

        # Simulate concurrent calls with same key
        key = "concurrent-test"
        result1 = executor.execute(expensive_fn, idempotency_key=key)
        result2 = executor.execute(expensive_fn, idempotency_key=key)
        result3 = executor.execute(expensive_fn, idempotency_key=key)

        assert result1.success
        assert result2.success
        assert result3.success
        assert call_count == 1  # Only executed once!
