#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transactional Execution Manager.

Implements MACI's transactional memory pattern for agent coordination.
Every tool action is tracked, and changes are rolled back if verification fails.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path
from enum import Enum
import json
import hashlib
import shutil
import subprocess
from datetime import datetime
import uuid

from rev.tools.command_runner import run_command_safe


class TransactionStatus(Enum):
    """Status of a transaction."""
    ACTIVE = "active"
    COMMITTED = "committed"
    ABORTED = "aborted"
    ROLLED_BACK = "rolled_back"


class RollbackMethod(Enum):
    """Methods for rolling back changes."""
    GIT_CHECKOUT = "git_checkout"
    FILE_RESTORE = "file_restore"
    NONE = "none"


@dataclass
class ToolAction:
    """A single tool action within a transaction."""
    tool: str
    timestamp: str
    args: Dict[str, Any] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)
    hash_before: Optional[str] = None
    hash_after: Optional[str] = None
    result: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "tool": self.tool,
            "timestamp": self.timestamp,
            "args": self.args,
            "files": self.files,
            "hash_before": self.hash_before,
            "hash_after": self.hash_after,
            "result": str(self.result) if self.result else None,
            "error": self.error
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ToolAction":
        """Deserialize from dictionary."""
        return ToolAction(
            tool=data["tool"],
            timestamp=data["timestamp"],
            args=data.get("args", {}),
            files=data.get("files", []),
            hash_before=data.get("hash_before"),
            hash_after=data.get("hash_after"),
            result=data.get("result"),
            error=data.get("error")
        )


@dataclass
class Transaction:
    """Represents a transaction with rollback capability."""
    tx_id: str
    task_id: Optional[str]
    status: TransactionStatus = TransactionStatus.ACTIVE
    actions: List[ToolAction] = field(default_factory=list)
    rollback_method: RollbackMethod = RollbackMethod.FILE_RESTORE
    rollback_data: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    committed_at: Optional[str] = None
    aborted_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "tx_id": self.tx_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "actions": [a.to_dict() for a in self.actions],
            "rollback_method": self.rollback_method.value,
            "rollback_data": self.rollback_data,
            "started_at": self.started_at,
            "committed_at": self.committed_at,
            "aborted_at": self.aborted_at
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Transaction":
        """Deserialize from dictionary."""
        return Transaction(
            tx_id=data["tx_id"],
            task_id=data.get("task_id"),
            status=TransactionStatus(data["status"]),
            actions=[ToolAction.from_dict(a) for a in data.get("actions", [])],
            rollback_method=RollbackMethod(data.get("rollback_method", "file_restore")),
            rollback_data=data.get("rollback_data", {}),
            started_at=data["started_at"],
            committed_at=data.get("committed_at"),
            aborted_at=data.get("aborted_at")
        )


