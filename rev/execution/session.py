#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session management and summarization for rev.

This module provides comprehensive session summarization to keep context windows
small in long-running sessions. Features include:
- Automatic session tracking
- Rich summarization (tasks, tools, code changes, outcomes)
- Manual and automatic summary triggers
- Session persistence (save/load summaries)
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class SessionSummary:
    """Comprehensive session summary for context window optimization."""

    # Session metadata
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None

    # Task tracking
    tasks_completed: List[str] = field(default_factory=list)
    tasks_failed: List[str] = field(default_factory=list)
    total_tasks: int = 0

    # Tool usage
    tools_used: Dict[str, int] = field(default_factory=dict)  # tool_name -> count
    total_tool_calls: int = 0

    # Code changes
    files_modified: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    files_deleted: List[str] = field(default_factory=list)

    # Test results
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0

    # Git operations
    commits_made: List[str] = field(default_factory=list)  # commit messages

    # Message statistics
    message_count: int = 0
    tokens_estimated: int = 0

    # Outcomes
    success: bool = True
    error_messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionSummary':
        """Create SessionSummary from dictionary."""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> 'SessionSummary':
        """Create SessionSummary from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def finalize(self):
        """Finalize the session summary (calculate duration, etc.)."""
        if self.end_time is None:
            self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time

    def get_concise_summary(self) -> str:
        """Get a concise text summary for context window optimization.

        This is optimized for minimal token usage while preserving key information.
        """
        parts = []

        # Header
        duration = self.duration_seconds or (time.time() - self.start_time)
        parts.append(f"## Session Summary ({duration:.1f}s)")

        # Task summary
        if self.total_tasks > 0:
            parts.append(f"\n### Tasks ({self.total_tasks} total)")
            parts.append(f"✓ Completed: {len(self.tasks_completed)}")
            if self.tasks_failed:
                parts.append(f"✗ Failed: {len(self.tasks_failed)}")

            # List completed tasks (max 10)
            if self.tasks_completed:
                parts.append("\nCompleted:")
                for task in self.tasks_completed[:10]:
                    parts.append(f"  • {task[:80]}")
                if len(self.tasks_completed) > 10:
                    parts.append(f"  ... and {len(self.tasks_completed) - 10} more")

        # Tool usage
        if self.tools_used:
            parts.append(f"\n### Tools ({self.total_tool_calls} calls)")
            # Top 10 most used tools
            top_tools = sorted(self.tools_used.items(), key=lambda x: x[1], reverse=True)[:10]
            parts.append(", ".join([f"{name}({count})" for name, count in top_tools]))

        # Code changes
        if self.files_modified or self.files_created or self.files_deleted:
            parts.append("\n### Code Changes")
            if self.files_created:
                parts.append(f"Created: {len(self.files_created)} files")
            if self.files_modified:
                parts.append(f"Modified: {len(self.files_modified)} files")
            if self.files_deleted:
                parts.append(f"Deleted: {len(self.files_deleted)} files")

        # Test results
        if self.tests_run > 0:
            parts.append(f"\n### Tests")
            parts.append(f"Run: {self.tests_run}, Passed: {self.tests_passed}, Failed: {self.tests_failed}")

        # Git commits
        if self.commits_made:
            parts.append(f"\n### Git Commits ({len(self.commits_made)})")
            for msg in self.commits_made[:5]:
                parts.append(f"  • {msg[:80]}")

        # Errors
        if self.error_messages:
            parts.append(f"\n### Errors ({len(self.error_messages)})")
            for err in self.error_messages[:3]:
                parts.append(f"  • {err[:100]}")

        return "\n".join(parts)

    def get_detailed_summary(self) -> str:
        """Get a detailed text summary with all information."""
        parts = [self.get_concise_summary()]

        # Add detailed file lists if not too many
        if len(self.files_modified) <= 20:
            parts.append("\n### Modified Files (detailed)")
            for f in self.files_modified:
                parts.append(f"  • {f}")

        if len(self.files_created) <= 20:
            parts.append("\n### Created Files (detailed)")
            for f in self.files_created:
                parts.append(f"  • {f}")

        # Add message statistics
        parts.append(f"\n### Message Statistics")
        parts.append(f"Messages: {self.message_count}")
        parts.append(f"Estimated tokens: {self.tokens_estimated}")

        return "\n".join(parts)


class SessionTracker:
    """Tracks session activity and generates summaries."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"session_{int(time.time())}"
        self.summary = SessionSummary(
            session_id=self.session_id,
            start_time=time.time()
        )

    def track_task_started(self, task_description: str):
        """Track when a task starts."""
        self.summary.total_tasks += 1

    def track_task_completed(self, task_description: str):
        """Track when a task completes successfully."""
        if task_description not in self.summary.tasks_completed:
            self.summary.tasks_completed.append(task_description)

    def track_task_failed(self, task_description: str, error: str):
        """Track when a task fails."""
        if task_description not in self.summary.tasks_failed:
            self.summary.tasks_failed.append(task_description)
        if error not in self.summary.error_messages:
            self.summary.error_messages.append(error)
        self.summary.success = False

    def track_tool_call(self, tool_name: str, tool_args: Dict[str, Any]):
        """Track tool usage."""
        self.summary.total_tool_calls += 1
        self.summary.tools_used[tool_name] = self.summary.tools_used.get(tool_name, 0) + 1

        # Track specific file operations
        if tool_name == "write_file":
            path = tool_args.get("path", "")
            if path and path not in self.summary.files_created:
                self.summary.files_created.append(path)

        elif tool_name in ["replace_in_file", "append_to_file"]:
            path = tool_args.get("path", "")
            if path and path not in self.summary.files_modified:
                self.summary.files_modified.append(path)

        elif tool_name == "delete_file":
            path = tool_args.get("path", "")
            if path and path not in self.summary.files_deleted:
                self.summary.files_deleted.append(path)

        # Track git commits
        elif tool_name == "git_commit":
            msg = tool_args.get("message", "")
            if msg:
                self.summary.commits_made.append(msg)

    def track_test_results(self, result: str):
        """Track test execution results."""
        try:
            result_data = json.loads(result)
            self.summary.tests_run += 1

            if result_data.get("rc", 0) == 0:
                self.summary.tests_passed += 1
            else:
                self.summary.tests_failed += 1
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Log malformed test results but don't fail
            pass

    def track_messages(self, message_count: int, estimated_tokens: Optional[int] = None):
        """Track message statistics."""
        self.summary.message_count = message_count
        if estimated_tokens is not None:
            self.summary.tokens_estimated = estimated_tokens

    def estimate_tokens(self, messages: List[Dict]) -> int:
        """Estimate token count from messages (rough approximation)."""
        # Rough estimate: ~4 chars per token
        total_chars = sum(
            len(str(msg.get("content", "")))
            for msg in messages
        )
        return total_chars // 4

    def get_summary(self, detailed: bool = False) -> str:
        """Get current session summary."""
        if detailed:
            return self.summary.get_detailed_summary()
        return self.summary.get_concise_summary()

    def finalize(self) -> SessionSummary:
        """Finalize and return the session summary."""
        self.summary.finalize()
        return self.summary

    def save_to_file(self, path: Optional[Path] = None) -> Path:
        """Save session summary to a file.

        Args:
            path: Optional path to save to. If None, uses default location.

        Returns:
            Path where summary was saved
        """
        if path is None:
            # Default location: .rev_sessions/session_<id>.json
            sessions_dir = Path.cwd() / ".rev_sessions"
            sessions_dir.mkdir(exist_ok=True)
            path = sessions_dir / f"{self.session_id}.json"

        self.summary.finalize()

        with open(path, 'w') as f:
            f.write(self.summary.to_json())

        return path

    def emit_metrics(self, path: Optional[Path] = None) -> Path:
        """Emit structured metrics to JSONL for evaluation and monitoring.

        This implements the Evaluation & Monitoring pattern by capturing
        agent trajectories, tool usage, and outcomes over time.

        Args:
            path: Optional path to metrics file. If None, uses default location.

        Returns:
            Path where metrics were written
        """
        import json

        if path is None:
            # Default location: .rev-metrics/metrics.jsonl
            metrics_dir = Path.cwd() / ".rev-metrics"
            metrics_dir.mkdir(exist_ok=True)
            path = metrics_dir / "metrics.jsonl"

        # Ensure summary is finalized
        self.summary.finalize()

        # Create metrics record
        metrics = {
            "session_id": self.session_id,
            "timestamp": self.summary.start_time,
            "duration_seconds": self.summary.duration_seconds,
            "tasks": {
                "total": self.summary.total_tasks,
                "completed": len(self.summary.tasks_completed),
                "failed": len(self.summary.tasks_failed),
                "success_rate": len(self.summary.tasks_completed) / max(self.summary.total_tasks, 1)
            },
            "tools": {
                "total_calls": self.summary.total_tool_calls,
                "unique_tools": len(self.summary.tools_used),
                "by_tool": dict(self.summary.tools_used)
            },
            "tests": {
                "total_runs": self.summary.tests_run,
                "passed": self.summary.tests_passed,
                "failed": self.summary.tests_failed,
                "pass_rate": self.summary.tests_passed / max(self.summary.tests_run, 1) if self.summary.tests_run > 0 else None
            },
            "files": {
                "created": len(self.summary.files_created),
                "modified": len(self.summary.files_modified),
                "deleted": len(self.summary.files_deleted)
            },
            "git": {
                "commits": len(self.summary.commits_made)
            },
            "messages": {
                "count": self.summary.message_count,
                "tokens_estimated": self.summary.tokens_estimated
            },
            "success": self.summary.success,
            "errors": len(self.summary.error_messages)
        }

        # Append to JSONL file (newline-delimited JSON)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(metrics) + '\n')

        return path

    @classmethod
    def load_from_file(cls, path: Path) -> 'SessionTracker':
        """Load session tracker from a saved file."""
        with open(path, 'r') as f:
            summary = SessionSummary.from_json(f.read())

        tracker = cls(session_id=summary.session_id)
        tracker.summary = summary
        return tracker


