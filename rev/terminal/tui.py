#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal curses-based UI with bottom prompt and top scrollback."""

from __future__ import annotations

import importlib.util
import threading
import queue
import time
import re
import os
import os.path
from pathlib import Path
from typing import Callable, Optional

if importlib.util.find_spec("curses") is not None:  # pragma: no cover - platform dependent
    import curses
    import curses.textpad
else:  # pragma: no cover - platform dependent
    curses = None

from rev.terminal.input import _get_command_suggestions


# Global reference to active TUI instance (for menu callbacks)
_active_tui: Optional['TUI'] = None


def _require_curses() -> None:
    if curses is None:
        raise RuntimeError(
            "The curses module is unavailable on this platform. "
            "Install a compatible curses package (e.g., windows-curses on Windows) "
            "or run without TUI mode."
        )


def get_active_tui() -> Optional['TUI']:
    """Get the currently active TUI instance, if any."""
    return _active_tui


def autocomplete_slash_command(buffer: str) -> tuple[str, list[str]]:
    """
    Return an autocompleted buffer and the list of matching commands.

    Args:
        buffer: Current input buffer.

    Returns:
        (new_buffer, matches)
        - new_buffer: updated buffer (may be unchanged)
        - matches: list of matching commands (with leading '/')
    """
    if not buffer.startswith("/"):
        return buffer, []

    commands = _get_command_suggestions()
    matches = [cmd for cmd in commands if cmd.startswith(buffer)]
    if not matches:
        return buffer, []

    # If single match, complete fully
    if len(matches) == 1:
        return matches[0] + " ", matches

    # Multiple matches: extend to common prefix
    common = os.path.commonprefix(matches)
    if len(common) > len(buffer):
        return common, matches
    return buffer, matches


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


_ANSI_RE = re.compile(r"(\x1b\[[0-?]*[ -/]*[@-~])")


