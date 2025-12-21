from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Any, TypeVar, Tuple

from rev.config import get_escape_interrupt, set_escape_interrupt, EscapeInterrupt

# Generic return type for functions wrapped by the manager
T = TypeVar("T")

@dataclass
class TimeoutConfig:
    """Configuration for retry and timeout behavior."""
    max_attempts: int = 8
    base_backoff_ms: float = 250
    max_backoff_ms: float = 5000
    jitter_fraction: float = 1.0  # Full jitter by default

    @classmethod
    def from_env(cls) -> "TimeoutConfig":
        """Create a config from environment variables."""
        return cls(
            max_attempts=int(os.getenv("REV_TOOL_MAX_ATTEMPTS", "8")),
            base_backoff_ms=float(os.getenv("REV_TOOL_BASE_BACKOFF_MS", "250")),
            max_backoff_ms=float(os.getenv("REV_TOOL_MAX_BACKOFF_MS", "5000")),
            jitter_fraction=float(os.getenv("REV_TOOL_JITTER_FRACTION", "1.0")),
        )

def _is_transient_error(e: Exception) -> bool:
    """Check if an exception represents a likely transient network error."""
    msg = str(e).lower()
    return any(
        err_str in msg for err_str in [
            "connection reset",
            "connection refused",
            "connection aborted",
            "timeout",
            "timed out",
            "service unavailable",
            "502", "503", "504", # Bad Gateway, Service Unavailable, Gateway Timeout
        ]
    )

class TimeoutManager:
    """Manages timeouts and retries for tool executions."""

    def __init__(self, config: TimeoutConfig):
        self.config = config

    def execute_with_retry(
        self,
        func: Callable[..., T],
        log_prefix: str,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute a function with retries on transient errors.

        Args:
            func: The function to execute.
            log_prefix: Prefix for log messages.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the function.

        Raises:
            Exception: If max attempts are exhausted or a non-transient error occurs.
        """
        for attempt in range(1, self.config.max_attempts + 1):
            if get_escape_interrupt():
                set_escape_interrupt(False)
                raise EscapeInterrupt("Interrupted during tool execution retry loop")

            try:
                return func(*args, **kwargs)
            except Exception as e:
                is_transient = _is_transient_error(e)
                if not is_transient:
                    # Non-transient error, re-raise immediately
                    raise

                if attempt >= self.config.max_attempts:
                    print(f"  [tool-io] {log_prefix}: Max retries ({self.config.max_attempts}) exhausted. Final error: {e}")
                    raise

                backoff_ms, jitter_ms = self._get_next_backoff(attempt)
                print(
                    f"  [tool-io] {log_prefix}: Transient error (attempt {attempt}/{self.config.max_attempts}): {e}. "
                    f"Retrying in {backoff_ms + jitter_ms:.0f}ms..."
                )
                time.sleep((backoff_ms + jitter_ms) / 1000.0)
        
        # This line should not be reachable due to the raises above
        raise RuntimeError("Max retries exhausted")

    def _get_next_backoff(self, attempt: int) -> Tuple[float, float]:
        """Calculate exponential backoff with full jitter."""
        # Exponential backoff
        backoff = self.config.base_backoff_ms * (2 ** (attempt - 1))
        
        # Cap the backoff
        backoff = min(backoff, self.config.max_backoff_ms)

        # Apply jitter
        jitter = random.uniform(0, backoff * self.config.jitter_fraction)

        return backoff, jitter