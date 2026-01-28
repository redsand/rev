#!/usr/bin/env python3
"""
Tests for the complex task manager system.
"""

import pytest
import asyncio
from datetime import datetime
from models import Task, AsyncTask, RetryableTask, TaskStatus, TaskResult
from scheduler import TaskScheduler
from decorators import timeout, retry, log_execution, TaskTimeoutError
from validators import (
    RangeValidator,
    TypeValidator,
    LengthValidator,
    RegexValidator,
    CustomValidator,
    ValidationError,
)


# ============================================================================
# Test Models
# ============================================================================

class TestTask:
    """Test Task base class."""

    def test_task_initialization(self):
        """Test creating a task."""
        task = Task(task_id="task1", name="Test Task")
        assert task.task_id == "task1"
        assert task.name == "Test Task"
        assert task.status == TaskStatus.PENDING
        assert task.result is None

    def test_task_status_callback(self):
        """Test status change callback."""
        task = Task(task_id="task1", name="Test")
        callback_called = []

        def callback(old, new):
            callback_called.append((old, new))

        task.add_status_callback(callback)
        # Trigger status change
        task._set_status(TaskStatus.RUNNING)
        assert len(callback_called) > 0


class TestRetryableTask:
    """Test RetryableTask class."""

    def test_retryable_task_initialization(self):
        """Test creating a retryable task."""
        task = RetryableTask(task_id="task1", name="Test", max_retries=3, retry_delay=1.0)
        assert task.max_retries == 3
        assert task.retry_delay == 1.0
        assert task.attempt_count == 0


class TestAsyncTask:
    """Test AsyncTask class."""

    @pytest.mark.asyncio
    async def test_async_task_execution(self):
        """Test async task can be executed."""
        class SimpleAsyncTask(AsyncTask):
            async def execute_async(self):
                await asyncio.sleep(0.01)
                return TaskResult(success=True, value="done")

            def cancel(self):
                return False

        task = SimpleAsyncTask(task_id="task1", name="Test")
        result = await task.execute_async()
        assert result.success is True
        assert result.value == "done"


# ============================================================================
# Test Decorators
# ============================================================================

class TestTimeoutDecorator:
    """Test @timeout decorator."""

    def test_timeout_success(self):
        """Test timeout allows successful execution within limit."""
        @timeout(seconds=1.0)
        def fast_function():
            return "success"

        result = fast_function()
        assert result == "success"

    def test_timeout_raises(self):
        """Test timeout raises exception for slow execution."""
        @timeout(seconds=0.01)
        def slow_function():
            import time
            time.sleep(0.1)

        with pytest.raises((TaskTimeoutError, TimeoutError)):
            slow_function()


class TestRetryDecorator:
    """Test @retry decorator."""

    def test_retry_on_failure(self):
        """Test retry retries on failure."""
        attempts = []

        @retry(max_attempts=3, delay=0.01)
        def flaky_function():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("fail")
            return "success"

        result = flaky_function()
        assert result == "success"
        assert len(attempts) == 3

    def test_retry_success_on_first_try(self):
        """Test retry doesn't retry on first success."""
        attempts = []

        @retry(max_attempts=3, delay=0.01)
        def stable_function():
            attempts.append(1)
            return "success"

        result = stable_function()
        assert result == "success"
        assert len(attempts) == 1


# ============================================================================
# Test Scheduler
# ============================================================================

class TestTaskScheduler:
    """Test TaskScheduler class."""

    @pytest.mark.asyncio
    async def test_scheduler_initialization(self):
        """Test creating scheduler."""
        scheduler = TaskScheduler(max_concurrent_tasks=5)
        stats = scheduler.get_statistics()
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_schedule_task(self):
        """Test scheduling a task."""
        class SimpleTask(Task):
            def __init__(self):
                super().__init__(task_id="task1", name="Test")

            def execute(self):
                return TaskResult(success=True, value="done")

            def cancel(self):
                return False

        scheduler = TaskScheduler(max_concurrent_tasks=5)
        task_id = scheduler.schedule_task(SimpleTask())
        assert task_id is not None

        await scheduler.wait_for_all()
        assert scheduler.get_task_status(task_id) == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        """Test cancelling a scheduled task."""
        class SlowTask(Task):
            def __init__(self):
                super().__init__(task_id="task1", name="Test")

            def execute(self):
                import time
                time.sleep(1)
                return TaskResult(success=True)

            def cancel(self):
                return False

        scheduler = TaskScheduler(max_concurrent_tasks=5)
        task_id = scheduler.schedule_task(SlowTask(), delay=1.0)
        result = scheduler.cancel_task(task_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_concurrent_tasks(self):
        """Test concurrent task execution."""
        class CounterTask(Task):
            def __init__(self, task_id):
                super().__init__(task_id=task_id, name="Counter")
                self.counter = 0

            def execute(self):
                import time
                time.sleep(0.01)
                self.counter += 1
                return TaskResult(success=True, value=self.counter)

            def cancel(self):
                return False

        scheduler = TaskScheduler(max_concurrent_tasks=10)
        tasks = [CounterTask(f"task{i}") for i in range(5)]

        for task in tasks:
            scheduler.schedule_task(task)

        await scheduler.wait_for_all()

        for task in tasks:
            assert task.counter == 1


# ============================================================================
# Test Validators
# ============================================================================

class TestValidators:
    """Test validator classes."""

    def test_range_validator(self):
        """Test RangeValidator."""
        validator = RangeValidator(min_val=0, max_val=100)

        assert validator.validate(50, "value") == 50
        assert validator.validate(0, "value") == 0
        assert validator.validate(100, "value") == 100

        with pytest.raises(ValidationError):
            validator.validate(-1, "value")
        with pytest.raises(ValidationError):
            validator.validate(101, "value")

    def test_type_validator(self):
        """Test TypeValidator."""
        validator = TypeValidator(int)

        assert validator.validate(42, "value") == 42
        assert validator.validate(0, "value") == 0

        with pytest.raises(ValidationError):
            validator.validate("not an int", "value")

    def test_length_validator(self):
        """Test LengthValidator."""
        validator = LengthValidator(min_length=3, max_length=10)

        assert validator.validate("abc", "value") == "abc"
        assert validator.validate("abcdefghij", "value") == "abcdefghij"

        with pytest.raises(ValidationError):
            validator.validate("ab", "value")
        with pytest.raises(ValidationError):
            validator.validate("abcdefghijk", "value")

    def test_custom_validator(self):
        """Test CustomValidator."""
        validator = CustomValidator(
            lambda x: x > 0,
            "Value must be positive"
        )

        assert validator.validate(1, "value") == 1
        assert validator.validate(100, "value") == 100

        with pytest.raises(ValidationError):
            validator.validate(0, "value")
        with pytest.raises(ValidationError):
            validator.validate(-1, "value")