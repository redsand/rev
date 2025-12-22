#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retry logic for LLM provider requests."""

import time
from typing import Any, Callable

from rev.llm.providers.base import ProviderError, RetryConfig, ErrorClass
from rev.debug_logger import get_logger


logger = get_logger()


class RetryHandler:
    """Handles retry logic for LLM requests with exponential backoff."""

    def __init__(self, config: RetryConfig):
        """Initialize retry handler.

        Args:
            config: Retry configuration
        """
        self.config = config

    def should_retry(self, error: ProviderError, attempt: int) -> bool:
        """Determine if an operation should be retried.

        Args:
            error: The error that occurred
            attempt: Current attempt number (1-indexed)

        Returns:
            True if should retry, False otherwise
        """
        # Check if we've exceeded max retries
        if self.config.max_retries > 0 and attempt >= self.config.max_retries:
            logger.info(f"Max retries ({self.config.max_retries}) exceeded")
            return False

        # Check if error is retryable
        if not error.retryable:
            logger.info(f"Error is not retryable: {error.error_class}")
            return False

        # Check if error class is in retry list
        if error.error_class not in self.config.retry_on:
            logger.info(f"Error class {error.error_class} not in retry list")
            return False

        return True

    def get_backoff_delay(self, attempt: int, retry_after: float = None) -> float:
        """Calculate backoff delay for retry.

        Args:
            attempt: Current attempt number (1-indexed)
            retry_after: Optional explicit delay from rate limit header

        Returns:
            Delay in seconds
        """
        # Use explicit retry_after if provided
        if retry_after is not None and retry_after > 0:
            delay = min(retry_after, self.config.max_backoff)
            logger.info(f"Using explicit retry_after: {delay}s")
            return delay

        # Calculate exponential or fixed backoff
        if self.config.exponential:
            # Exponential backoff: base * 2^(attempt-1)
            delay = self.config.base_backoff * (2 ** (attempt - 1))
        else:
            # Fixed backoff
            delay = self.config.base_backoff

        # Cap at max_backoff
        delay = min(delay, self.config.max_backoff)

        logger.info(f"Calculated backoff delay: {delay}s for attempt {attempt}")
        return delay

    def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute a function with automatic retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from successful function call

        Raises:
            Last exception if all retries fail
        """
        attempt = 1
        last_error = None

        while True:
            try:
                logger.debug(f"Attempt {attempt} for {func.__name__}")
                result = func(*args, **kwargs)

                if attempt > 1:
                    logger.info(f"Retry successful on attempt {attempt}")

                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt} failed: {e}")

                # Try to classify error if func has a classify_error method
                # This is a bit of a hack - in practice, the caller would
                # need to provide error classification
                provider_error = ProviderError(
                    error_class=ErrorClass.UNKNOWN,
                    message=str(e),
                    retryable=self._is_retryable_exception(e),
                    original_error=e
                )

                # Check if should retry
                if not self.should_retry(provider_error, attempt):
                    logger.error(f"Not retrying after {attempt} attempts")
                    raise last_error

                # Calculate backoff
                delay = self.get_backoff_delay(attempt)

                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)

                attempt += 1

    def _is_retryable_exception(self, error: Exception) -> bool:
        """Heuristic to determine if exception is retryable.

        Args:
            error: The exception

        Returns:
            True if likely retryable
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Network/connection errors
        if any(keyword in error_str for keyword in [
            "connection", "timeout", "network", "unreachable"
        ]):
            return True

        if any(keyword in error_type for keyword in [
            "connection", "timeout", "network"
        ]):
            return True

        # Rate limit errors
        if any(keyword in error_str for keyword in [
            "rate limit", "too many requests", "quota"
        ]):
            return True

        # Server errors (5xx)
        if any(keyword in error_str for keyword in [
            "server error", "503", "502", "500", "internal server"
        ]):
            return True

        # Default: not retryable
        return False


def create_retry_handler(
    max_retries: int = 3,
    base_backoff: float = 1.0,
    max_backoff: float = 30.0,
    exponential: bool = True
) -> RetryHandler:
    """Create a retry handler with specified configuration.

    Args:
        max_retries: Maximum number of retry attempts
        base_backoff: Base backoff delay in seconds
        max_backoff: Maximum backoff delay in seconds
        exponential: Use exponential backoff if True, fixed if False

    Returns:
        Configured RetryHandler instance
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_backoff=base_backoff,
        max_backoff=max_backoff,
        exponential=exponential,
    )
    return RetryHandler(config)
