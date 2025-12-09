#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
State persistence and recovery for chain execution.

This module provides automatic state persistence with:
- Auto-save after each task completion
- Recovery from interruptions
- Progress tracking
- Resume capability
"""

import os
import json
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import uuid

from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.debug_logger import get_logger


class StateManager:
    """Manages execution state persistence and recovery."""

    def __init__(
        self,
        plan: ExecutionPlan,
        checkpoint_dir: str = ".rev_checkpoints",
        auto_save: bool = True
    ):
        """Initialize state manager.

        Args:
            plan: ExecutionPlan to manage
            checkpoint_dir: Directory for checkpoint files
            auto_save: Enable automatic checkpoint saving
        """
        self.plan = plan
        self.checkpoint_dir = Path(checkpoint_dir)
        self.auto_save = auto_save
        self.logger = get_logger()
        self._lock = threading.Lock()
        self._last_checkpoint: Optional[str] = None
        self._checkpoint_count = 0

        # Create checkpoint directory
        self.checkpoint_dir.mkdir(exist_ok=True, parents=True)

        # Generate session ID using a UUID4 for uniqueness across runs
        self.session_id = uuid.uuid4().hex

    def save_checkpoint(
        self,
        reason: str = "manual",
        force: bool = False
    ) -> Optional[str]:
        """Save current execution state to checkpoint.

        Args:
            reason: Reason for checkpoint (manual, task_complete, interrupt, etc.)
            force: Force save even if auto_save is disabled

        Returns:
            Path to checkpoint file, or None if save was skipped
        """
        if not self.auto_save and not force:
            return None

        with self._lock:
            try:
                self._checkpoint_count += 1
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                # Filename now includes the GUID‑based session_id for clear identification
                filename = f"checkpoint_{self.session_id}_{self._checkpoint_count:04d}_{timestamp}.json"
                filepath = self.checkpoint_dir / filename

                checkpoint_data = {
                    "version": "1.0",
                    "session_id": self.session_id,
                    "checkpoint_number": self._checkpoint_count,
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason,
                    "plan": self.plan.to_dict(),
                    "resume_info": self._get_resume_info()
                }

                with open(filepath, "w") as f:
                    json.dump(checkpoint_data, f, indent=2)

                self._last_checkpoint = str(filepath)

                self.logger.log("state", "CHECKPOINT_SAVED", {
                    "filepath": str(filepath),
                    "reason": reason,
                    "checkpoint_number": self._checkpoint_count,
                    "tasks_completed": sum(1 for t in self.plan.tasks if t.status == TaskStatus.COMPLETED),
                    "tasks_total": len(self.plan.tasks)
                }, "INFO")

                return str(filepath)

            except Exception as e:
                self.logger.log("state", "CHECKPOINT_SAVE_ERROR", {
                    "error": str(e),
                    "reason": reason
                }, "ERROR")
                print(f"⚠️  Warning: Failed to save checkpoint: {e}")
                return None

    def _get_resume_info(self) -> Dict[str, Any]:
        """Get information needed to resume execution.

        Returns:
            Dictionary with resume information
        """
        completed = [t for t in self.plan.tasks if t.status == TaskStatus.COMPLETED]
        pending = [t for t in self.plan.tasks if t.status == TaskStatus.PENDING]
        stopped = [t for t in self.plan.tasks if t.status == TaskStatus.STOPPED]
        failed = [t for t in self.plan.tasks if t.status == TaskStatus.FAILED]

        next_task = None
        if stopped:
            next_task = stopped[0].description
        elif pending:
            next_task = pending[0].description

        return {
            "tasks_completed": len(completed),
            "tasks_pending": len(pending),
            "tasks_stopped": len(stopped),
            "tasks_failed": len(failed),
            "tasks_total": len(self.plan.tasks),
            "next_task": next_task,
            "progress_percent": (len(completed) / len(self.plan.tasks) * 100) if self.plan.tasks else 0
        }

    def on_task_started(self, task: Task):
        """Handle task start event.

        Args:
            task: Task that started
        """
        self.logger.log("state", "TASK_STARTED", {
            "task_id": task.task_id,
            "description": task.description,
            "action_type": task.action_type
        }, "INFO")

    def on_task_completed(self, task: Task):
        """Handle task completion event.

        Args:
            task: Task that completed
        """
        self.logger.log("state", "TASK_COMPLETED", {
            "task_id": task.task_id,
            "description": task.description,
            "action_type": task.action_type
        }, "INFO")

        if self.auto_save:
            self.save_checkpoint(reason="task_complete")

    def on_task_failed(self, task: Task):
        """Handle task failure event.

        Args:
            task: Task that failed
        """
        self.logger.log("state", "TASK_FAILED", {
            "task_id": task.task_id,
            "description": task.description,
            "error": task.error,
            "action_type": task.action_type
        }, "ERROR")

        if self.auto_save:
            self.save_checkpoint(reason="task_failed")

    def on_interrupt(self, task: Optional[Task] = None, token_usage: Optional[Dict[str, int]] = None):
        """Handle execution interrupt.

        Args:
            task: Task that was running when interrupted (if any)
        """
        self.logger.log("state", "EXECUTION_INTERRUPTED", {
            "task_id": task.task_id if task else None,
            "description": task.description if task else None
        }, "WARNING")

        # Always save on interrupt
        checkpoint_path = self.save_checkpoint(reason="interrupt", force=True)

        if checkpoint_path:

            print("\n" + "=" * 60)
            print("⚠️  EXECUTION INTERRUPTED")
            print("=" * 60)
            print(f"\n✓ State saved to: {checkpoint_path}")
            print("\nTo resume from where you left off, run:")
            print(f"\n  rev --resume {checkpoint_path}")
            print("\nOr to resume from the latest checkpoint:")

            if token_usage:
                total = token_usage.get("total", 0)
                prompt = token_usage.get("prompt", 0)
                completion = token_usage.get("completion", 0)
                print("\nToken Usage:")
                print(f"  Total: {total:,}")
                print(f"  Prompt: {prompt:,}")
                print(f"  Completion: {completion:,}")




            print("\n" + "=" * 60)
        return checkpoint_path

    def get_last_checkpoint(self) -> Optional[str]:
        """Get path to the last checkpoint.

        Returns:
            Path to last checkpoint, or None if no checkpoints
        """
        return self._last_checkpoint

    def list_checkpoints(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent checkpoints.

        Args:
            limit: Maximum number of checkpoints to return

        Returns:
            List of checkpoint info dictionaries
        """
        checkpoints = []

        if not self.checkpoint_dir.exists():
            return checkpoints

        for filepath in sorted(self.checkpoint_dir.glob("checkpoint_*.json"), reverse=True):
            if len(checkpoints) >= limit:
                break

            try:
                with open(filepath, "r") as f:
                    data = json.load(f)

                resume_info = data.get("resume_info", {})

                checkpoints.append({
                    "filepath": str(filepath),
                    "filename": filepath.name,
                    "timestamp": data.get("timestamp"),
                    "reason": data.get("reason", "unknown"),
                    "session_id": data.get("session_id"),
                    "checkpoint_number": data.get("checkpoint_number"),
                    "tasks_completed": resume_info.get("tasks_completed", 0),
                    "tasks_total": resume_info.get("tasks_total", 0),
                    "progress_percent": resume_info.get("progress_percent", 0),
                    "next_task": resume_info.get("next_task")
                })
            except Exception as e:
                self.logger.log("state", "CHECKPOINT_READ_ERROR", {
                    "filepath": str(filepath),
                    "error": str(e)
                }, "WARNING")

        return checkpoints

    def clean_old_checkpoints(self, keep_last: int = 10):
        """Remove old checkpoints, keeping only the most recent.

        Args:
            keep_last: Number of recent checkpoints to keep
        """
        if not self.checkpoint_dir.exists():
            return

        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"), reverse=True)

        for filepath in checkpoints[keep_last:]:
            try:
                filepath.unlink()
                self.logger.log("state", "CHECKPOINT_CLEANED", {
                    "filepath": str(filepath)
                }, "INFO")
            except Exception as e:
                self.logger.log("state", "CHECKPOINT_CLEAN_ERROR", {
                    "filepath": str(filepath),
                    "error": str(e)
                }, "WARNING")

    @staticmethod
    def load_from_checkpoint(checkpoint_path: str) -> ExecutionPlan:
        """Load an execution plan from a checkpoint file.

        Args:
            checkpoint_path: Path to checkpoint file

        Returns:
            Restored ExecutionPlan

        Raises:
            FileNotFoundError: If checkpoint doesn't exist
            json.JSONDecodeError: If checkpoint is corrupted
        """
        logger = get_logger()

        try:
            with open(checkpoint_path, "r") as f:
                data = json.load(f)

            plan = ExecutionPlan.from_dict(data["plan"])

            logger.log("state", "CHECKPOINT_LOADED", {
                "filepath": checkpoint_path,
                "session_id": data.get("session_id"),
                "checkpoint_number": data.get("checkpoint_number"),
                "timestamp": data.get("timestamp"),
                "tasks_total": len(plan.tasks)
            }, "INFO")

            return plan

        except Exception as e:
            logger.log("state", "CHECKPOINT_LOAD_ERROR", {
                "filepath": checkpoint_path,
                "error": str(e),
                "error_type": type(e).__name__
            }, "ERROR")
            raise

    @staticmethod
    def find_latest_checkpoint(checkpoint_dir: str = ".rev_checkpoints") -> Optional[str]:
        """Find the most recent checkpoint file.

        Args:
            checkpoint_dir: Directory containing checkpoints

        Returns:
            Path to latest checkpoint, or None if no checkpoints found
        """
        checkpoint_path = Path(checkpoint_dir)

        if not checkpoint_path.exists():
            return None

        checkpoints = sorted(checkpoint_path.glob("checkpoint_*.json"), reverse=True)

        if checkpoints:
            return str(checkpoints[0])

        return None

    def print_resume_info(self, checkpoint_path: Optional[str] = None):
        """Print information about how to resume execution.

        Args:
            checkpoint_path: Path to specific checkpoint (uses last if None)
        """
        if checkpoint_path is None:
            checkpoint_path = self._last_checkpoint

        if not checkpoint_path:
            print("No checkpoint available for resumption")
            return

        try:
            with open(checkpoint_path, "r") as f:
                data = json.load(f)

            resume_info = data.get("resume_info", {})


            print("RESUME INFORMATION")
            print("=" * 60)
            print(f"\nCheckpoint: {checkpoint_path}")
            print(f"Saved at: {data.get('timestamp')}")
            print(f"Reason: {data.get('reason')}")
            print(f"\nProgress: {resume_info.get('tasks_completed', 0)}/{resume_info.get('tasks_total', 0)} tasks completed ({resume_info.get('progress_percent', 0):.1f}%)")

            if resume_info.get('tasks_stopped', 0) > 0:
                print(f"Stopped tasks: {resume_info['tasks_stopped']}")
            if resume_info.get('tasks_failed', 0) > 0:
                print(f"Failed tasks: {resume_info['tasks_failed']}")

            if resume_info.get('next_task'):
                print(f"\nNext task: {resume_info['next_task']}")

            print("\nTo resume:")
            print(f"  rev --resume {checkpoint_path}")
            print("\nOr:")
            print("  rev --resume  (uses latest checkpoint)")
            print("=" * 60)

        except Exception as e:
            print(f"Error reading checkpoint: {e}")
