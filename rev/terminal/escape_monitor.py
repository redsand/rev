#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background ESC key monitoring for responsive interruption.

This module provides a background thread that continuously monitors for ESC key
presses and sets the interrupt flag, making ESC interruption responsive even
during long-running operations.
"""

import sys
import threading
import time
from typing import Optional

from rev.config import set_escape_interrupt, get_escape_interrupt


class EscapeKeyMonitor:
    """Background monitor for ESC key presses."""

    def __init__(self, check_interval: float = 0.1):
        """Initialize the escape key monitor.

        Args:
            check_interval: How often to check for ESC key (seconds)
        """
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the background monitoring thread."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background monitoring thread."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _monitor_loop(self):
        """Main monitoring loop (runs in background thread)."""
        try:
            # Only monitor on systems with stdin
            if not sys.stdin.isatty():
                return

            while self._running and not self._stop_event.is_set():
                # Check if ESC was already set by the input handler
                if get_escape_interrupt():
                    # Already set, no need to keep checking
                    time.sleep(self.check_interval)
                    continue

                # On Unix-like systems, we can use select for non-blocking input
                try:
                    import select
                    # Check if input is available (non-blocking)
                    ready, _, _ = select.select([sys.stdin], [], [], self.check_interval)

                    if ready:
                        # Read the character
                        char = sys.stdin.read(1)

                        # Check if it's ESC key (ASCII 27)
                        if char == '\x1b':
                            set_escape_interrupt(True)
                            print("\n  ESC detected - interrupting execution...")

                except (ImportError, OSError):
                    # select not available (Windows) or stdin not available
                    # Fall back to simple polling
                    time.sleep(self.check_interval)

        except Exception as e:
            # Silently handle any errors in background thread
            pass

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


# Global instance for easy access
_global_monitor: Optional[EscapeKeyMonitor] = None
_monitor_lock = threading.Lock()


def start_escape_monitoring(check_interval: float = 0.1):
    """Start global escape key monitoring.

    Args:
        check_interval: How often to check for ESC key (seconds)
    """
    global _global_monitor

    with _monitor_lock:
        if _global_monitor is None:
            _global_monitor = EscapeKeyMonitor(check_interval)

        _global_monitor.start()


def stop_escape_monitoring():
    """Stop global escape key monitoring."""
    global _global_monitor

    with _monitor_lock:
        if _global_monitor is not None:
            _global_monitor.stop()


def escape_monitor_context(check_interval: float = 0.1):
    """Create a context manager for escape monitoring.

    Usage:
        with escape_monitor_context():
            # Long-running operation
            # ESC will be detected in background
            do_work()

    Args:
        check_interval: How often to check for ESC key (seconds)

    Returns:
        Context manager
    """
    return EscapeKeyMonitor(check_interval)
