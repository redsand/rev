#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal input handling with escape key detection.

Provides cross-platform support for:
- Unix/Linux/macOS: Uses termios and tty for raw mode input
- Windows: Uses msvcrt for console input
- Escape key detection for immediate submission

Features:
- Arrow key navigation (left/right)
- History navigation (up/down)
- Escape key for immediate submission
"""

import sys
import platform
import threading
import time
from typing import List, Tuple
from rev.terminal.history import PromptHistory

from rev.config import set_escape_interrupt
from rev.settings_manager import get_runtime_settings_snapshot
from rev.terminal.commands import COMMAND_HANDLERS

# Global history instance
_history = PromptHistory()


def _get_command_suggestions() -> List[str]:
    """Return sorted list of available slash commands with leading slash."""

    unique_commands = {handler.name for handler in COMMAND_HANDLERS.values()}
    return sorted(f"/{cmd}" for cmd in unique_commands)


def _get_tab_suggestions(text: str) -> List[str]:
    """Build tab-completion suggestions based on current input text."""

    if not text.startswith('/'):
        return []

    stripped = text[1:]
    parts = stripped.split()

    # Suggest commands when only "/" or partial command is present
    command_list = _get_command_suggestions()
    if not parts or (len(parts) == 1 and stripped and ' ' not in stripped and not stripped.endswith(' ')):
        prefix = parts[0] if parts else ""
        return [cmd for cmd in command_list if cmd.startswith(f"/{prefix}")]

    # Suggest /set keys when applicable
    if parts[0] == "set":
        key_prefix = parts[1] if len(parts) > 1 else ""
        return [
            key
            for key in sorted(get_runtime_settings_snapshot().keys())
            if key.startswith(key_prefix)
        ]

    return []


def _render_prompt(prompt: str, buffer: List[str], cursor_pos: int) -> None:
    """Redraw prompt and buffer while keeping cursor position consistent."""

    sys.stdout.write("\r" + prompt + ''.join(buffer))
    if cursor_pos < len(buffer):
        sys.stdout.write('\x1b[' + str(len(buffer) - cursor_pos) + 'D')
    sys.stdout.flush()


def _handle_tab_completion(prompt: str, buffer: List[str], cursor_pos: int) -> int:
    """Render tab-completion suggestions and re-draw the current prompt."""

    buffer_prefix = ''.join(buffer[:cursor_pos])
    suggestions = _get_tab_suggestions(buffer_prefix)

    if not suggestions:
        return cursor_pos

    sys.stdout.write("\n" + "  ".join(suggestions) + "\n")
    _render_prompt(prompt, buffer, cursor_pos)
    return cursor_pos

def get_history() -> PromptHistory:
    """Get the global history instance."""
    return _history

# Platform-specific imports
if platform.system() != "Windows":
    # Unix/Linux/macOS terminal handling
    import termios
    import tty
    import select
else:
    # Windows terminal handling
    import msvcrt


def _get_input_unix(prompt: str) -> Tuple[str, bool]:
    """Unix/Linux/macOS implementation of input with escape key detection."""
    # Display prompt
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()

    # Save terminal settings
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    buffer = []
    cursor_pos = 0
    navigating_history = False
    is_command = prompt.strip().endswith('/')  # Simple heuristic for command mode
    escape_pressed = False

    try:
        # Set terminal to raw mode
        tty.setraw(fd)

        while True:
            # Read one character
            char = sys.stdin.read(1)
            
            # Reset navigation state on any non-arrow key input
            if navigating_history and char not in ('\x1b', '[', 'A', 'B', 'C', 'D'):
                navigating_history = False
                _history.start_navigation(is_command, ''.join(buffer))

            # Check for ESC key
            if char == '\x1b':  # ESC key
                # Check if it's an escape sequence (arrow keys, etc.) or just ESC
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    # It's an escape sequence, read the rest
                    next_chars = sys.stdin.read(2)

                    if next_chars == '[D':  # Left arrow
                        if cursor_pos > 0:
                            cursor_pos -= 1
                            navigating_history = False
                            sys.stdout.write('\x1b[D')
                            sys.stdout.flush()
                    elif next_chars == '[C':  # Right arrow
                        if cursor_pos < len(buffer):
                            cursor_pos += 1
                            navigating_history = False
                            sys.stdout.write('\x1b[C')
                            sys.stdout.flush()
                    elif next_chars == '[A':  # Up arrow
                        if not navigating_history:
                            _history.start_navigation(is_command, ''.join(buffer))
                            navigating_history = True
                        
                        previous = _history.get_previous()
                        if previous is not None:
                            # Clear current line
                            sys.stdout.write('\r' + ' ' * (len(prompt) + len(buffer)) + '\r' + prompt)
                            # Write previous entry
                            buffer = list(previous)
                            cursor_pos = len(buffer)
                            sys.stdout.write(previous)
                            sys.stdout.flush()
                    elif next_chars == '[B':  # Down arrow
                        if navigating_history:
                            next_entry = _history.get_next()
                            # Clear current line
                            sys.stdout.write('\r' + ' ' * (len(prompt) + len(buffer)) + '\r' + prompt)
                            
                            if next_entry is not None:
                                buffer = list(next_entry)
                                cursor_pos = len(buffer)
                                sys.stdout.write(next_entry)
                            else:
                                buffer = []
                                cursor_pos = 0
                            sys.stdout.flush()
                else:
                    # Just ESC key pressed alone - clear the current input
                    buffer = []
                    cursor_pos = 0
                    navigating_history = False
                    escape_pressed = True
                    set_escape_interrupt(True)
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    break

            elif char == '\t':  # Tab key for command completion
                navigating_history = False
                cursor_pos = _handle_tab_completion(prompt, buffer, cursor_pos)
                continue

            elif char == '\r':  # Carriage return (Enter key)
                sys.stdout.write('\n')
                sys.stdout.flush()
                break

            elif char == '\n':  # Line feed - allow in multi-line paste, but also can submit
                # Allow newlines in the buffer for multi-line paste support
                # The next Enter (carriage return) will submit the full multi-line input
                buffer.insert(cursor_pos, '\n')
                cursor_pos += 1
                navigating_history = False

                # Display newline and continuation prompt
                sys.stdout.write('\n')
                if prompt:
                    sys.stdout.write('...')  # Continuation prompt
                sys.stdout.flush()

            elif char == '\x7f' or char == '\x08':  # Backspace/Delete
                if cursor_pos > 0:
                    # Remove character at cursor position
                    buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1

                    # Redraw line
                    sys.stdout.write('\x1b[D')  # Move cursor left
                    sys.stdout.write(''.join(buffer[cursor_pos:]) + ' ')  # Redraw rest of line
                    sys.stdout.write('\x1b[' + str(len(buffer) - cursor_pos + 1) + 'D')  # Move cursor back
                    sys.stdout.flush()

            elif char == '\x03':  # Ctrl+C
                raise KeyboardInterrupt

            elif char == '\x04':  # Ctrl+D (EOF)
                if not buffer:
                    raise EOFError

            elif ord(char) >= 32:  # Printable characters
                # Insert character at cursor position
                buffer.insert(cursor_pos, char)
                cursor_pos += 1
                navigating_history = False

                # Redraw from cursor position
                sys.stdout.write(''.join(buffer[cursor_pos-1:]))
                if cursor_pos < len(buffer):
                    # Move cursor back to correct position
                    sys.stdout.write('\x1b[' + str(len(buffer) - cursor_pos) + 'D')
                sys.stdout.flush()
            else:
                navigating_history = False

    finally:
        # Restore terminal settings
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    result = ''.join(buffer)
    return result, escape_pressed

    # Note: History addition is handled by the caller (REPL) to properly
    # distinguish between commands and regular input based on context
    # that's not available at this level

def _get_input_windows(prompt: str) -> Tuple[str, bool]:
    """Windows implementation of input with escape key detection."""
    # Display prompt
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()

    buffer = []
    cursor_pos = 0
    escape_pressed = False
    navigating_history = False
    is_command = prompt.strip().endswith('/')  # Simple heuristic for command mode
    pending_char = None

    def _insert_newline() -> None:
        """Insert a newline into the buffer and render continuation prompt."""
        nonlocal cursor_pos, navigating_history
        buffer.insert(cursor_pos, '\n')
        cursor_pos += 1
        navigating_history = False

        sys.stdout.write('\n')
        if prompt:
            sys.stdout.write('...')
        sys.stdout.flush()

    try:
        while True:
            # Read one character (blocking)
            char = pending_char if pending_char is not None else msvcrt.getch()
            pending_char = None

            # Handle extended keys (arrow keys, etc.)
            if char in (b'\x00', b'\xe0'):
                # Extended key - read the next byte
                extended = msvcrt.getch()
                
                # Handle arrow keys
                if extended == b'K':  # Left arrow
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        navigating_history = False
                        sys.stdout.write('\x1b[D')
                        sys.stdout.flush()
                elif extended == b'M':  # Right arrow
                    if cursor_pos < len(buffer):
                        cursor_pos += 1
                        navigating_history = False
                        sys.stdout.write('\x1b[C')
                        sys.stdout.flush()
                elif extended == b'H':  # Up arrow
                    if not navigating_history:
                        _history.start_navigation(is_command, ''.join(buffer))
                        navigating_history = True
                    
                    previous = _history.get_previous()
                    if previous is not None:
                        # Clear current line
                        sys.stdout.write('\r' + ' ' * (len(prompt) + len(buffer)) + '\r' + prompt)
                        # Write previous entry
                        buffer = list(previous)
                        cursor_pos = len(buffer)
                        sys.stdout.write(previous)
                        sys.stdout.flush()
                elif extended == b'P':  # Down arrow
                    if navigating_history:
                        next_entry = _history.get_next()
                        # Clear current line
                        sys.stdout.write('\r' + ' ' * (len(prompt) + len(buffer)) + '\r' + prompt)
                        
                        if next_entry is not None:
                            buffer = list(next_entry)
                            cursor_pos = len(buffer)
                            sys.stdout.write(next_entry)
                        else:
                            buffer = []
                            cursor_pos = 0
                        sys.stdout.flush()
                continue
                
            # Reset navigation state on any non-arrow key input
            if navigating_history and char not in (b'\x00', b'\xe0'):
                navigating_history = False
                _history.start_navigation(is_command, ''.join(buffer))

            # Check for ESC key
            if char == b'\x1b':
                # Just ESC key pressed - clear the current input
                buffer = []
                cursor_pos = 0
                navigating_history = False
                escape_pressed = True
                set_escape_interrupt(True)
                sys.stdout.write('\n')
                sys.stdout.flush()
                break

            elif char == b'\t':
                navigating_history = False
                cursor_pos = _handle_tab_completion(prompt, buffer, cursor_pos)
                continue

            # Enter key
            elif char == b'\r':
                # Detect pasted newlines by checking for buffered characters
                if msvcrt.kbhit():
                    next_char = msvcrt.getch()
                    _insert_newline()
                    if next_char != b'\n':
                        pending_char = next_char
                    continue

                sys.stdout.write('\n')
                sys.stdout.flush()
                break

            # Line feed (e.g., from pasted text)
            elif char == b'\n':
                _insert_newline()
                continue

            # Backspace
            elif char == b'\x08':
                if cursor_pos > 0:
                    # Remove character at cursor position
                    buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1

                    # Redraw line
                    sys.stdout.write('\x1b[D')  # Move cursor left
                    sys.stdout.write(''.join(buffer[cursor_pos:]) + ' ')  # Redraw rest of line
                    sys.stdout.write('\x1b[' + str(len(buffer) - cursor_pos + 1) + 'D')  # Move cursor back
                    sys.stdout.flush()

            # Ctrl+C
            elif char == b'\x03':
                raise KeyboardInterrupt

            # Ctrl+D (EOF)
            elif char == b'\x04':
                if not buffer:
                    raise EOFError

            # Printable characters
            else:
                try:
                    # Decode the character
                    char_str = char.decode('utf-8', errors='ignore')
                    if char_str and ord(char_str) >= 32:
                        # Insert character at cursor position
                        buffer.insert(cursor_pos, char_str)
                        cursor_pos += 1

                        # Redraw from cursor position
                        sys.stdout.write(''.join(buffer[cursor_pos-1:]))
                        if cursor_pos < len(buffer):
                            # Move cursor back to correct position
                            sys.stdout.write('\x1b[' + str(len(buffer) - cursor_pos) + 'D')
                        sys.stdout.flush()
                except (UnicodeDecodeError, ValueError):
                    # Skip characters that can't be decoded
                    pass

    except Exception:
        raise

    result = ''.join(buffer)
    return result, escape_pressed

    # Note: History addition is handled by the caller (REPL) to properly
    # distinguish between commands and regular input based on context
    # that's not available at this level

def get_input_with_escape(prompt: str = "") -> Tuple[str, bool]:
    """
    Get user input with escape key detection.

    Cross-platform implementation supporting both Unix/Linux/macOS and Windows.

    Args:
        prompt: The prompt string to display to the user

    Returns:
        tuple: (input_string, escape_pressed)
            - input_string: The text entered by user
            - escape_pressed: True if ESC was pressed to submit, False if Enter was pressed
    """
    # Check if we're in a TTY (terminal)
    if not sys.stdin.isatty():
        # Non‑interactive environments: still use platform‑specific input handling
        if platform.system() == "Windows":
            return _get_input_windows(prompt)
        else:
            return _get_input_unix(prompt)

    # Use platform-specific implementation
    if platform.system() == "Windows":
        return _get_input_windows(prompt)
    else:
        return _get_input_unix(prompt)


# =============================================================================
# Streaming Input Handler - For real-time input during task execution
# =============================================================================

class StreamingInputHandler:
    """Handles non-blocking input during streaming task execution.

    This enables the Claude Code-like experience where users can type
    messages while the LLM is generating responses. The input is captured
    in a background thread and queued for injection into the conversation.
    """

    def __init__(self, on_message: callable = None, prompt: str = ""):
        """Initialize the streaming input handler.

        Args:
            on_message: Callback called with each complete message
            prompt: Prompt to display when ready for input
        """
        self._on_message = on_message
        self._prompt = prompt
        self._thread = None
        self._running = False
        self._buffer = []
        self._lock = threading.Lock()
        self._input_ready = threading.Event()
        self._prompt_displayed = False
        self._use_stdio_reader = False

    def start(self):
        """Start the background input handler."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._input_loop, daemon=True)
        self._thread.start()

        if platform.system() == "Windows":
            self._use_stdio_reader = not _stdin_is_windows_console()

        # Display initial prompt if configured
        if self._prompt:
            sys.stdout.write(f"\n{self._prompt}")
            sys.stdout.flush()
            self._prompt_displayed = True

    def stop(self):
        """Stop the background input handler."""
        self._running = False
        if self._thread:
            # If we are using blocking stdin.readline(), the thread may not be able to
            # exit promptly. Avoid hanging the caller while still allowing the daemon
            # thread to exit on process termination.
            timeout = 0.0 if self._use_stdio_reader else 0.5
            self._thread.join(timeout=timeout)
            self._thread = None

    def _input_loop(self):
        """Background loop for reading user input during streaming."""
        while self._running:
            try:
                if platform.system() != "Windows":
                    self._input_loop_unix()
                else:
                    if self._use_stdio_reader:
                        self._input_loop_windows_stdio()
                    else:
                        self._input_loop_windows()
            except Exception:
                # Don't crash on input errors
                time.sleep(0.1)

    def _input_loop_unix(self):
        """Unix implementation of non-blocking input loop."""
        import select as sel

        # Check if input is available (non-blocking)
        ready, _, _ = sel.select([sys.stdin], [], [], 0.1)
        if ready:
            try:
                # Read available input
                line = sys.stdin.readline()
                if line:
                    self._process_input(line.rstrip('\n\r'))
            except Exception:
                pass

    def _input_loop_windows(self):
        """Windows implementation of non-blocking input loop."""
        import time as t
        try:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                with self._lock:
                    if char == '\r' or char == '\n':
                        # Enter pressed - submit the buffer
                        if self._buffer:
                            line = ''.join(self._buffer)
                            self._buffer = []
                            sys.stdout.write('\n')
                            sys.stdout.flush()
                            self._process_input(line)
                            # Re-display prompt after processing
                            if self._prompt and sys.stdout.isatty():
                                sys.stdout.write(f"{self._prompt}")
                                sys.stdout.flush()
                    elif char == '\x1b':
                        # ESC pressed - clear buffer and signal interrupt
                        self._buffer = []
                        sys.stdout.write('\n')
                        sys.stdout.flush()
                        self._process_input('/stop')
                        # Re-display prompt after processing
                        if self._prompt and sys.stdout.isatty():
                            sys.stdout.write(f"{self._prompt}")
                            sys.stdout.flush()
                    elif char == '\x08':
                        # Backspace
                        if self._buffer:
                            self._buffer.pop()
                            # Echo backspace to terminal
                            sys.stdout.write('\b \b')
                            sys.stdout.flush()
                    elif char == '\x03':
                        # Ctrl+C
                        self._running = False
                    elif ord(char) >= 32:
                        self._buffer.append(char)
                        # Echo character to terminal
                        sys.stdout.write(char)
                        sys.stdout.flush()
            else:
                t.sleep(0.05)  # Brief sleep to avoid busy-waiting
        except Exception:
            t.sleep(0.1)

    def _input_loop_windows_stdio(self):
        """Windows fallback for PTY environments where msvcrt input is unavailable."""
        try:
            line = sys.stdin.readline()
        except Exception:
            time.sleep(0.1)
            return

        if not line:
            time.sleep(0.1)
            return

        self._process_input(line.rstrip("\n\r"))

        if self._prompt:
            sys.stdout.write(f"{self._prompt}")
            sys.stdout.flush()

    def _process_input(self, text: str):
        """Process a complete line of user input."""
        if not text:
            return

        if self._on_message:
            self._on_message(text)

    def is_running(self) -> bool:
        """Check if the input handler is running."""
        return self._running

    def redisplay_prompt(self):
        """Re-display the prompt (useful after LLM output).

        This can be called from the main thread to show the prompt
        after the LLM has finished generating a response.
        """
        if self._prompt and self._running:
            with self._lock:
                if not self._buffer:
                    sys.stdout.write(f"\n{self._prompt}")
                else:
                    sys.stdout.write(f"\n{self._prompt}{''.join(self._buffer)}")
                sys.stdout.flush()


def _stdin_is_windows_console() -> bool:
    """Return True if stdin is a real Windows console (not a PTY/pipe)."""
    if platform.system() != "Windows":
        return False

    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:
        return False


# Global streaming input handler
_streaming_handler: StreamingInputHandler = None


def start_streaming_input(on_message: callable, prompt: str = "") -> StreamingInputHandler:
    """Start the streaming input handler.

    Args:
        on_message: Callback called with each complete message
        prompt: Prompt to display when ready for input

    Returns:
        The StreamingInputHandler instance
    """
    global _streaming_handler

    if _streaming_handler and _streaming_handler.is_running():
        _streaming_handler.stop()

    _streaming_handler = StreamingInputHandler(on_message=on_message, prompt=prompt)
    _streaming_handler.start()
    return _streaming_handler


def stop_streaming_input():
    """Stop the streaming input handler."""
    global _streaming_handler

    if _streaming_handler:
        _streaming_handler.stop()
        _streaming_handler = None


def get_streaming_handler() -> StreamingInputHandler:
    """Get the current streaming input handler."""
    return _streaming_handler
