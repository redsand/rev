#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Windows terminal input handling."""

from collections import deque
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

from rev.terminal.input import _get_input_windows


class TestWindowsInput(TestCase):
    """Windows-specific input handling tests."""

    def test_multiline_paste_preserves_newlines(self):
        """Pasting multiple lines should keep newline separators instead of submitting early."""
        # Simulate pasting "line1\nline2" followed by Enter to submit
        char_queue = deque([
            b'l', b'i', b'n', b'e', b'1',
            b'\r', b'\n',  # newline inside pasted content
            b'l', b'i', b'n', b'e', b'2',
            b'\r',  # final Enter to submit
        ])

        with patch('rev.terminal.input.msvcrt.getch', side_effect=char_queue.popleft):
            with patch('rev.terminal.input.msvcrt.kbhit', side_effect=lambda: len(char_queue) > 0):
                with patch('sys.stdout', new=StringIO()):
                    result, escape_pressed = _get_input_windows("> ")

        self.assertEqual(result, "line1\nline2")
        self.assertFalse(escape_pressed)

    def test_regular_enter_still_submits(self):
        """Regular Enter without buffered characters should submit immediately."""
        char_queue = deque([b't', b'e', b's', b't', b'\r'])

        with patch('rev.terminal.input.msvcrt.getch', side_effect=char_queue.popleft):
            with patch('rev.terminal.input.msvcrt.kbhit', side_effect=lambda: len(char_queue) > 0):
                with patch('sys.stdout', new=StringIO()):
                    result, escape_pressed = _get_input_windows("> ")

        self.assertEqual(result, "test")
        self.assertFalse(escape_pressed)
