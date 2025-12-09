#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Code reuse metrics tracking (Phase 3).

This module tracks metrics for code reuse vs. new file creation to measure
the effectiveness of reuse-first policies.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, field, asdict


@dataclass
class ReuseMetrics:
    """Metrics for code reuse tracking."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    task_description: str = ""
    files_created: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    new_files_list: List[str] = field(default_factory=list)
    modified_files_list: List[str] = field(default_factory=list)
    similarity_warnings: int = 0
    reuse_opportunities_found: int = 0
    reuse_opportunities_used: int = 0
    total_lines_added: int = 0
    total_lines_modified: int = 0
    reuse_ratio: float = 0.0  # modified / (created + modified)

    def calculate_reuse_ratio(self):
        """Calculate the reuse ratio."""
        total = self.files_created + self.files_modified
        if total > 0:
            self.reuse_ratio = self.files_modified / total
        else:
            self.reuse_ratio = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ReuseMetricsTracker:
    """Tracks code reuse metrics across sessions."""

    def __init__(self, metrics_file: str = ".rev-metrics/code_reuse.jsonl"):
        """Initialize metrics tracker.

        Args:
            metrics_file: Path to metrics file (JSONL format)
        """
        self.metrics_file = Path(metrics_file)
        self.current_session = ReuseMetrics()

    def start_task(self, task_description: str):
        """Start tracking a new task.

        Args:
            task_description: Description of the task
        """
        self.current_session = ReuseMetrics(task_description=task_description)

    def record_file_created(self, filepath: str, has_similar: bool = False):
        """Record a new file creation.

        Args:
            filepath: Path to the created file
            has_similar: Whether similar files were found
        """
        self.current_session.files_created += 1
        self.current_session.new_files_list.append(filepath)
        if has_similar:
            self.current_session.similarity_warnings += 1

    def record_file_modified(self, filepath: str):
        """Record a file modification.

        Args:
            filepath: Path to the modified file
        """
        self.current_session.files_modified += 1
        self.current_session.modified_files_list.append(filepath)

    def record_file_deleted(self, filepath: str):
        """Record a file deletion.

        Args:
            filepath: Path to the deleted file
        """
        self.current_session.files_deleted += 1

    def record_reuse_opportunity(self, was_used: bool = False):
        """Record a reuse opportunity.

        Args:
            was_used: Whether the reuse opportunity was actually used
        """
        self.current_session.reuse_opportunities_found += 1
        if was_used:
            self.current_session.reuse_opportunities_used += 1

    def finish_task(self) -> ReuseMetrics:
        """Finish tracking current task and save metrics.

        Returns:
            The completed metrics for the task
        """
        self.current_session.calculate_reuse_ratio()
        self._save_metrics()
        return self.current_session

    def _save_metrics(self):
        """Save metrics to JSONL file."""
        try:
            # Create directory if it doesn't exist
            self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

            # Append metrics to file
            with open(self.metrics_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(self.current_session.to_dict()) + '\n')
        except Exception as e:
            # Don't fail if metrics can't be saved
            print(f"  ⚠️  Failed to save reuse metrics: {e}")

    def get_summary(self, last_n: int = 10) -> Dict[str, Any]:
        """Get summary of recent reuse metrics.

        Args:
            last_n: Number of recent tasks to summarize

        Returns:
            Summary statistics
        """
        if not self.metrics_file.exists():
            return {
                "total_tasks": 0,
                "average_reuse_ratio": 0.0,
                "total_files_created": 0,
                "total_files_modified": 0,
                "message": "No metrics data available"
            }

        try:
            metrics_list = []
            with open(self.metrics_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        metrics_list.append(json.loads(line))

            # Get last N tasks
            recent = metrics_list[-last_n:] if len(metrics_list) > last_n else metrics_list

            total_created = sum(m['files_created'] for m in recent)
            total_modified = sum(m['files_modified'] for m in recent)
            avg_reuse_ratio = sum(m['reuse_ratio'] for m in recent) / len(recent) if recent else 0.0
            total_warnings = sum(m['similarity_warnings'] for m in recent)

            return {
                "total_tasks": len(recent),
                "average_reuse_ratio": avg_reuse_ratio,
                "total_files_created": total_created,
                "total_files_modified": total_modified,
                "total_similarity_warnings": total_warnings,
                "edit_to_create_ratio": f"{total_modified}:{total_created}" if total_created > 0 else "N/A",
                "message": f"Analyzed last {len(recent)} tasks"
            }
        except Exception as e:
            return {
                "error": f"Failed to load metrics: {e}"
            }

    def display_summary(self, last_n: int = 10):
        """Display a formatted summary of reuse metrics.

        Args:
            last_n: Number of recent tasks to summarize
        """
        summary = self.get_summary(last_n)

        print("\n" + "=" * 60)
        print("CODE REUSE METRICS SUMMARY")
        print("=" * 60)

        if "error" in summary:
            print(f"  ⚠️  {summary['error']}")
            return

        print(f"  📊 {summary['message']}")
        print(f"  📁 Files created: {summary['total_files_created']}")
        print(f"  ✏️  Files modified: {summary['total_files_modified']}")
        print(f"  📈 Edit-to-create ratio: {summary['edit_to_create_ratio']}")
        print(f"  🎯 Average reuse ratio: {summary['average_reuse_ratio']:.1%}")

        if summary.get('total_similarity_warnings', 0) > 0:
            print(f"  ⚠️  Similarity warnings: {summary['total_similarity_warnings']}")
            print(f"     (Files created despite similar files existing)")

        print("=" * 60)


# Global tracker instance
_metrics_tracker = None


def get_metrics_tracker() -> ReuseMetricsTracker:
    """Get the global metrics tracker instance."""
    global _metrics_tracker
    if _metrics_tracker is None:
        _metrics_tracker = ReuseMetricsTracker()
    return _metrics_tracker


def track_file_operation(operation: str, filepath: str, **kwargs):
    """Convenience function to track file operations.

    Args:
        operation: Type of operation ('create', 'modify', 'delete')
        filepath: Path to the file
        **kwargs: Additional arguments (e.g., has_similar for create)
    """
    tracker = get_metrics_tracker()

    if operation == 'create':
        tracker.record_file_created(filepath, kwargs.get('has_similar', False))
    elif operation == 'modify':
        tracker.record_file_modified(filepath)
    elif operation == 'delete':
        tracker.record_file_deleted(filepath)
