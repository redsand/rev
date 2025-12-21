#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for transactional execution manager."""

import pytest
from pathlib import Path
import tempfile
import shutil
import json

from rev.execution.transaction_manager import (
    TransactionManager,
    Transaction,
    ToolAction,
    TransactionStatus,
    RollbackMethod
)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    workspace = Path(tempfile.mkdtemp())
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def transaction_manager(temp_workspace):
    """Create a transaction manager."""
    log_file = temp_workspace / ".rev" / "transactions.jsonl"
    return TransactionManager(temp_workspace, log_file)


class TestTransactionLifecycle:
    """Test transaction begin/commit/abort lifecycle."""

    def test_begin_transaction(self, transaction_manager):
        """Should create a new transaction."""
        tx = transaction_manager.begin(task_id="task-001")

        assert tx.tx_id.startswith("tx_")
        assert tx.task_id == "task-001"
        assert tx.status == TransactionStatus.ACTIVE
        assert len(tx.actions) == 0
        assert transaction_manager.current_transaction == tx

    def test_begin_transaction_with_git_rollback(self, transaction_manager):
        """Should prepare git rollback data."""
        tx = transaction_manager.begin(
            task_id="task-002",
            rollback_method=RollbackMethod.GIT_CHECKOUT
        )

        assert tx.rollback_method == RollbackMethod.GIT_CHECKOUT
        assert "ref" in tx.rollback_data

    def test_cannot_begin_while_active(self, transaction_manager):
        """Should not allow starting a new transaction while one is active."""
        transaction_manager.begin(task_id="task-001")

        with pytest.raises(RuntimeError, match="already active"):
            transaction_manager.begin(task_id="task-002")

    def test_commit_transaction(self, transaction_manager):
        """Should commit an active transaction."""
        tx = transaction_manager.begin(task_id="task-001")
        tx_id = tx.tx_id

        committed_tx = transaction_manager.commit()

        assert committed_tx.tx_id == tx_id
        assert committed_tx.status == TransactionStatus.COMMITTED
        assert committed_tx.committed_at is not None
        assert transaction_manager.current_transaction is None

    def test_commit_without_active_transaction(self, transaction_manager):
        """Should raise error when committing without active transaction."""
        with pytest.raises(RuntimeError, match="No active transaction"):
            transaction_manager.commit()

    def test_abort_transaction(self, transaction_manager):
        """Should abort an active transaction."""
        tx = transaction_manager.begin(task_id="task-001")
        tx_id = tx.tx_id

        aborted_tx = transaction_manager.abort(reason="Test abort")

        assert aborted_tx.tx_id == tx_id
        assert aborted_tx.status == TransactionStatus.ROLLED_BACK
        assert aborted_tx.aborted_at is not None
        assert "Test abort" in aborted_tx.rollback_data.get("abort_reason", "")
        assert transaction_manager.current_transaction is None

    def test_abort_without_active_transaction(self, transaction_manager):
        """Should raise error when aborting without active transaction."""
        with pytest.raises(RuntimeError, match="No active transaction"):
            transaction_manager.abort()


class TestActionRecording:
    """Test recording tool actions within transactions."""

    def test_record_action(self, transaction_manager, temp_workspace):
        """Should record a tool action."""
        # Create a test file
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original content")

        tx = transaction_manager.begin(task_id="task-001")

        action = transaction_manager.record_action(
            tool="write_file",
            args={"path": "test.txt", "content": "new content"},
            files=["test.txt"],
            result="success"
        )

        assert action.tool == "write_file"
        assert action.args["path"] == "test.txt"
        assert action.files == ["test.txt"]
        assert action.result == "success"
        assert action.hash_before is not None
        assert len(tx.actions) == 1

    def test_record_action_without_transaction(self, transaction_manager):
        """Should raise error when recording action without active transaction."""
        with pytest.raises(RuntimeError, match="No active transaction"):
            transaction_manager.record_action(
                tool="write_file",
                args={},
                files=[]
            )

    def test_record_multiple_actions(self, transaction_manager, temp_workspace):
        """Should record multiple actions in sequence."""
        (temp_workspace / "file1.txt").write_text("content1")
        (temp_workspace / "file2.txt").write_text("content2")

        tx = transaction_manager.begin(task_id="task-001")

        transaction_manager.record_action("edit", {}, ["file1.txt"])
        transaction_manager.record_action("edit", {}, ["file2.txt"])

        assert len(tx.actions) == 2
        assert tx.actions[0].files == ["file1.txt"]
        assert tx.actions[1].files == ["file2.txt"]

    def test_record_action_with_error(self, transaction_manager):
        """Should record action that resulted in error."""
        tx = transaction_manager.begin(task_id="task-001")

        action = transaction_manager.record_action(
            tool="run_command",
            args={"cmd": "invalid_command"},
            error="Command not found"
        )

        assert action.error == "Command not found"
        assert action.result is None


