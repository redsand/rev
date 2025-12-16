#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for execution mode configuration."""

import unittest
import os
from rev import config


class TestExecutionModeConfig(unittest.TestCase):
    """Test execution mode configuration functions."""

    def setUp(self):
        """Save the original execution mode."""
        self.original_mode = config.EXECUTION_MODE

    def tearDown(self):
        """Restore the original execution mode."""
        config.EXECUTION_MODE = self.original_mode
        if "REV_EXECUTION_MODE" in os.environ:
            os.environ["REV_EXECUTION_MODE"] = self.original_mode

    def test_set_execution_mode_linear(self):
        """Test setting execution mode to linear."""
        result = config.set_execution_mode("linear")
        self.assertTrue(result)
        self.assertEqual(config.get_execution_mode(), "linear")
        self.assertEqual(os.environ.get("REV_EXECUTION_MODE"), "linear")

    def test_set_execution_mode_sub_agent(self):
        """Test setting execution mode to sub-agent."""
        result = config.set_execution_mode("sub-agent")
        self.assertTrue(result)
        self.assertEqual(config.get_execution_mode(), "sub-agent")
        self.assertEqual(os.environ.get("REV_EXECUTION_MODE"), "sub-agent")

    def test_set_execution_mode_inline_alias(self):
        """Test that 'inline' is an alias for 'linear'."""
        result = config.set_execution_mode("inline")
        self.assertTrue(result)
        self.assertEqual(config.get_execution_mode(), "linear")
        self.assertEqual(os.environ.get("REV_EXECUTION_MODE"), "linear")

    def test_set_execution_mode_case_insensitive(self):
        """Test that mode setting is case-insensitive."""
        result = config.set_execution_mode("SUB-AGENT")
        self.assertTrue(result)
        self.assertEqual(config.get_execution_mode(), "sub-agent")

    def test_set_execution_mode_whitespace(self):
        """Test that mode setting handles whitespace."""
        result = config.set_execution_mode("  linear  ")
        self.assertTrue(result)
        self.assertEqual(config.get_execution_mode(), "linear")

    def test_set_execution_mode_invalid(self):
        """Test that invalid modes return False."""
        result = config.set_execution_mode("invalid_mode")
        self.assertFalse(result)
        # Mode should not have changed
        self.assertEqual(config.get_execution_mode(), self.original_mode)

    def test_get_execution_mode_default(self):
        """Test getting the execution mode returns a valid value."""
        mode = config.get_execution_mode()
        self.assertIn(mode, ["linear", "sub-agent"])


if __name__ == "__main__":
    unittest.main()
