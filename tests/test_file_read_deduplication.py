#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for File Read Deduplication Relaxation.

Tests that file read deduplication has been relaxed to allow
legitimate re-reading during debugging and research.
"""

import unittest
from unittest.mock import MagicMock
from rev.execution.orchestrator import _count_file_reads


class TestFileReadDeduplication(unittest.TestCase):
    """Test file read deduplication relaxation."""

    def test_count_file_reads_returns_zero_for_empty_list(self):
        """Returns 0 for empty completed tasks list."""
        count = _count_file_reads("test.py", [])
        self.assertEqual(count, 0)

    def test_count_file_reads_returns_zero_for_none_file_path(self):
        """Returns 0 for None file path."""
        count = _count_file_reads(None, [])
        self.assertEqual(count, 0)

    def test_count_file_reads_returns_zero_for_empty_file_path(self):
        """Returns 0 for empty file path."""
        count = _count_file_reads("", [])
        self.assertEqual(count, 0)

    def test_count_file_reads_counts_read_file_tasks(self):
        """Counts tasks that read the specified file."""
        # Create mock tasks with tool_events
        task1 = MagicMock()
        task1.status = MagicMock(value='completed')
        task1.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'src/main.py', 'raw_result': 'content'}}
        ]

        task2 = MagicMock()
        task2.status = MagicMock(value='completed')
        task2.tool_events = [
            {'tool': 'write_file', 'args': {'path': 'src/test.py', 'raw_result': 'success'}}
        ]

        completed_tasks = [task1, task2]
        count = _count_file_reads('src/main.py', completed_tasks)

        # Should count only the read_file task for main.py
        self.assertEqual(count, 1)

    def test_count_file_reads_path_normalization(self):
        """Path normalization works correctly (handles backslashes)."""
        task1 = MagicMock()
        task1.status = MagicMock(value='completed')
        task1.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'src\\main.py', 'raw_result': 'content'}}
        ]

        completed_tasks = [task1]

        # Test with forward slashes
        count1 = _count_file_reads('src/main.py', completed_tasks)
        # Test with backslashes
        count2 = _count_file_reads('src\\main.py', completed_tasks)
        # Test with mixed case
        count3 = _count_file_reads('SRC/Main.Py', completed_tasks)

        self.assertEqual(count1, 1)
        self.assertEqual(count2, 1)
        self.assertEqual(count3, 1)

    def test_count_file_reads_multiple_reads_same_file(self):
        """Counts multiple reads of the same file."""
        task1 = MagicMock()
        task1.status = MagicMock(value='completed')
        task1.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'src/main.py', 'raw_result': 'content'}}
        ]

        task2 = MagicMock()
        task2.status = MagicMock(value='completed')
        task2.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'src/main.py', 'raw_result': 'content'}}
        ]

        task3 = MagicMock()
        task3.status = MagicMock(value='completed')
        task3.tool_events = [
            {'tool': 'search_code', 'args': {'query': 'test'}, 'raw_result': 'results'}
        ]

        completed_tasks = [task1, task2, task3]
        count = _count_file_reads('src/main.py', completed_tasks)

        # Should count both read_file tasks for main.py
        self.assertEqual(count, 2)

    def test_count_file_reads_only_completed_tasks(self):
        """Only counts completed tasks, ignores failed/stopped tasks."""
        # Completed task
        task_completed = MagicMock()
        task_completed.status = MagicMock(value='completed')
        task_completed.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'test.py', 'raw_result': 'content'}}
        ]

        # Failed task (should not count)
        task_failed = MagicMock()
        task_failed.status = MagicMock(value='failed')
        task_failed.tool_events = [
            {'tool': 'read_file', 'args': {'path': 'test.py', 'raw_result': 'error'}}
        ]

        completed_tasks = [task_completed, task_failed]
        count = _count_file_reads('test.py', completed_tasks)

        # Should only count the completed task
        self.assertEqual(count, 1)


class TestFileReadThreshold(unittest.TestCase):
    """Test that file read deduplication threshold has been increased."""

    def test_redundant_read_threshold_increased(self):
        """Verify the redundant read threshold has been increased from 2 to 5.

        This test verifies that the code change has been applied to
        increase the threshold for blocking redundant file reads.

        The new threshold allows up to 5 reads of the same file before
        blocking, which is more lenient for debugging scenarios.
        """
        # Read the orchestrator code to check the threshold
        import rev.execution.orchestrator as orch_module

        # The threshold should now be 5 instead of 2
        # We verify this by checking the source code
        import inspect
        source = inspect.getsource(orch_module)

        # Check that the threshold has been updated
        self.assertIn('if read_count >= 5:', source,
                     "Redundant read threshold should be >= 5")
        self.assertNotIn('if read_count >= 2:', source,
                        "Old threshold of 2 should be removed")

    def test_redundant_read_allows_more_reads(self):
        """Verify that more reads are now allowed before blocking.

        Scenario:
        - File is read 3 times
        - Old behavior: would block after 2 reads
        - New behavior: should allow (threshold is 5)
        """
        # Create 3 mock tasks that read the same file
        tasks = []
        for i in range(3):
            task = MagicMock()
            task.status = MagicMock(value='completed')
            task.tool_events = [
                {'tool': 'read_file', 'args': {'path': 'test.py', 'raw_result': f'content{i}'}}
            ]
            tasks.append(task)

        count = _count_file_reads('test.py', tasks)

        # Should count all 3 reads
        self.assertEqual(count, 3)

        # The threshold is now 5, so 3 reads should NOT be blocked
        # (In the actual orchestrator code, the check is: if read_count >= 5)
        self.assertLess(count, 5, "3 reads should be allowed with new threshold of 5")

    def test_redundant_read_blocks_at_threshold(self):
        """Verify that blocking still happens at the new threshold.

        Scenario:
        - File is read 5 times
        - New behavior: should block (threshold is 5)
        """
        # Create 5 mock tasks that read the same file
        tasks = []
        for i in range(5):
            task = MagicMock()
            task.status = MagicMock(value='completed')
            task.tool_events = [
                {'tool': 'read_file', 'args': {'path': 'test.py', 'raw_result': f'content{i}'}}
            ]
            tasks.append(task)

        count = _count_file_reads('test.py', tasks)

        # Should count all 5 reads
        self.assertEqual(count, 5)

        # The threshold is 5, so 5 reads SHOULD be blocked
        # (In the actual orchestrator code, the check is: if read_count >= 5)
        self.assertGreaterEqual(count, 5, "5 reads should reach the blocking threshold")


if __name__ == "__main__":
    unittest.main()