class TestFileBackup:
    """Test file backup and restore functionality."""

    def test_backup_files_on_action(self, transaction_manager, temp_workspace):
        """Should backup files when action is recorded."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original content")

        tx = transaction_manager.begin(
            task_id="task-001",
            rollback_method=RollbackMethod.FILE_RESTORE
        )

        transaction_manager.record_action(
            tool="edit",
            args={},
            files=["test.txt"]
        )

        # Check backup exists
        backup_dir = Path(tx.rollback_data["backup_dir"])
        backup_file = backup_dir / "test.txt"

        assert backup_file.exists()
        assert backup_file.read_text() == "original content"

    def test_restore_files_on_abort(self, transaction_manager, temp_workspace):
        """Should restore files when transaction is aborted."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original content")

        tx = transaction_manager.begin(
            task_id="task-001",
            rollback_method=RollbackMethod.FILE_RESTORE
        )

        # Record action and modify file
        transaction_manager.record_action("edit", {}, ["test.txt"])
        test_file.write_text("modified content")

        # Abort should restore original content
        transaction_manager.abort()

        assert test_file.read_text() == "original content"

    def test_cleanup_backups_on_commit(self, transaction_manager, temp_workspace):
        """Should clean up backups when transaction is committed."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original content")

        tx = transaction_manager.begin(
            task_id="task-001",
            rollback_method=RollbackMethod.FILE_RESTORE
        )

        transaction_manager.record_action("edit", {}, ["test.txt"])

        backup_dir = Path(tx.rollback_data["backup_dir"])
        assert backup_dir.exists()

        # Commit should clean up backup
        transaction_manager.commit()

        assert not backup_dir.exists()

    def test_backup_preserves_directory_structure(self, transaction_manager, temp_workspace):
        """Should preserve directory structure in backups."""
        nested_dir = temp_workspace / "subdir" / "nested"
        nested_dir.mkdir(parents=True)
        nested_file = nested_dir / "file.txt"
        nested_file.write_text("content")

        tx = transaction_manager.begin(
            task_id="task-001",
            rollback_method=RollbackMethod.FILE_RESTORE
        )

        transaction_manager.record_action("edit", {}, ["subdir/nested/file.txt"])

        backup_dir = Path(tx.rollback_data["backup_dir"])
        backup_file = backup_dir / "subdir" / "nested" / "file.txt"

        assert backup_file.exists()
        assert backup_file.read_text() == "content"


class TestTransactionLogging:
    """Test transaction logging to JSONL file."""

    def test_log_transaction_on_begin(self, transaction_manager):
        """Should log transaction when it begins."""
        tx = transaction_manager.begin(task_id="task-001")

        assert transaction_manager.log_file.exists()

        # Read log
        with open(transaction_manager.log_file, "r") as f:
            log_entry = json.loads(f.readline())

        assert log_entry["tx_id"] == tx.tx_id
        assert log_entry["status"] == "active"

    def test_log_transaction_on_commit(self, transaction_manager):
        """Should log transaction when committed."""
        tx = transaction_manager.begin(task_id="task-001")
        transaction_manager.commit()

        # Read all log entries
        with open(transaction_manager.log_file, "r") as f:
            lines = f.readlines()

        # Should have 2 entries (begin + commit)
        assert len(lines) == 2

        commit_entry = json.loads(lines[-1])
        assert commit_entry["status"] == "committed"
        assert commit_entry["committed_at"] is not None

    def test_log_transaction_on_abort(self, transaction_manager):
        """Should log transaction when aborted."""
        tx = transaction_manager.begin(task_id="task-001")
        transaction_manager.abort(reason="Test abort")

        with open(transaction_manager.log_file, "r") as f:
            lines = f.readlines()

        # Should have 2 entries (begin + abort)
        assert len(lines) == 2

        abort_entry = json.loads(lines[-1])
        assert abort_entry["status"] == "rolled_back"
        assert abort_entry["aborted_at"] is not None

    def test_log_includes_actions(self, transaction_manager, temp_workspace):
        """Should log all actions in transaction."""
        (temp_workspace / "test.txt").write_text("content")

        tx = transaction_manager.begin(task_id="task-001")
        transaction_manager.record_action("edit", {"key": "value"}, ["test.txt"])
        transaction_manager.commit()

        with open(transaction_manager.log_file, "r") as f:
            lines = f.readlines()

        commit_entry = json.loads(lines[-1])
        assert len(commit_entry["actions"]) == 1
        assert commit_entry["actions"][0]["tool"] == "edit"
        assert commit_entry["actions"][0]["args"]["key"] == "value"


class TestTransactionHistory:
    """Test transaction history retrieval."""

    def test_get_transaction_history(self, transaction_manager):
        """Should retrieve transaction history."""
        # Create multiple transactions
        tx1 = transaction_manager.begin(task_id="task-001")
        transaction_manager.commit()

        tx2 = transaction_manager.begin(task_id="task-002")
        transaction_manager.abort()

        tx3 = transaction_manager.begin(task_id="task-003")
        transaction_manager.commit()

        # Get history
        history = transaction_manager.get_transaction_history()

        # Should have 3 transactions (most recent first)
        assert len(history) == 3
        assert history[0].tx_id == tx3.tx_id
        assert history[1].tx_id == tx2.tx_id
        assert history[2].tx_id == tx1.tx_id

    def test_get_transaction_history_with_limit(self, transaction_manager):
        """Should limit number of transactions returned."""
        for i in range(5):
            tx = transaction_manager.begin(task_id=f"task-{i}")
            transaction_manager.commit()

        history = transaction_manager.get_transaction_history(limit=2)

        assert len(history) == 2

    def test_get_transaction_by_id(self, transaction_manager):
        """Should retrieve specific transaction by ID."""
        tx1 = transaction_manager.begin(task_id="task-001")
        transaction_manager.commit()

        tx2 = transaction_manager.begin(task_id="task-002")
        transaction_manager.commit()

        # Get specific transaction
        retrieved_tx = transaction_manager.get_transaction_by_id(tx1.tx_id)

        assert retrieved_tx is not None
        assert retrieved_tx.tx_id == tx1.tx_id
        assert retrieved_tx.task_id == "task-001"

    def test_get_transaction_by_id_not_found(self, transaction_manager):
        """Should return None if transaction not found."""
        retrieved_tx = transaction_manager.get_transaction_by_id("tx_nonexistent")

        assert retrieved_tx is None


class TestStatistics:
    """Test transaction statistics."""

    def test_get_statistics(self, transaction_manager):
        """Should calculate transaction statistics."""
        # Create various transactions
        tx1 = transaction_manager.begin(task_id="task-001")
        transaction_manager.commit()

        tx2 = transaction_manager.begin(task_id="task-002")
        transaction_manager.abort()

        tx3 = transaction_manager.begin(task_id="task-003")
        transaction_manager.record_action("edit", {}, [])
        transaction_manager.record_action("test", {}, [])
        transaction_manager.commit()

        stats = transaction_manager.get_statistics()

        assert stats["total"] == 3
        assert stats["committed"] == 2
        assert stats["aborted"] == 0
        assert stats["rolled_back"] == 1
        assert stats["total_actions"] == 2
        assert len(stats["recent_transactions"]) <= 5


class TestHashComputation:
    """Test file hash computation."""

    def test_compute_hash_empty_files(self, transaction_manager):
        """Should return empty string for no files."""
        hash_val = transaction_manager._compute_hash([])

        assert hash_val == ""

    def test_compute_hash_single_file(self, transaction_manager, temp_workspace):
        """Should compute hash for single file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("content")

        hash_val = transaction_manager._compute_hash(["test.txt"])

        assert hash_val != ""
        assert len(hash_val) == 64  # SHA256 hex digest

    def test_compute_hash_multiple_files(self, transaction_manager, temp_workspace):
        """Should compute combined hash for multiple files."""
        (temp_workspace / "file1.txt").write_text("content1")
        (temp_workspace / "file2.txt").write_text("content2")

        hash_val = transaction_manager._compute_hash(["file1.txt", "file2.txt"])

        assert hash_val != ""
        assert len(hash_val) == 64

    def test_compute_hash_same_files_same_hash(self, transaction_manager, temp_workspace):
        """Should produce same hash for same files."""
        (temp_workspace / "file.txt").write_text("content")

        hash1 = transaction_manager._compute_hash(["file.txt"])
        hash2 = transaction_manager._compute_hash(["file.txt"])

        assert hash1 == hash2

    def test_compute_hash_different_content_different_hash(self, transaction_manager, temp_workspace):
        """Should produce different hash when content changes."""
        test_file = temp_workspace / "file.txt"

        test_file.write_text("content1")
        hash1 = transaction_manager._compute_hash(["file.txt"])

        test_file.write_text("content2")
        hash2 = transaction_manager._compute_hash(["file.txt"])

        assert hash1 != hash2


