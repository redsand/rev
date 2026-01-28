#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Consecutive Reads Guard Removal.

Tests that the consecutive reads guard has been removed to allow
uninterrupted research.
"""

import unittest
import inspect
import rev.execution.orchestrator as orch_module


class TestConsecutiveReadsGuardRemoval(unittest.TestCase):
    """Test that consecutive reads guard has been removed."""

    def test_consecutive_reads_guard_removed(self):
        """Verify the consecutive reads guard has been removed.

        The guard previously forced action phase after MAX_CONSECUTIVE_READS (40)
        consecutive research tasks. This test verifies it has been removed.
        """
        source = inspect.getsource(orch_module)

        # The guard should be removed (REMOVED comment should be present)
        self.assertIn('REMOVED: Consecutive reads guard', source,
                     "Consecutive reads guard should be marked as removed")

        # Old behavior should be commented out/removed
        self.assertNotIn('if consecutive_reads >= MAX_CONSECUTIVE_READS', source,
                        "Old consecutive reads check should be removed")

        # The forced action phase trigger should be gone
        self.assertNotIn('RESEARCH_BUDGET_EXHAUSTED', source,
                        "Research budget exhausted trigger should be removed")

    def test_consecutive_reads_counter_still_exists(self):
        """Verify consecutive_reads counter still exists for other purposes.

        The counter is still tracked but no longer triggers forced action phase.
        """
        source = inspect.getsource(orch_module)

        # Counter should still be tracked
        self.assertIn('consecutive_reads:', source,
                     "consecutive_reads counter should still be tracked")
        self.assertIn('consecutive_reads += 1', source,
                     "Counter increment should still exist")
        self.assertIn('consecutive_reads = 0', source,
                     "Counter reset should still exist")

    def test_research_not_forced_to_action_phase(self):
        """Verify research tasks are not forced to action phase.

        Research tasks should continue uninterrupted until the agent
        decides to switch to action phase based on task requirements.
        """
        source = inspect.getsource(orch_module)

        # Should NOT contain forced action phase trigger for research
        self.assertNotIn('forcing action phase', source.lower(),
                        "Should not force action phase")

        # Should NOT have constraint that prevents consecutive research
        self.assertNotIn('You MUST now propose a concrete action task', source,
                        "Should not force agent to propose action task")


if __name__ == "__main__":
    unittest.main()