class TransactionManager:
    """Manages transactions with automatic rollback on failure."""

    def __init__(self, workspace_root: Path, log_file: Optional[Path] = None):
        """
        Initialize transaction manager.

        Args:
            workspace_root: Root directory of the workspace
            log_file: Optional path to transaction log (JSONL format)
        """
        self.workspace_root = workspace_root
        self.log_file = log_file or (workspace_root / ".rev" / "transactions.jsonl")
        self.current_transaction: Optional[Transaction] = None
        self._backup_dir = workspace_root / ".rev" / "tx_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # Ensure log file directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def begin(self, task_id: Optional[str] = None, rollback_method: RollbackMethod = RollbackMethod.FILE_RESTORE) -> Transaction:
        """
        Begin a new transaction.

        Args:
            task_id: Optional task ID this transaction belongs to
            rollback_method: Method to use for rollback

        Returns:
            New Transaction object

        Raises:
            RuntimeError: If a transaction is already active
        """
        if self.current_transaction and self.current_transaction.status == TransactionStatus.ACTIVE:
            raise RuntimeError(f"Transaction {self.current_transaction.tx_id} is already active")

        tx_id = f"tx_{uuid.uuid4().hex[:8]}"
        transaction = Transaction(
            tx_id=tx_id,
            task_id=task_id,
            rollback_method=rollback_method
        )

        # Set up rollback data based on method
        if rollback_method == RollbackMethod.GIT_CHECKOUT:
            transaction.rollback_data = self._prepare_git_rollback()
        elif rollback_method == RollbackMethod.FILE_RESTORE:
            transaction.rollback_data = {"backup_dir": str(self._backup_dir / tx_id)}

        self.current_transaction = transaction
        self._log_transaction(transaction)

        return transaction

    def record_action(
        self,
        tool: str,
        args: Dict[str, Any],
        files: Optional[List[str]] = None,
        result: Any = None,
        error: Optional[str] = None
    ) -> ToolAction:
        """
        Record a tool action in the current transaction.

        Args:
            tool: Name of the tool
            args: Tool arguments
            files: Files affected by this action
            result: Result of the action
            error: Error message if action failed

        Returns:
            ToolAction object

        Raises:
            RuntimeError: If no transaction is active
        """
        if not self.current_transaction or self.current_transaction.status != TransactionStatus.ACTIVE:
            raise RuntimeError("No active transaction")

        files = files or []

        # Compute file hashes
        hash_before = self._compute_hash(files)

        action = ToolAction(
            tool=tool,
            timestamp=datetime.utcnow().isoformat(),
            args=args,
            files=files,
            hash_before=hash_before,
            result=result,
            error=error
        )

        # Backup files before modification (for file_restore method)
        if self.current_transaction.rollback_method == RollbackMethod.FILE_RESTORE and files:
            self._backup_files(files, self.current_transaction.tx_id)

        self.current_transaction.actions.append(action)

        # Update hash after action
        action.hash_after = self._compute_hash(files)

        # Update transaction log
        self._log_transaction(self.current_transaction)

        return action

    def commit(self) -> Transaction:
        """
        Commit the current transaction.

        Returns:
            Committed Transaction object

        Raises:
            RuntimeError: If no transaction is active
        """
        if not self.current_transaction or self.current_transaction.status != TransactionStatus.ACTIVE:
            raise RuntimeError("No active transaction to commit")

        self.current_transaction.status = TransactionStatus.COMMITTED
        self.current_transaction.committed_at = datetime.utcnow().isoformat()

        # Clean up backups
        if self.current_transaction.rollback_method == RollbackMethod.FILE_RESTORE:
            backup_dir = Path(self.current_transaction.rollback_data.get("backup_dir", ""))
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

        self._log_transaction(self.current_transaction)

        transaction = self.current_transaction
        self.current_transaction = None
        return transaction

    def abort(self, reason: Optional[str] = None) -> Transaction:
        """
        Abort the current transaction and rollback changes.

        Args:
            reason: Optional reason for aborting

        Returns:
            Aborted Transaction object

        Raises:
            RuntimeError: If no transaction is active
        """
        if not self.current_transaction or self.current_transaction.status != TransactionStatus.ACTIVE:
            raise RuntimeError("No active transaction to abort")

        self.current_transaction.status = TransactionStatus.ABORTED
        self.current_transaction.aborted_at = datetime.utcnow().isoformat()

        if reason:
            self.current_transaction.rollback_data["abort_reason"] = reason

        # Perform rollback
        self._rollback(self.current_transaction)

        self.current_transaction.status = TransactionStatus.ROLLED_BACK

        self._log_transaction(self.current_transaction)

        transaction = self.current_transaction
        self.current_transaction = None
        return transaction

    def _backup_files(self, files: List[str], tx_id: str):
        """Backup files before modification."""
        backup_dir = self._backup_dir / tx_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        for file_path in files:
            full_path = self.workspace_root / file_path

            if not full_path.exists():
                continue

            # Preserve directory structure in backup
            relative_path = Path(file_path)
            backup_path = backup_dir / relative_path

            backup_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.copy2(full_path, backup_path)
            except Exception as e:
                # Log but don't fail - backup is best-effort
                print(f"Warning: Failed to backup {file_path}: {e}")

    def _rollback(self, transaction: Transaction):
        """Perform rollback based on transaction's rollback method."""
        if transaction.rollback_method == RollbackMethod.GIT_CHECKOUT:
            self._rollback_git(transaction)
        elif transaction.rollback_method == RollbackMethod.FILE_RESTORE:
            self._rollback_file_restore(transaction)

    def _rollback_git(self, transaction: Transaction):
        """Rollback using git checkout."""
        ref = transaction.rollback_data.get("ref", "HEAD")

        # Get affected files
        affected_files = set()
        for action in transaction.actions:
            affected_files.update(action.files)

        if not affected_files:
            return

        # Checkout each file from git
        for file_path in affected_files:
            try:
                run_command_safe(
                    ["git", "checkout", ref, "--", file_path],
                    cwd=self.workspace_root,
                    timeout=30
                )
            except Exception as e:
                print(f"Warning: Failed to rollback {file_path}: {e}")

    def _rollback_file_restore(self, transaction: Transaction):
        """Rollback using file backups."""
        backup_dir = Path(transaction.rollback_data.get("backup_dir", ""))

        if not backup_dir.exists():
            print(f"Warning: Backup directory not found: {backup_dir}")
            return

        # Restore each backed up file
        for action in transaction.actions:
            for file_path in action.files:
                backup_path = backup_dir / file_path
                full_path = self.workspace_root / file_path

                if not backup_path.exists():
                    continue

                try:
                    # Restore file from backup
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_path, full_path)
                except Exception as e:
                    print(f"Warning: Failed to restore {file_path}: {e}")

        # Clean up backup directory
        shutil.rmtree(backup_dir, ignore_errors=True)

    def _prepare_git_rollback(self) -> Dict[str, Any]:
        """Prepare git rollback data."""
        try:
            # Get current HEAD
            result = run_command_safe(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                timeout=5
            )
            head_ref = (result.get("stdout") or "").strip()

            if result.get("rc") != 0 or not head_ref:
                return {
                    "ref": "HEAD",
                    "method": "git_checkout"
                }

            return {
                "ref": head_ref,
                "method": "git_checkout"
            }
        except Exception:
            # Fallback to HEAD if we can't get current ref
            return {
                "ref": "HEAD",
                "method": "git_checkout"
            }

    def _compute_hash(self, files: List[str]) -> str:
        """Compute combined hash of files."""
        if not files:
            return ""

        hasher = hashlib.sha256()

        for file_path in sorted(files):
            full_path = self.workspace_root / file_path

            if not full_path.exists():
                hasher.update(b"<file_not_found>")
                continue

            try:
                with open(full_path, "rb") as f:
                    hasher.update(f.read())
            except Exception:
                hasher.update(b"<read_error>")

        return hasher.hexdigest()

    def _log_transaction(self, transaction: Transaction):
        """Log transaction to JSONL file."""
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(transaction.to_dict()) + "\n")
        except Exception as e:
            print(f"Warning: Failed to log transaction: {e}")

    def get_transaction_history(self, limit: Optional[int] = None) -> List[Transaction]:
        """
        Get transaction history from log file.

        Args:
            limit: Optional limit on number of transactions to return

        Returns:
            List of Transaction objects (deduplicated, most recent first)
        """
        if not self.log_file.exists():
            return []

        # Use OrderedDict to preserve order while deduplicating
        from collections import OrderedDict
        tx_by_id = OrderedDict()

        try:
            with open(self.log_file, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        transaction = Transaction.from_dict(data)
                        # Update existing entry (last write wins)
                        if transaction.tx_id in tx_by_id:
                            del tx_by_id[transaction.tx_id]
                        tx_by_id[transaction.tx_id] = transaction
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Warning: Failed to read transaction log: {e}")
            return []

        # Convert to list (already in chronological order)
        transactions = list(tx_by_id.values())

        # Reverse to get most recent first
        transactions.reverse()

        if limit:
            transactions = transactions[:limit]

        return transactions

    def get_transaction_by_id(self, tx_id: str) -> Optional[Transaction]:
        """
        Get a specific transaction by ID.

        Args:
            tx_id: Transaction ID

        Returns:
            Transaction object or None if not found
        """
        transactions = self.get_transaction_history()

        for tx in transactions:
            if tx.tx_id == tx_id:
                return tx

        return None

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get transaction statistics.

        Returns:
            Dict with statistics
        """
        transactions = self.get_transaction_history()

        stats = {
            "total": len(transactions),
            "committed": sum(1 for tx in transactions if tx.status == TransactionStatus.COMMITTED),
            "aborted": sum(1 for tx in transactions if tx.status == TransactionStatus.ABORTED),
            "rolled_back": sum(1 for tx in transactions if tx.status == TransactionStatus.ROLLED_BACK),
            "total_actions": sum(len(tx.actions) for tx in transactions),
            "recent_transactions": [tx.tx_id for tx in transactions[:5]]
        }

        return stats