class TestSerialization:
    """Test transaction and action serialization."""

    def test_action_to_dict(self):
        """Should serialize ToolAction to dictionary."""
        action = ToolAction(
            tool="edit",
            timestamp="2025-01-01T00:00:00",
            args={"key": "value"},
            files=["file.txt"],
            hash_before="abc123",
            hash_after="def456",
            result="success"
        )

        data = action.to_dict()

        assert data["tool"] == "edit"
        assert data["args"]["key"] == "value"
        assert data["files"] == ["file.txt"]
        assert data["hash_before"] == "abc123"
        assert data["hash_after"] == "def456"

    def test_action_from_dict(self):
        """Should deserialize ToolAction from dictionary."""
        data = {
            "tool": "edit",
            "timestamp": "2025-01-01T00:00:00",
            "args": {"key": "value"},
            "files": ["file.txt"],
            "hash_before": "abc123",
            "hash_after": "def456"
        }

        action = ToolAction.from_dict(data)

        assert action.tool == "edit"
        assert action.args["key"] == "value"
        assert action.files == ["file.txt"]
        assert action.hash_before == "abc123"
        assert action.hash_after == "def456"

    def test_transaction_to_dict(self):
        """Should serialize Transaction to dictionary."""
        tx = Transaction(
            tx_id="tx_123",
            task_id="task-001",
            status=TransactionStatus.COMMITTED
        )

        data = tx.to_dict()

        assert data["tx_id"] == "tx_123"
        assert data["task_id"] == "task-001"
        assert data["status"] == "committed"

    def test_transaction_from_dict(self):
        """Should deserialize Transaction from dictionary."""
        data = {
            "tx_id": "tx_123",
            "task_id": "task-001",
            "status": "committed",
            "started_at": "2025-01-01T00:00:00"
        }

        tx = Transaction.from_dict(data)

        assert tx.tx_id == "tx_123"
        assert tx.task_id == "task-001"
        assert tx.status == TransactionStatus.COMMITTED


