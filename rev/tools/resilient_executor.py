#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resilient Tool Executor.

Provides robust tool execution with retries, exponential backoff, jitter, and idempotency.
Handles transient failures to stabilize agent coordination.
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Dict, Optional, List
from enum import Enum
import time
import random
import hashlib
import json
from pathlib import Path


class RetryPolicy(Enum):
    """Retry policies for different failure scenarios."""
    EXPONENTIAL_BACKOFF = "exponential"
    LINEAR_BACKOFF = "linear"
    FIXED_BACKOFF = "fixed"
    NO_RETRY = "none"


class JitterStrategy(Enum):
    """Jitter strategies to prevent thundering herd."""
    FULL = "full"  # Random jitter from 0 to backoff time
    EQUAL = "equal"  # Half deterministic, half random
    DECORRELATED = "decorrelated"  # Decorrelated jitter
    NONE = "none"  # No jitter


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 8
    backoff_policy: RetryPolicy = RetryPolicy.EXPONENTIAL_BACKOFF
    base_ms: int = 250
    max_ms: int = 5000
    jitter: JitterStrategy = JitterStrategy.FULL
    retry_on_exceptions: List[type] = field(default_factory=lambda: [
        ConnectionError,
        TimeoutError,
        OSError
    ])
    retry_on_status_codes: List[int] = field(default_factory=lambda: [
        500, 502, 503, 504,  # Server errors
        429  # Rate limit
    ])


@dataclass
class ToolCallResult:
    """Result of a tool call execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    total_time_ms: float = 0.0
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class IdempotencyStore:
    """Store for idempotency keys to prevent duplicate execution."""

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize idempotency store.

        Args:
            storage_path: Optional path to persist idempotency keys
        """
        self.storage_path = storage_path
        self._cache: Dict[str, ToolCallResult] = {}

        # Load from disk if storage path exists
        if self.storage_path and self.storage_path.exists():
            self._load_from_disk()

    def get(self, key: str) -> Optional[ToolCallResult]:
        """Get cached result for idempotency key."""
        return self._cache.get(key)

    def set(self, key: str, result: ToolCallResult):
        """Store result for idempotency key."""
        self._cache[key] = result

        # Persist to disk
        if self.storage_path:
            self._save_to_disk()

    def clear(self):
        """Clear all cached results."""
        self._cache.clear()

        if self.storage_path and self.storage_path.exists():
            self.storage_path.unlink()

    def _load_from_disk(self):
        """Load idempotency cache from disk."""
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                # Note: We only cache success/error, not the full result object
                # to avoid serialization issues
                for key, value in data.items():
                    self._cache[key] = ToolCallResult(
                        success=value["success"],
                        error=value.get("error"),
                        attempts=value.get("attempts", 1),
                        total_time_ms=value.get("total_time_ms", 0.0),
                        idempotency_key=key
                    )
        except Exception:
            # Ignore load errors - start fresh
            pass

    def _save_to_disk(self):
        """Save idempotency cache to disk."""
        if not self.storage_path:
            return

        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            for key, result in self._cache.items():
                data[key] = {
                    "success": result.success,
                    "error": result.error,
                    "attempts": result.attempts,
                    "total_time_ms": result.total_time_ms
                }

            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            # Ignore save errors
            pass


