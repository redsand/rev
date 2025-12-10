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
from typing import Tuple
from rev.terminal.history import PromptHistory

from rev.config import get_escape_interrupt, set_escape_interrupt

# Global history instance
_history = PromptHistory()

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
                    # Just ESC key pressed alone - submit input immediately
                    escape_pressed = True
                    set_escape_interrupt(True)
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    break

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

    try:
        while True:
            # Read one character (blocking)
            char = msvcrt.getch()

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
                # Just ESC key pressed - submit input immediately
                escape_pressed = True
                set_escape_interrupt(True)
                sys.stdout.write('\n')
                sys.stdout.flush()
                break

            # Enter key
            elif char == b'\r':
                sys.stdout.write('\n')
                sys.stdout.flush()
                break

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
