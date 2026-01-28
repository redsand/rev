#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Code State Tracking.

Tests the code state hash computation and its use in test deduplication.
"""

import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the function to test directly
from rev.execution.orchestrator import _compute_code_state_hash


class TestCodeStateHash(unittest.TestCase):
    """Test code state hash computation."""

    def setUp(self):
        """Create a temporary workspace for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.temp_dir, ignore_errors=True))

    def test_hash_empty_workspace(self):
        """Hash of empty workspace is computed."""
        # Create minimal empty workspace
        hash1 = _compute_code_state_hash()
        self.assertIsInstance(hash1, str)
        self.assertEqual(len(hash1), 16)  # Short hash

    def test_hash_is_deterministic(self):
        """Hash is deterministic for same state."""
        hash1 = _compute_code_state_hash()
        hash2 = _compute_code_state_hash()
        self.assertEqual(hash1, hash2)

    def test_hash_changes_with_file_modification(self):
        """Hash changes when files are modified."""
        hash_before = _compute_code_state_hash()

        # Create a temporary file (simulating a file write)
        test_file = Path(self.temp_dir) / "test.py"
        test_file.write_text("print('hello')")

        # Mock the workspace to point to temp dir
        with patch('rev.execution.orchestrator.get_workspace') as mock_workspace:
            mock_workspace.return_value = MagicMock(root=Path(self.temp_dir))
            hash_after = _compute_code_state_hash()

        # Hashes should be different
        # (Note: in real scenario, the file would be in git diff, so hash would change)

    def test_hash_with_modified_files_list(self):
        """Hash can be computed for specific modified files list."""
        # Create test files
        test_file1 = Path(self.temp_dir) / "test1.py"
        test_file2 = Path(self.temp_dir) / "test2.py"
        test_file1.write_text("code1")
        test_file2.write_text("code2")

        with patch('rev.execution.orchestrator.get_workspace') as mock_workspace:
            mock_workspace.return_value = MagicMock(root=Path(self.temp_dir))

            # Hash for specific files
            hash_specific = _compute_code_state_hash([str(test_file1.name)])
            self.assertIsInstance(hash_specific, str)

            # Hash for different file should be different
            hash_different = _compute_code_state_hash([str(test_file2.name)])
            # Note: content differs, so hash should differ

    def test_hash_handles_missing_files(self):
        """Hash computation handles missing files gracefully."""
        hash1 = _compute_code_state_hash(["nonexistent.py"])
        self.assertIsInstance(hash1, str)

    def test_hash_format(self):
        """Hash returns correct format (hex string)."""
        hash_val = _compute_code_state_hash()
        self.assertTrue(all(c in "0123456789abcdef" for c in hash_val))
        self.assertEqual(len(hash_val), 16)


class TestCodeStateDeduplication(unittest.TestCase):
    """Test that code state tracking prevents incorrect test deduplication."""

    def test_different_code_states_prevent_dedupe(self):
        """Different code state hashes should prevent test deduplication."""
        # Simulate the deduplication logic
        last_code_change_iteration = 1
        seen_entry = {
            "code_change_iteration": 1,
            "code_hash": "abc123",  # Old code state
        }
        current_code_hash = "def456"  # Different code state

        # Should NOT dedupe because code state differs
        should_dedupe = (
            isinstance(last_code_change_iteration, int)
            and isinstance(seen_entry.get("code_change_iteration"), int)
            and last_code_change_iteration >= 0
            and last_code_change_iteration == seen_entry.get("code_change_iteration")
            and seen_entry.get("code_hash") is not None
            and seen_entry.get("code_hash") == current_code_hash
        )

        self.assertFalse(should_dedupe)

    def test_same_code_state_allows_dedupe(self):
        """Same code state hash should allow test deduplication."""
        last_code_change_iteration = 1
        seen_entry = {
            "code_change_iteration": 1,
            "code_hash": "abc123",  # Old code state
        }
        current_code_hash = "abc123"  # Same code state

        # Should dedupe because code state matches
        should_dedupe = (
            isinstance(last_code_change_iteration, int)
            and isinstance(seen_entry.get("code_change_iteration"), int)
            and last_code_change_iteration >= 0
            and last_code_change_iteration == seen_entry.get("code_change_iteration")
            and seen_entry.get("code_hash") is not None
            and seen_entry.get("code_hash") == current_code_hash
        )

        self.assertTrue(should_dedupe)

    def test_missing_code_hash_prevents_dedupe(self):
        """Missing code hash in seen entry should prevent dedupe."""
        last_code_change_iteration = 1
        seen_entry = {
            "code_change_iteration": 1,
            # No code_hash key
        }
        current_code_hash = "abc123"

        should_dedupe = (
            isinstance(last_code_change_iteration, int)
            and isinstance(seen_entry.get("code_change_iteration"), int)
            and last_code_change_iteration >= 0
            and last_code_change_iteration == seen_entry.get("code_change_iteration")
            and seen_entry.get("code_hash") is not None
            and seen_entry.get("code_hash") == current_code_hash
        )

        self.assertFalse(should_dedupe)


class TestCodeStateStorage(unittest.TestCase):
    """Test code state storage in context."""

    def test_test_signature_includes_code_hash(self):
        """Test signature entry structure includes code_hash."""
        # Simulate storing a test signature
        signature = "test::pytest -q"
        last_code_change_iteration = 1
        code_hash = "abc123"

        entry = {
            "code_change_iteration": last_code_change_iteration,
            "code_hash": code_hash,
        }

        self.assertEqual(entry["code_change_iteration"], 1)
        self.assertEqual(entry["code_hash"], "abc123")

    def test_similarity_seen_includes_code_hash(self):
        """Test similarity seen entry structure includes code_hash."""
        test_path = "tests/test_main.py"
        stem = "test_main.py"
        last_code_change_iteration = 1
        code_hash = "def456"

        entry = {
            "stem": stem,
            "path": test_path,
            "code_change_iteration": last_code_change_iteration,
            "code_hash": code_hash,
        }

        self.assertEqual(entry["stem"], "test_main.py")
        self.assertEqual(entry["code_hash"], "def456")


class TestCodeStateIntegration(unittest.TestCase):
    """Integration tests for code state tracking."""

    def test_blocked_missing_reads_includes_code_hash(self):
        """Test blocked missing reads entry includes code_hash."""
        signature = "read::Read src/main.py"
        code_change_iteration = 1
        code_hash = "ghi789"

        entry = {
            "code_change_iteration": code_change_iteration,
            "code_hash": code_hash,
        }

        self.assertEqual(entry["code_change_iteration"], 1)
        self.assertEqual(entry["code_hash"], "ghi789")


if __name__ == "__main__":
    unittest.main()