class ResilientExecutor:
    """Executes tool calls with retry logic, backoff, and idempotency."""

    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        idempotency_store: Optional[IdempotencyStore] = None
    ):
        """
        Initialize resilient executor.

        Args:
            retry_config: Optional retry configuration (uses defaults if not provided)
            idempotency_store: Optional idempotency store
        """
        self.retry_config = retry_config or RetryConfig()
        self.idempotency_store = idempotency_store or IdempotencyStore()

    def execute(
        self,
        tool_fn: Callable,
        *args,
        idempotency_key: Optional[str] = None,
        **kwargs
    ) -> ToolCallResult:
        """
        Execute a tool call with retry logic.

        Args:
            tool_fn: The tool function to execute
            *args: Positional arguments for the tool
            idempotency_key: Optional idempotency key for duplicate detection
            **kwargs: Keyword arguments for the tool

        Returns:
            ToolCallResult with success/failure information
        """
        # Generate idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = self._generate_idempotency_key(tool_fn, args, kwargs)

        # Check if we've already executed this call
        cached_result = self.idempotency_store.get(idempotency_key)
        if cached_result:
            return cached_result

        start_time = time.time()
        attempts = 0
        last_error = None

        for attempt in range(1, self.retry_config.max_attempts + 1):
            attempts = attempt

            try:
                # Execute tool
                result = tool_fn(*args, **kwargs)

                # Success!
                total_time_ms = (time.time() - start_time) * 1000
                tool_result = ToolCallResult(
                    success=True,
                    result=result,
                    attempts=attempts,
                    total_time_ms=total_time_ms,
                    idempotency_key=idempotency_key
                )

                # Cache result
                self.idempotency_store.set(idempotency_key, tool_result)

                return tool_result

            except Exception as e:
                last_error = e

                # Check if we should retry
                if not self._should_retry(e, attempt):
                    break

                # Calculate backoff
                if attempt < self.retry_config.max_attempts:
                    backoff_ms = self._calculate_backoff(attempt)
                    time.sleep(backoff_ms / 1000.0)

        # All attempts failed
        total_time_ms = (time.time() - start_time) * 1000
        tool_result = ToolCallResult(
            success=False,
            error=str(last_error),
            attempts=attempts,
            total_time_ms=total_time_ms,
            idempotency_key=idempotency_key,
            metadata={"exception_type": type(last_error).__name__}
        )

        # Cache failure result to prevent retrying same bad call
        self.idempotency_store.set(idempotency_key, tool_result)

        return tool_result

    def execute_with_resume(
        self,
        tool_fn: Callable,
        checkpoint_fn: Optional[Callable[[Any], None]] = None,
        *args,
        **kwargs
    ) -> ToolCallResult:
        """
        Execute a tool call with checkpoint/resume capability.

        Args:
            tool_fn: The tool function to execute
            checkpoint_fn: Optional function to call on each checkpoint
            *args: Positional arguments for the tool
            **kwargs: Keyword arguments for the tool

        Returns:
            ToolCallResult with success/failure information
        """
        # For now, wraps execute with checkpoint support
        # In a full implementation, this would handle partial execution state

        idempotency_key = kwargs.pop('idempotency_key', None)

        def wrapped_fn(*fn_args, **fn_kwargs):
            result = tool_fn(*fn_args, **fn_kwargs)

            # Call checkpoint function if provided
            if checkpoint_fn:
                checkpoint_fn(result)

            return result

        return self.execute(wrapped_fn, *args, idempotency_key=idempotency_key, **kwargs)

    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """Determine if we should retry based on exception type."""
        if attempt >= self.retry_config.max_attempts:
            return False

        # Check if exception type is retryable
        for exc_type in self.retry_config.retry_on_exceptions:
            if isinstance(exception, exc_type):
                return True

        # Check for HTTP status codes (if exception has status_code attribute)
        if hasattr(exception, 'status_code'):
            if exception.status_code in self.retry_config.retry_on_status_codes:
                return True

        return False

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time in milliseconds."""
        if self.retry_config.backoff_policy == RetryPolicy.NO_RETRY:
            return 0

        if self.retry_config.backoff_policy == RetryPolicy.FIXED_BACKOFF:
            base_backoff = self.retry_config.base_ms

        elif self.retry_config.backoff_policy == RetryPolicy.LINEAR_BACKOFF:
            base_backoff = self.retry_config.base_ms * attempt

        elif self.retry_config.backoff_policy == RetryPolicy.EXPONENTIAL_BACKOFF:
            base_backoff = self.retry_config.base_ms * (2 ** (attempt - 1))

        else:
            base_backoff = self.retry_config.base_ms

        # Cap at max_ms
        base_backoff = min(base_backoff, self.retry_config.max_ms)

        # Apply jitter
        backoff = self._apply_jitter(base_backoff)

        return backoff

    def _apply_jitter(self, backoff_ms: float) -> float:
        """Apply jitter to backoff time."""
        if self.retry_config.jitter == JitterStrategy.NONE:
            return backoff_ms

        elif self.retry_config.jitter == JitterStrategy.FULL:
            # Random jitter from 0 to backoff_ms
            return random.uniform(0, backoff_ms)

        elif self.retry_config.jitter == JitterStrategy.EQUAL:
            # Half deterministic, half random
            half = backoff_ms / 2
            return half + random.uniform(0, half)

        elif self.retry_config.jitter == JitterStrategy.DECORRELATED:
            # Decorrelated jitter (uses previous backoff)
            # Simplified version - use base backoff
            return random.uniform(self.retry_config.base_ms, backoff_ms * 3)

        return backoff_ms

    def _generate_idempotency_key(
        self,
        tool_fn: Callable,
        args: tuple,
        kwargs: dict
    ) -> str:
        """Generate idempotency key from function and arguments."""
        # Create a stable representation of the call
        call_repr = {
            "function": tool_fn.__name__,
            "module": tool_fn.__module__,
            "args": str(args),  # Simple string representation
            "kwargs": str(sorted(kwargs.items()))
        }

        # Hash it
        call_str = json.dumps(call_repr, sort_keys=True)
        return hashlib.sha256(call_str.encode()).hexdigest()[:16]


def create_default_executor(workspace_root: Optional[Path] = None) -> ResilientExecutor:
    """
    Create a ResilientExecutor with default configuration.

    Args:
        workspace_root: Optional workspace root for idempotency storage

    Returns:
        ResilientExecutor instance
    """
    # Default retry config (matching the spec)
    retry_config = RetryConfig(
        max_attempts=8,
        backoff_policy=RetryPolicy.EXPONENTIAL_BACKOFF,
        base_ms=250,
        max_ms=5000,
        jitter=JitterStrategy.FULL
    )

    # Idempotency store
    storage_path = None
    if workspace_root:
        storage_path = workspace_root / ".rev" / "idempotency_cache.json"

    idempotency_store = IdempotencyStore(storage_path=storage_path)

    return ResilientExecutor(
        retry_config=retry_config,
        idempotency_store=idempotency_store
    )


# Decorator for easy use
def resilient(
    max_attempts: int = 8,
    base_ms: int = 250,
    max_ms: int = 5000
):
    """
    Decorator to make a function resilient with retries.

    Usage:
        @resilient(max_attempts=5, base_ms=100)
        def my_tool_call():
            # ... tool implementation
    """
    def decorator(fn):
        executor = ResilientExecutor(
            retry_config=RetryConfig(
                max_attempts=max_attempts,
                base_ms=base_ms,
                max_ms=max_ms
            )
        )

        def wrapper(*args, **kwargs):
            result = executor.execute(fn, *args, **kwargs)
            if not result.success:
                raise Exception(result.error)
            return result.result

        return wrapper

    return decorator
