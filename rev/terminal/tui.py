#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal curses-based UI with bottom prompt and top scrollback."""

from __future__ import annotations

import curses
import curses.textpad
import threading
import queue
import time
import re
from typing import Callable, Optional


class TuiStream:
    """File-like stream that routes writes to a TUI log callback."""

    def __init__(self, write_cb: Callable[[str], None]):
        self.write_cb = write_cb

    def write(self, data: str) -> int:
        if not data:
            return 0
        for line in data.splitlines():
            self.write_cb(line)
        if data.endswith("\n"):
            # Preserve trailing newline as empty line
            self.write_cb("")
        return len(data)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    if not text:
        return ""
    return _ANSI_RE.sub("", text)


class TUI:
    """Curses wrapper with scrollback and bottom prompt."""

    def __init__(self, prompt: str = "rev> "):
        self.prompt = prompt
        self.lines: list[str] = []
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._screen = None
        self._input_win = None
        self._log_win = None
        self._input_buffer = ""
        self._worker: Optional[threading.Thread] = None

    def log(self, text: str) -> None:
        """Queue text for append to scrollback (thread-safe)."""
        if text is None:
            return
        # Curses cannot render ANSI escape sequences; strip them.
        text = _strip_ansi(str(text)).replace("\r\n", "\n").replace("\r", "\n")
        for line in text.splitlines():
            self._log_queue.put(line)

    def set_prompt(self, prompt: str) -> None:
        self.prompt = prompt

    def run(self, on_input: Callable[[str], None], *, initial_input: Optional[str] = None) -> None:
        """Start the curses UI and dispatch input lines to on_input."""

        def _curses_main(stdscr):
            curses.curs_set(1)
            stdscr.nodelay(True)
            self._screen = stdscr
            self._resize_windows()
            self._render_input()

            if initial_input and initial_input.strip():
                self.log(self.prompt + initial_input)
                self._start_worker(on_input, initial_input)

            while not self._stop.is_set():
                self._drain_log_queue()

                try:
                    ch = stdscr.getch()
                except Exception:
                    ch = -1

                if ch == -1:
                    time.sleep(0.01)
                    continue
                if ch in (curses.KEY_RESIZE,):
                    self._resize_windows()
                    self._refresh_log()
                    self._render_input()
                    continue
                if ch in (curses.KEY_ENTER, 10, 13):
                    line = self._input_buffer
                    self._input_buffer = ""
                    self._render_input()
                    if line.strip():
                        self.log(self.prompt + line)
                        self._start_worker(on_input, line)
                    continue
                if ch in (27,):  # ESC
                    self.stop()
                    break
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    self._input_buffer = self._input_buffer[:-1]
                    self._render_input()
                    continue
                if ch >= 32:
                    self._input_buffer += chr(ch)
                    self._render_input()

        curses.wrapper(_curses_main)

    def stop(self) -> None:
        self._stop.set()

    # Internal helpers
    def _start_worker(self, on_input: Callable[[str], None], line: str) -> None:
        if self._worker and self._worker.is_alive():
            self.log("[TUI] Busy (previous command still running)")
            return

        def _run():
            self.log("[running]")
            try:
                on_input(line)
            except SystemExit:
                self.stop()
            except Exception as e:
                self.log(f"[TUI ERROR] {e}")
            finally:
                self.log("[done]")

        self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def _drain_log_queue(self) -> None:
        changed = False
        try:
            while True:
                line = self._log_queue.get_nowait()
                self.lines.append(line)
                changed = True
        except queue.Empty:
            pass
        if changed:
            self._refresh_log()

    def _resize_windows(self) -> None:
        if not self._screen:
            return
        max_y, max_x = self._screen.getmaxyx()
        input_height = 1
        log_height = max_y - input_height
        self._log_win = curses.newwin(log_height, max_x, 0, 0)
        self._log_win.scrollok(True)
        self._input_win = curses.newwin(input_height, max_x, log_height, 0)
        self._input_win.nodelay(True)

    def _refresh_log(self) -> None:
        if not self._log_win:
            return
        self._log_win.erase()
        max_y, max_x = self._log_win.getmaxyx()
        start = max(0, len(self.lines) - max_y)
        for idx, line in enumerate(self.lines[start:]):
            try:
                self._log_win.addnstr(idx, 0, line, max_x - 1)
            except curses.error:
                # Window may be too small; ignore render errors.
                pass
        self._log_win.refresh()

    def _render_input(self) -> None:
        if not self._input_win:
            return
        self._input_win.erase()
        max_y, max_x = self._input_win.getmaxyx()
        prompt = self.prompt
        buf = self._input_buffer
        try:
            self._input_win.addnstr(0, 0, prompt + buf, max_x - 1)
            self._input_win.move(0, min(len(prompt + buf), max_x - 1))
        except curses.error:
            pass
        self._input_win.refresh()
