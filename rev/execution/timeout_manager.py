#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Timeout and retry management for long-running operations.

This module provides intelligent timeout handling with:
- Configurable timeouts with retry logic
- Exponential backoff for retries
- Maximum retry limits
- Graceful degradation
"""

import os
import signal
import time
import functools
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass

from rev.debug_logger import get_logger


@dataclass
class TimeoutConfig:
    """Configuration for timeout behavior."""
    initial_timeout: int = 300  # 5 minutes
    max_timeout: int = 1800  # 30 minutes
    max_retries: int = 3
    timeout_multiplier: float = 2.0  # Exponential backoff multiplier

    @classmethod
    def from_env(cls, prefix: str = "REV") -> 'TimeoutConfig':
        """Create config from environment variables.

        Args:
            prefix: Environment variable prefix (default: REV)

        Returns:
            TimeoutConfig instance
        """
        return cls(
            initial_timeout=int(os.getenv(f"{prefix}_INITIAL_TIMEOUT", "300")),
            max_timeout=int(os.getenv(f"{prefix}_MAX_TIMEOUT", "1800")),
            max_retries=int(os.getenv(f"{prefix}_MAX_RETRIES", "3")),
            timeout_multiplier=float(os.getenv(f"{prefix}_TIMEOUT_MULTIPLIER", "2.0"))
        )

    def get_timeout_for_attempt(self, attempt: int) -> int:
        """Calculate timeout for a given retry attempt.

        Args:
            attempt: Attempt number (0-based)

        Returns:
            Timeout in seconds, capped at max_timeout
        """
        timeout = int(self.initial_timeout * (self.timeout_multiplier ** attempt))
        return min(timeout, self.max_timeout)


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


class MaxRetriesExceededError(Exception):
    """Raised when maximum retry attempts are exhausted."""
    def __init__(self, attempts: int, last_error: Optional[Exception] = None):
        self.attempts = attempts
        self.last_error = last_error
        message = f"Maximum retry attempts ({attempts}) exceeded"
        if last_error:
            message += f". Last error: {last_error}"
        super().__init__(message)


def timeout_handler(signum, frame):
    """Signal handler for timeout."""
    raise TimeoutError("Operation timed out")


def with_timeout(
    func: Callable,
    timeout: int,
    *args,
    **kwargs
) -> Any:
    """Execute a function with a timeout.

    Args:
        func: Function to execute
        timeout: Timeout in seconds
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Function result

    Raises:
        TimeoutError: If operation times out
    """
    # Set up signal-based timeout (Unix-like systems)
    if hasattr(signal, 'SIGALRM'):
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)

        try:
            result = func(*args, **kwargs)
            signal.alarm(0)  # Cancel alarm
            return result
        except TimeoutError:
            raise
        finally:
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # For Windows or systems without SIGALRM, use threading
        import threading

        result = {"value": None, "error": None}

        def target():
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            # Thread is still running - timeout occurred
            raise TimeoutError(f"Operation timed out after {timeout} seconds")

        if result["error"]:
            raise result["error"]

        return result["value"]


def with_retry_and_timeout(
    config: Optional[TimeoutConfig] = None,
    operation_name: str = "operation"
) -> Callable:
    """Decorator for retry and timeout logic.

    Args:
        config: TimeoutConfig instance. If None, uses environment defaults.
        operation_name: Name of operation for logging

    Returns:
        Decorator function
    """
    if config is None:
        config = TimeoutConfig.from_env()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = get_logger()

            for attempt in range(config.max_retries):
                timeout = config.get_timeout_for_attempt(attempt)

                if attempt > 0:
                    logger.log("timeout", "RETRY_ATTEMPT", {
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "max_retries": config.max_retries,
                        "timeout_seconds": timeout,
                        "timeout_minutes": timeout // 60
                    }, "INFO")

                    print(f"  ⚠ Retrying {operation_name} (attempt {attempt + 1}/{config.max_retries}, timeout: {timeout}s)")

                try:
                    # Execute with timeout
                    result = with_timeout(func, timeout, *args, **kwargs)

                    if attempt > 0:
                        logger.log("timeout", "RETRY_SUCCESS", {
                            "operation": operation_name,
                            "attempt": attempt + 1,
                            "timeout": timeout
                        }, "INFO")
                        print(f"  ✓ {operation_name} succeeded after {attempt + 1} attempt(s)")

                    return result

                except TimeoutError as e:
                    logger.log("timeout", "TIMEOUT", {
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "timeout": timeout,
                        "will_retry": attempt < config.max_retries - 1
                    }, "WARNING")

                    if attempt < config.max_retries - 1:
                        next_timeout = config.get_timeout_for_attempt(attempt + 1)
                        print(f"  ⏱ {operation_name} timed out after {timeout}s. Will retry with {next_timeout}s timeout...")
                        time.sleep(2)  # Brief pause before retry
                        continue
                    else:
                        logger.log("timeout", "MAX_RETRIES_EXCEEDED", {
                            "operation": operation_name,
                            "attempts": config.max_retries,
                            "final_timeout": timeout
                        }, "ERROR")
                        raise MaxRetriesExceededError(config.max_retries, e)

                except Exception as e:
                    # Non-timeout errors - don't retry by default
                    logger.log("timeout", "ERROR", {
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }, "ERROR")
                    raise

            # Should never reach here
            raise MaxRetriesExceededError(config.max_retries)

        return wrapper
    return decorator


class TimeoutManager:
    """Manages timeouts and retries for operations."""

    def __init__(self, config: Optional[TimeoutConfig] = None):
        """Initialize timeout manager.

        Args:
            config: TimeoutConfig instance. If None, uses environment defaults.
        """
        self.config = config or TimeoutConfig.from_env()
        self.logger = get_logger()
        self._operation_stats: Dict[str, Dict[str, int]] = {}

    def execute_with_retry(
        self,
        func: Callable,
        operation_name: str,
        *args,
        **kwargs
    ) -> Any:
        """Execute a function with retry and timeout logic.

        Args:
            func: Function to execute
            operation_name: Name of operation for logging
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Function result

        Raises:
            MaxRetriesExceededError: If all retry attempts fail
        """
        # Track operation stats
        if operation_name not in self._operation_stats:
            self._operation_stats[operation_name] = {
                "attempts": 0,
                "successes": 0,
                "timeouts": 0,
                "failures": 0
            }

        stats = self._operation_stats[operation_name]

        for attempt in range(self.config.max_retries):
            timeout = self.config.get_timeout_for_attempt(attempt)
            stats["attempts"] += 1

            if attempt > 0:
                self.logger.log("timeout", "RETRY_ATTEMPT", {
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "max_retries": self.config.max_retries,
                    "timeout_seconds": timeout,
                    "timeout_minutes": timeout // 60
                }, "INFO")

                print(f"  ⚠ Retrying {operation_name} (attempt {attempt + 1}/{self.config.max_retries}, timeout: {timeout}s)")

            try:
                result = with_timeout(func, timeout, *args, **kwargs)
                stats["successes"] += 1

                if attempt > 0:
                    self.logger.log("timeout", "RETRY_SUCCESS", {
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "stats": stats
                    }, "INFO")
                    print(f"  ✓ {operation_name} succeeded after {attempt + 1} attempt(s)")

                return result

            except TimeoutError as e:
                stats["timeouts"] += 1

                self.logger.log("timeout", "TIMEOUT", {
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "timeout": timeout,
                    "will_retry": attempt < self.config.max_retries - 1,
                    "stats": stats
                }, "WARNING")

                if attempt < self.config.max_retries - 1:
                    next_timeout = self.config.get_timeout_for_attempt(attempt + 1)
                    print(f"  ⏱ {operation_name} timed out after {timeout}s. Will retry with {next_timeout}s timeout...")
                    time.sleep(2)  # Brief pause before retry
                    continue
                else:
                    self.logger.log("timeout", "MAX_RETRIES_EXCEEDED", {
                        "operation": operation_name,
                        "attempts": self.config.max_retries,
                        "final_timeout": timeout,
                        "stats": stats
                    }, "ERROR")
                    stats["failures"] += 1
                    raise MaxRetriesExceededError(self.config.max_retries, e)

            except Exception as e:
                stats["failures"] += 1
                self.logger.log("timeout", "ERROR", {
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "stats": stats
                }, "ERROR")
                raise

        # Should never reach here
        stats["failures"] += 1
        raise MaxRetriesExceededError(self.config.max_retries)

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Get operation statistics.

        Returns:
            Dictionary of operation names to their stats
        """
        return self._operation_stats.copy()

    def print_stats(self):
        """Print operation statistics."""
        if not self._operation_stats:
            print("No timeout operations tracked")
            return

        print("\n" + "=" * 60)
        print("TIMEOUT MANAGER STATISTICS")
        print("=" * 60)

        for operation, stats in self._operation_stats.items():
            success_rate = (stats["successes"] / stats["attempts"] * 100) if stats["attempts"] > 0 else 0
            print(f"\n{operation}:")
            print(f"  Total attempts: {stats['attempts']}")
            print(f"  Successes: {stats['successes']}")
            print(f"  Timeouts: {stats['timeouts']}")
            print(f"  Failures: {stats['failures']}")
            print(f"  Success rate: {success_rate:.1f}%")

        print("=" * 60)
