#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Always-on run log for rev sessions.

This is intentionally separate from DebugLogger (--debug):
- DebugLogger captures structured events for LLM review.
- RunLog captures the human-facing stdout/stderr stream so failures are visible later.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from rev import config
from rev.debug_logger import prune_old_logs

_RUN_LOG_PATH: Optional[Path] = None
_RUN_LOG_HANDLE: Optional[TextIO] = None


@dataclass
class TeeStream:
    primary: TextIO
    secondary: TextIO

    def write(self, data: str) -> int:
        n = 0
        try:
            n = self.primary.write(data)
        except Exception:
            pass
        try:
            self.secondary.write(data)
        except Exception:
            pass
        return n

    def flush(self) -> None:
        try:
            self.primary.flush()
        except Exception:
            pass
        try:
            self.secondary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(getattr(self.primary, "isatty")())
        except Exception:
            return False


def get_run_log_path() -> Optional[Path]:
    return _RUN_LOG_PATH


def write_run_log_line(line: str) -> None:
    """Write a single line to the run log without affecting stdout."""
    if _RUN_LOG_HANDLE is None:
        return
    try:
        _RUN_LOG_HANDLE.write(str(line) + "\n")
        _RUN_LOG_HANDLE.flush()
    except Exception:
        return


def wrap_stream(stream: TextIO) -> TextIO:
    """Wrap a stream so writes also go to the run log (if enabled)."""
    if _RUN_LOG_HANDLE is None:
        return stream
    return TeeStream(primary=stream, secondary=_RUN_LOG_HANDLE)  # type: ignore[return-value]


def start_run_log() -> Optional[Path]:
    """Start an always-on run log and tee stdout/stderr into it."""
    global _RUN_LOG_PATH, _RUN_LOG_HANDLE

    env = os.getenv("REV_LOG_ALWAYS", "").lower()
    if env in {"0", "false", "no", "off"}:
        return None

    if _RUN_LOG_HANDLE is not None:
        return _RUN_LOG_PATH

    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _RUN_LOG_PATH = config.LOGS_DIR / f"rev_run_{ts}.log"
        _RUN_LOG_HANDLE = _RUN_LOG_PATH.open("w", encoding="utf-8", errors="replace")
        prune_old_logs(config.LOGS_DIR, config.LOG_RETENTION_LIMIT)

        sys.stdout = wrap_stream(sys.stdout)  # type: ignore[assignment]
        sys.stderr = wrap_stream(sys.stderr)  # type: ignore[assignment]
        return _RUN_LOG_PATH
    except Exception:
        _RUN_LOG_PATH = None
        _RUN_LOG_HANDLE = None
        return None

