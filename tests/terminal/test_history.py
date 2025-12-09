#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for terminal history navigation functionality."""

from unittest import TestCase
from unittest.mock import patch, MagicMock
from rev.terminal.history import PromptHistory
from rev.terminal.input import get_history
from rev.config import HISTORY_SIZE


class TestPromptHistory(TestCase):
    """Test suite for PromptHistory class."""

    def setUp(self):
        """Setup a fresh history instance for each test."""
        self.history = PromptHistory(max_history=HISTORY_SIZE)

    def test_initial_state(self):
        """Test that history starts empty."""
        self.assertEqual(len(self.history.command_history), 0)
        self.assertEqual(len(self.history.input_history), 0)
        self.assertEqual(self.history.history_position, 0)
        self.assertIsNone(self.history.current_history)
        self.assertEqual(self.history.current_input, "")

    def test_add_command(self):
        """Test adding commands to history."""
        self.history.add_command("help")
        self.history.add_command("config")
        
        self.assertEqual(len(self.history.command_history), 2)
        self.assertEqual(self.history.command_history[0], "help")
        self.assertEqual(self.history.command_history[1], "config")
        self.assertEqual(len(self.history.input_history), 0)

    def test_add_input(self):
        """Test adding regular input to history."""
        self.history.add_input("first input")
        self.history.add_input("second input")
        
        self.assertEqual(len(self.history.input_history), 2)
        self.assertEqual(self.history.input_history[0], "first input")
        self.assertEqual(self.history.input_history[1], "second input")
        self.assertEqual(len(self.history.command_history), 0)

    def test_history_size_limit(self):
        """Test that history respects size limit."""
        # Add more entries than history size
        for i in range(HISTORY_SIZE + 5):
            self.history.add_input(f"input {i}")
        
        self.assertEqual(len(self.history.input_history), HISTORY_SIZE)
        self.assertEqual(self.history.input_history[0], f"input {5}")  # Oldest entry
        self.assertEqual(self.history.input_history[-1], f"input {HISTORY_SIZE + 4}")  # Newest entry

    def test_duplicate_prevention(self):
        """Test that consecutive duplicates are prevented."""
        self.history.add_input("command")
        self.history.add_input("command")  # Duplicate
        
        self.assertEqual(len(self.history.input_history), 1)  # Should only store one
        self.assertEqual(self.history.input_history[0], "command")

    def test_empty_command_prevention(self):
        """Test that empty commands are not stored."""
        self.history.add_input("")
        self.history.add_input("   ")
        
        self.assertEqual(len(self.history.input_history), 0)  # Should be empty

    def test_whitespace_normalization(self):
        """Test that whitespace-only inputs are not stored."""
        self.history.add_input("  ")
        self.history.add_input("")
        
        self.assertEqual(len(self.history.input_history), 0)

    def test_navigation_up_command(self):
        """Test navigating up through command history."""
        self.history.add_command("first")
        self.history.add_command("second")
        self.history.add_command("third")
        
        # Start navigation
        self.history.start_navigation(is_command=True)
        
        # Should navigate from newest to oldest
        self.assertEqual(self.history.get_previous(), "third")
        self.assertEqual(self.history.get_previous(), "second")
        self.assertEqual(self.history.get_previous(), "first")
        self.assertIsNone(self.history.get_previous())  # Should stay at oldest

    def test_navigation_down_command(self):
        """Test navigating down through command history."""
        self.history.add_command("first")
        self.history.add_command("second")
        self.history.add_command("third")
        
        # Start navigation and go up twice
        self.history.start_navigation(is_command=True)
        self.history.get_previous()
        self.history.get_previous()
        
        # Should navigate from second to third
        self.assertEqual(self.history.get_next(), "third")
        result = self.history.get_next()
        self.assertTrue(result is None or result == "")  # Should return to empty/None

    def test_navigation_up_input(self):
        """Test navigating up through input history."""
        self.history.add_input("first input")
        self.history.add_input("second input")
        
        # Start navigation
        self.history.start_navigation(is_command=False)
        
        # Should navigate from newest to oldest
        self.assertEqual(self.history.get_previous(), "second input")
        self.assertEqual(self.history.get_previous(), "first input")
        self.assertIsNone(self.history.get_previous())  # Should stay at oldest

    def test_temp_input_preservation(self):
        """Test that temporary input is preserved during navigation."""
        self.history.add_input("first")
        self.history.add_input("second")
        
        # Start navigation with temporary input
        temp_input = "temporary"
        self.history.start_navigation(is_command=False, current_input=temp_input)
        
        # Navigate up (should save temp input)
        self.history.get_previous()
        
        # Navigate down (should restore temp input)
        result = self.history.get_next()
        self.assertEqual(result, temp_input if temp_input else None)

    def test_separate_histories(self):
        """Test that command and input histories are separate."""
        self.history.add_command("config")
        self.history.add_input("some input")
        self.history.add_command("help")
        
        self.assertEqual(len(self.history.command_history), 2)
        self.assertEqual(len(self.history.input_history), 1)
        self.assertEqual(self.history.command_history[0], "config")
        self.assertEqual(self.history.command_history[1], "help")
        self.assertEqual(self.history.input_history[0], "some input")


class TestGlobalHistory(TestCase):
    """Test suite for global history management."""

    def test_singleton_behavior(self):
        """Test that get_history() returns the same instance."""
        history1 = get_history()
        history2 = get_history()
        
        self.assertIs(history1, history2)
        self.assertIsInstance(history1, PromptHistory)

    def test_global_history_state(self):
        """Test that global history maintains state across calls."""
        history = get_history()
        history.add_input("global input")
        
        # Get history again (should be same instance)
        history2 = get_history()
        history2.start_navigation(is_command=False)
        self.assertEqual(history2.get_previous(), "global input")


class TestHistoryIntegration(TestCase):
    """Integration tests for history functionality."""

    @patch('rev.terminal.input.platform.system')
    @patch('rev.terminal.input._get_input_unix')
    @patch('rev.terminal.input._get_input_windows')
    def test_history_integration_unix(self, mock_windows, mock_unix, mock_platform):
        """Test history integration on Unix systems."""
        mock_platform.return_value = 'Linux'
        mock_unix.return_value = ("test input", False)
        
        from rev.terminal.input import get_input_with_escape
        
        # Get history and add test entry
        history = get_history()
        history.add_input("test command")
        
        # Call get_input_with_escape (should use same history)
        result, escape_pressed = get_input_with_escape("> ")
        
        self.assertEqual(result, "test input")
        self.assertFalse(escape_pressed)
        # History should still contain our test entry
        history.start_navigation(is_command=False)
        self.assertEqual(history.get_previous(), "test command")

    @patch('rev.terminal.input.platform.system')
    @patch('rev.terminal.input._get_input_unix')
    @patch('rev.terminal.input._get_input_windows')
    def test_history_integration_windows(self, mock_windows, mock_unix, mock_platform):
        """Test history integration on Windows systems."""
        mock_platform.return_value = 'Windows'
        mock_windows.return_value = ("windows input", False)
        
        from rev.terminal.input import get_input_with_escape
        
        # Get history and add test entry
        history = get_history()
        history.add_input("windows command")
        
        # Call get_input_with_escape (should use same history)
        result, escape_pressed = get_input_with_escape("> ")
        
        self.assertEqual(result, "windows input")
        self.assertFalse(escape_pressed)
        # History should still contain our test entry
        history.start_navigation(is_command=False)
        self.assertEqual(history.get_previous(), "windows command")