#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal curses-based UI with bottom prompt and top scrollback."""

from __future__ import annotations

import curses
import curses.textpad
import threading
import queue
import time
from typing import Callable, Optional


class TUI:
    """Curses wrapper with scrollback and bottom prompt."""

    def __init__(self, prompt: str = "rev> "):
        self.prompt = prompt
        self.lines: list[str] = []
        self.input_queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._screen = None
        self._input_win = None
        self._log_win = None
        self._input_buffer = ""

    def log(self, text: str) -> None:
        """Append text to scrollback and refresh."""
        for line in (text or "").splitlines():
            self.lines.append(line)
        self._refresh_log()

    def run(self, on_input: Callable[[str], None]) -> None:
        """Start the curses UI and dispatch input lines to on_input."""

        def _curses_main(stdscr):
            curses.curs_set(1)
            stdscr.nodelay(True)
            self._screen = stdscr
            self._resize_windows()
            self._render_input()

            while not self._stop.is_set():
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
                        on_input(line)
                    continue
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
            self._log_win.addnstr(idx, 0, line, max_x - 1)
        self._log_win.refresh()

    def _render_input(self) -> None:
        if not self._input_win:
            return
        self._input_win.erase()
        max_y, max_x = self._input_win.getmaxyx()
        prompt = self.prompt
        buf = self._input_buffer
        self._input_win.addnstr(0, 0, prompt + buf, max_x - 1)
        self._input_win.move(0, min(len(prompt + buf), max_x - 1))
        self._input_win.refresh()