def create_message_summary_from_history(messages: List[Dict], tracker: Optional[SessionTracker] = None) -> str:
    """Create a concise summary from message history.

    This is used for automatic context window optimization.

    Args:
        messages: List of message dictionaries
        tracker: Optional SessionTracker for enhanced summary

    Returns:
        Concise summary string optimized for minimal tokens
    """
    if tracker:
        # Use tracked information for accurate summary
        tracker.track_messages(len(messages), tracker.estimate_tokens(messages))
        return tracker.get_summary(detailed=False)

    # Fallback: basic message-based summarization
    tasks = []
    tools = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user" and "Task:" in content:
            task_line = content.split("Task:", 1)[1].split("\n")[0].strip()
            if task_line and task_line not in tasks:
                tasks.append(task_line)

        if role == "tool":
            tool_name = msg.get("name", "unknown")
            if tool_name not in tools:
                tools.append(tool_name)

    parts = [f"## Session Summary ({len(messages)} messages)"]

    if tasks:
        parts.append(f"\n### Tasks ({len(tasks)})")
        for task in tasks[:10]:
            parts.append(f"  • {task[:80]}")
        if len(tasks) > 10:
            parts.append(f"  ... and {len(tasks) - 10} more")

    if tools:
        parts.append(f"\n### Tools Used: {', '.join(tools[:15])}")

    return "\n".join(parts)
