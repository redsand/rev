"""
Task models and status enums.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Callable, Awaitable


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Result of task execution."""
    success: bool
    value: Any = None
    error: Optional[Exception] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Task(ABC):
    """Abstract base class for all tasks."""

    def __init__(self, task_id: str, name: str = ""):
        self.task_id = task_id
        self.name = name
        self.status = TaskStatus.PENDING
        self.result: Optional[TaskResult] = None
        self.created_at: datetime = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._on_status_change: List[Callable[[TaskStatus, TaskStatus], None]] = []

    @abstractmethod
    def execute(self) -> TaskResult:
        """Execute the task.

        Returns:
            TaskResult with execution outcome
        """
        # TODO: Implement in subclasses
        pass

    @abstractmethod
    def cancel(self) -> bool:
        """Cancel the task.

        Returns:
            True if cancelled, False if already completed
        """
        # TODO: Implement in subclasses
        pass

    def add_status_callback(self, callback: Callable[[TaskStatus, TaskStatus], None]):
        """Add callback for status changes.

        Args:
            callback: Function called with (old_status, new_status)
        """
        # TODO: Implement
        pass

    def _set_status(self, new_status: TaskStatus) -> None:
        """Internal method to change status and notify callbacks.

        Args:
            new_status: New status to set
        """
        # TODO: Implement
        pass


class AsyncTask(Task):
    """Async task that can be awaited."""

    async def execute_async(self) -> TaskResult:
        """Execute the task asynchronously.

        Returns:
            TaskResult with execution outcome
        """
        # TODO: Implement in subclasses
        pass

    def execute(self) -> TaskResult:
        """Synchronous wrapper - runs async task in event loop."""
        # TODO: Implement
        pass

    def cancel(self) -> bool:
        # TODO: Implement with async cancellation
        pass


class RetryableTask(Task):
    """Task with automatic retry logic on failure."""

    def __init__(self, task_id: str, name: str = "", max_retries: int = 3, retry_delay: float = 1.0):
        super().__init__(task_id, name)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.attempt_count = 0

    def execute(self) -> TaskResult:
        """Execute with retry logic.

        Returns:
            TaskResult with execution outcome
        """
        # TODO: Implement retry loop
        pass

    def should_retry(self, error: Exception) -> bool:
        """Determine if execution should be retried.

        Args:
            error: The exception that occurred

        Returns:
            True if should retry
        """
        # TODO: Implement in subclasses
        return True