class TestRollbackScenarios:
    """Test various rollback scenarios."""

    def test_rollback_single_file_modification(self, transaction_manager, temp_workspace):
        """Should rollback single file modification."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("original")

        transaction_manager.begin(rollback_method=RollbackMethod.FILE_RESTORE)
        transaction_manager.record_action("edit", {}, ["test.txt"])

        test_file.write_text("modified")

        transaction_manager.abort()

        assert test_file.read_text() == "original"

    def test_rollback_multiple_file_modifications(self, transaction_manager, temp_workspace):
        """Should rollback multiple file modifications."""
        file1 = temp_workspace / "file1.txt"
        file2 = temp_workspace / "file2.txt"

        file1.write_text("original1")
        file2.write_text("original2")

        transaction_manager.begin(rollback_method=RollbackMethod.FILE_RESTORE)
        transaction_manager.record_action("edit", {}, ["file1.txt", "file2.txt"])

        file1.write_text("modified1")
        file2.write_text("modified2")

        transaction_manager.abort()

        assert file1.read_text() == "original1"
        assert file2.read_text() == "original2"

    def test_rollback_with_nested_directories(self, transaction_manager, temp_workspace):
        """Should rollback files in nested directories."""
        nested_dir = temp_workspace / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        nested_file = nested_dir / "file.txt"
        nested_file.write_text("original")

        transaction_manager.begin(rollback_method=RollbackMethod.FILE_RESTORE)
        transaction_manager.record_action("edit", {}, ["a/b/c/file.txt"])

        nested_file.write_text("modified")

        transaction_manager.abort()

        assert nested_file.read_text() == "original"