def _parse_ansi(text: str) -> list[tuple[str, int]]:
    """Parse string with ANSI codes into segments with curses color pairs."""
    segments = []
    parts = _ANSI_RE.split(text)
    
    # Default color (pair 0)
    current_color = 0
    
    # Mapping of ANSI color codes to curses color pairs
    # These pairs must be initialized in _curses_main
    color_map = {
        "\x1b[30m": 8,  # Black
        "\x1b[31m": 1,  # Red
        "\x1b[32m": 2,  # Green
        "\x1b[33m": 3,  # Yellow
        "\x1b[34m": 4,  # Blue
        "\x1b[35m": 5,  # Magenta
        "\x1b[36m": 6,  # Cyan
        "\x1b[37m": 7,  # White
        "\x1b[90m": 8,  # Bright Black (Gray)
        "\x1b[91m": 9,  # Bright Red
        "\x1b[92m": 10, # Bright Green
        "\x1b[93m": 11, # Bright Yellow
        "\x1b[94m": 12, # Bright Blue
        "\x1b[95m": 13, # Bright Magenta
        "\x1b[96m": 14, # Bright Cyan
        "\x1b[97m": 15, # Bright White
        "\x1b[0m": 0,   # Reset
    }

    for part in parts:
        if not part:
            continue
        if part.startswith("\x1b["):
            # Update current color if it's a known code
            if part in color_map:
                current_color = color_map[part]
            elif part == "\x1b[1m": # Bold - we handle as attr but keeping it simple for now
                pass
        else:
            segments.append((part, current_color))
            
    return segments


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
        self._cursor_pos = 0 # Character position in input buffer
        self._scroll_pos = 0 # Horizontal scroll for input
        self._worker: Optional[threading.Thread] = None

        # Command history (last 100 commands)
        self._command_history: list[str] = []
        self._history_pos = -1  # Position in history when browsing (-1 = not browsing)
        self._history_temp = ""  # Temp storage for current input when browsing history
        self._history_file = Path.home() / ".rev" / "history"

        # Scrollback control
        self._log_scroll_offset = 0  # How many lines scrolled up from bottom

        # Curses screen reference (set when curses starts)
        self._stdscr = None

        # Load persistent history
        self._load_history()

    def log(self, text: str) -> None:
        """Queue text for append to scrollback (thread-safe)."""
        if text is None:
            return
        # Keep ANSI for parsing during render
        text = str(text).replace("\r\n", "\n").replace("\r", "\n")
        for line in text.splitlines():
            self._log_queue.put(line)

    def set_prompt(self, prompt: str) -> None:
        self.prompt = prompt

    def run(self, on_input: Callable[[str], None], *, initial_input: Optional[str] = None, on_feedback: Optional[Callable[[str], bool]] = None) -> None:
        """Start the curses UI and dispatch input lines to on_input."""
        _require_curses()
        global _active_tui
        _active_tui = self  # Set global reference

        self._on_feedback = on_feedback

        def _curses_main(stdscr):
            # Store stdscr reference for menu functionality
            self._stdscr = stdscr

            # Initialize colors
            curses.start_color()
            curses.use_default_colors()
            
            # Base colors
            curses.init_pair(1, curses.COLOR_RED, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_BLUE, -1)
            curses.init_pair(5, curses.COLOR_MAGENTA, -1)
            curses.init_pair(6, curses.COLOR_CYAN, -1)
            curses.init_pair(7, curses.COLOR_WHITE, -1)
            
            # Bright colors (if supported, otherwise fallback to base)
            # 8 is gray/bright black
            try:
                curses.init_pair(8, 244, -1) # Dark gray
                curses.init_pair(9, 196, -1) # Bright red
                curses.init_pair(10, 46, -1) # Bright green
                curses.init_pair(11, 226, -1)# Bright yellow
                curses.init_pair(12, 21, -1) # Bright blue
                curses.init_pair(13, 201, -1)# Bright magenta
                curses.init_pair(14, 51, -1) # Bright cyan
                curses.init_pair(15, 231, -1)# Bright white
            except:
                # Fallback for limited terminals
                for i in range(8, 16):
                    curses.init_pair(i, (i-8) % 7 + 1, -1)

            curses.curs_set(1)
            stdscr.nodelay(True)
            stdscr.keypad(True) # Enable special keys
            self._screen = stdscr
            self._resize_windows()
            self._render_input()
            try:
                # Lightweight command discovery hint
                commands_preview = ", ".join(_get_command_suggestions()[:8])
                self.log(f"\x1b[94m[TUI] Tab for autocomplete. Commands: {commands_preview}\x1b[0m")
            except Exception:
                pass

            if initial_input and initial_input.strip():
                # Add initial command to history
                self._command_history.append(initial_input)
                if len(self._command_history) > 100:
                    self._command_history.pop(0)

                self.log("\x1b[95m" + self.prompt + "\x1b[0m" + initial_input)
                self._start_worker(on_input, initial_input)

            while not self._stop.is_set():
                self._drain_log_queue()

                # Ensure cursor is in input window at correct position
                if self._input_win:
                    try:
                        prompt_len = len(self.prompt)
                        cursor_x = prompt_len + (self._cursor_pos - self._scroll_pos)
                        self._input_win.move(0, cursor_x)
                        self._input_win.refresh()
                    except curses.error:
                        pass

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
                    self._cursor_pos = 0
                    self._scroll_pos = 0
                    self._history_pos = -1  # Reset history browsing
                    self._render_input()

                    if line.strip():
                        # Add to command history (keep last 100)
                        self._command_history.append(line)
                        if len(self._command_history) > 100:
                            self._command_history.pop(0)

                        # Save history immediately for persistence
                        self._save_history()

                        # Log with prompt color
                        self.log("\x1b[95m" + self.prompt + "\x1b[0m" + line)

                        # Pass ALL input to the callback
                        # The REPL's _handle_input_line will process commands via execute_command()
                        self._start_worker(on_input, line)
                    continue
                if ch in (27,):  # ESC
                    self.stop()
                    break
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if self._cursor_pos > 0:
                        self._input_buffer = self._input_buffer[:self._cursor_pos-1] + self._input_buffer[self._cursor_pos:]
                        self._cursor_pos -= 1
                        self._render_input()
                    continue
                if ch == 9:  # Tab for autocomplete
                    new_buf, matches = autocomplete_slash_command(self._input_buffer[:self._cursor_pos])
                    if matches:
                        # Update buffer and move cursor to end of new buffer prefix
                        remainder = self._input_buffer[self._cursor_pos:]
                        self._input_buffer = new_buf + remainder
                        self._cursor_pos = len(new_buf)
                        self._render_input()
                        if len(matches) > 1:
                            self.log(f"\x1b[96m[TUI] Commands: {', '.join(matches)}\x1b[0m")
                    continue
                if ch == curses.KEY_DC: # Delete
                    if self._cursor_pos < len(self._input_buffer):
                        self._input_buffer = self._input_buffer[:self._cursor_pos] + self._input_buffer[self._cursor_pos+1:]
                        self._render_input()
                    continue
                if ch == curses.KEY_UP:
                    # Browse command history backward (older commands)
                    if self._command_history:
                        if self._history_pos == -1:
                            # Just started browsing - save current input
                            self._history_temp = self._input_buffer
                            self._history_pos = len(self._command_history) - 1
                        elif self._history_pos > 0:
                            self._history_pos -= 1

                        self._input_buffer = self._command_history[self._history_pos]
                        self._cursor_pos = len(self._input_buffer)
                        self._render_input()
                    continue

                if ch == curses.KEY_DOWN:
                    # Browse command history forward (newer commands)
                    if self._history_pos >= 0:
                        if self._history_pos < len(self._command_history) - 1:
                            self._history_pos += 1
                            self._input_buffer = self._command_history[self._history_pos]
                        else:
                            # Reached end - restore temp input
                            self._history_pos = -1
                            self._input_buffer = self._history_temp

                        self._cursor_pos = len(self._input_buffer)
                        self._render_input()
                    continue

                if ch == curses.KEY_PPAGE:  # Page Up
                    # Scroll log up (show older messages)
                    max_y, _ = self._log_win.getmaxyx() if self._log_win else (0, 0)
                    max_scroll = max(0, len(self.lines) - max_y)
                    self._log_scroll_offset = min(self._log_scroll_offset + max_y // 2, max_scroll)
                    self._refresh_log()
                    continue

                if ch == curses.KEY_NPAGE:  # Page Down
                    # Scroll log down (show newer messages)
                    max_y, _ = self._log_win.getmaxyx() if self._log_win else (0, 0)
                    self._log_scroll_offset = max(self._log_scroll_offset - max_y // 2, 0)
                    self._refresh_log()
                    continue

                if ch == curses.KEY_LEFT:
                    if self._cursor_pos > 0:
                        self._cursor_pos -= 1
                        self._render_input()
                    continue
                if ch == curses.KEY_RIGHT:
                    if self._cursor_pos < len(self._input_buffer):
                        self._cursor_pos += 1
                        self._render_input()
                    continue
                if ch == curses.KEY_HOME:
                    self._cursor_pos = 0
                    self._render_input()
                    continue
                if ch == curses.KEY_END:
                    self._cursor_pos = len(self._input_buffer)
                    self._render_input()
                    continue
                if ch >= 32 and ch <= 126:
                    self._input_buffer = self._input_buffer[:self._cursor_pos] + chr(ch) + self._input_buffer[self._cursor_pos:]
                    self._cursor_pos += 1
                    self._render_input()

        curses.wrapper(_curses_main)

    def show_menu(self, title: str, options: list[str]) -> int:
        """
        Display a curses menu with up/down navigation.

        Args:
            title: The menu title
            options: List of option strings

        Returns:
            The index of the selected option (0-based), or -1 if cancelled
        """
        _require_curses()
        if not hasattr(self, '_stdscr') or self._stdscr is None:
            # TUI not initialized yet, fall back to index 0
            return 0

        selected_idx = [0]  # Use list to allow modification in nested function
        done = [False]

        # Display title once
        self.log(f"\n\x1b[96m{title}\x1b[0m")

        # Calculate menu start position (track where menu begins in lines)
        menu_start_line = len(self.lines)

        # Initial menu display
        for i, option in enumerate(options):
            if i == selected_idx[0]:
                self.log(f"\x1b[7m  {option}\x1b[0m")  # Reverse video for selected
            else:
                self.log(f"  {option}")

        # Force refresh
        self._refresh_log()

        # Menu interaction loop
        while not done[0]:
            try:
                ch = self._stdscr.getch()
            except Exception:
                time.sleep(0.01)
                continue

            if ch == curses.KEY_UP and selected_idx[0] > 0:
                selected_idx[0] -= 1
                # Redraw menu options
                for i, option in enumerate(options):
                    line_idx = menu_start_line + i
                    if line_idx < len(self.lines):
                        if i == selected_idx[0]:
                            self.lines[line_idx] = f"\x1b[7m  {option}\x1b[0m"
                        else:
                            self.lines[line_idx] = f"  {option}"
                self._refresh_log()

            elif ch == curses.KEY_DOWN and selected_idx[0] < len(options) - 1:
                selected_idx[0] += 1
                # Redraw menu options
                for i, option in enumerate(options):
                    line_idx = menu_start_line + i
                    if line_idx < len(self.lines):
                        if i == selected_idx[0]:
                            self.lines[line_idx] = f"\x1b[7m  {option}\x1b[0m"
                        else:
                            self.lines[line_idx] = f"  {option}"
                self._refresh_log()

            elif ch in (curses.KEY_ENTER, 10, 13):
                # Remove menu lines
                del self.lines[menu_start_line:menu_start_line + len(options)]
                # Show selection
                self.log(f"\x1b[92m✓ Selected: {options[selected_idx[0]]}\x1b[0m\n")
                self._refresh_log()
                done[0] = True
                return selected_idx[0]

            elif ch == 27:  # ESC
                # Remove menu lines
                del self.lines[menu_start_line:menu_start_line + len(options)]
                self.log(f"\x1b[93m✗ Cancelled\x1b[0m\n")
                self._refresh_log()
                done[0] = True
                return -1

        return -1

    def stop(self) -> None:
        global _active_tui
        self._stop.set()
        # Save history on exit
        self._save_history()
        # Clear global reference
        if _active_tui is self:
            _active_tui = None

    def _load_history(self) -> None:
        """Load command history from persistent storage."""
        try:
            if self._history_file.exists():
                with open(self._history_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Load last 100 commands
                    self._command_history = [line.rstrip('\n') for line in lines[-100:]]
        except Exception:
            pass  # Silently fail if can't load history

    def _save_history(self) -> None:
        """Save command history to persistent storage."""
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, 'w', encoding='utf-8') as f:
                for cmd in self._command_history:
                    f.write(cmd + '\n')
        except Exception:
            pass  # Silently fail if can't save history

    # Internal helpers
    def _start_worker(self, on_input: Callable[[str], None], line: str) -> None:
        if self._worker and self._worker.is_alive():
            if hasattr(self, "_on_feedback") and self._on_feedback:
                if self._on_feedback(line):
                    self.log("\x1b[92m[TUI] Feedback sent to active task\x1b[0m")
                    return
            self.log("\x1b[93m[TUI] Busy (previous command still running)\x1b[0m")
            return

        def _run():
            try:
                on_input(line)
            except SystemExit:
                self.stop()
            except Exception as e:
                self.log(f"\x1b[91m[TUI ERROR] {e}\x1b[0m")

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
            # Reset scroll to bottom when new content arrives
            self._log_scroll_offset = 0
            self._refresh_log()

    def _resize_windows(self) -> None:
        if not self._screen:
            return
        max_y, max_x = self._screen.getmaxyx()
        input_height = 1
        log_height = max_y - 2 # One line for separator, one for input
        
        self._log_win = curses.newwin(log_height, max_x, 0, 0)
        self._log_win.scrollok(True)
        
        # Render separator
        self._screen.attron(curses.color_pair(8))
        self._screen.hline(log_height, 0, ord('━'), max_x)
        self._screen.attroff(curses.color_pair(8))
        self._screen.refresh()
        
        self._input_win = curses.newwin(input_height, max_x, log_height + 1, 0)
        self._input_win.nodelay(True)

    def _refresh_log(self) -> None:
        if not self._log_win:
            return
        self._log_win.erase()
        max_y, max_x = self._log_win.getmaxyx()

        # Calculate start position based on scroll offset
        # If scrolled up, show older messages; otherwise show newest
        end_pos = len(self.lines) - self._log_scroll_offset
        start = max(0, end_pos - max_y)

        for idx, line in enumerate(self.lines[start:end_pos]):
            segments = _parse_ansi(line)
            x = 0
            for text, color_pair in segments:
                try:
                    if x < max_x - 1:
                        self._log_win.addnstr(idx, x, text, max_x - x - 1, curses.color_pair(color_pair))
                        x += len(text)
                except curses.error:
                    pass

        # Show scroll indicator if not at bottom
        if self._log_scroll_offset > 0:
            try:
                indicator = f" ▲ -{self._log_scroll_offset} lines "
                self._log_win.addstr(max_y - 1, max_x - len(indicator) - 1, indicator,
                                   curses.color_pair(3) | curses.A_REVERSE)
            except curses.error:
                pass

        self._log_win.refresh()

    def _render_input(self) -> None:
        if not self._input_win:
            return
        self._input_win.erase()
        max_y, max_x = self._input_win.getmaxyx()
        
        # Prompt in magenta
        prompt = self.prompt
        self._input_win.attron(curses.color_pair(13) | curses.A_BOLD)
        self._input_win.addstr(0, 0, prompt)
        self._input_win.attroff(curses.color_pair(13) | curses.A_BOLD)
        
        # Calculate available width for buffer
        avail_width = max_x - len(prompt) - 1
        
        # Adjust scroll_pos to keep cursor in view
        if self._cursor_pos < self._scroll_pos:
            self._scroll_pos = self._cursor_pos
        elif self._cursor_pos >= self._scroll_pos + avail_width:
            self._scroll_pos = self._cursor_pos - avail_width + 1
            
        buf = self._input_buffer[self._scroll_pos : self._scroll_pos + avail_width]
        try:
            self._input_win.addstr(0, len(prompt), buf)
            # Position cursor relative to prompt and scroll
            cursor_x = len(prompt) + (self._cursor_pos - self._scroll_pos)
            self._input_win.move(0, cursor_x)
        except curses.error:
            pass
        self._input_win.refresh()
