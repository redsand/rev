"""
Custom exceptions for task manager.
"""


class TaskManagerError(Exception):
    """Base exception for task manager errors."""
    pass


class InvalidTaskError(TaskManagerError):
    """Raised when an invalid task is provided."""

    def __init__(self, task_id: str, reason: str):
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"Invalid task '{task_id}': {reason}")


class TaskNotFoundError(TaskManagerError):
    """Raised when a task is not found."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


class TaskExecutionError(TaskManagerError):
    """Raised when a task fails during execution."""

    def __init__(self, task_id: str, error: Exception):
        self.task_id = task_id
        self.error = error
        super().__init__(f"Task execution failed for '{task_id}': {error}")


class TaskTimeoutError(TaskManagerError):
    """Raised when a task exceeds its timeout."""

    def __init__(self, task_id: str, timeout_seconds: float):
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Task '{task_id}' timed out after {timeout_seconds} seconds")


class SchedulerFullError(TaskManagerError):
    """Raised when scheduler cannot accept more tasks."""

    def __init__(self, max_capacity: int):
        self.max_capacity = max_capacity
        super().__init__(f"Scheduler is full (max capacity: {max_capacity})")