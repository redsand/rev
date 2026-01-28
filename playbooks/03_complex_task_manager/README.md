# Playbook 03: Complex - Async Task Manager with Inheritance

## Level: Complex

## Goal
Implement an asynchronous task management system with inheritance, decorators, and error handling.

## Initial State
- Package structure with interfaces
- Empty implementations to fill in
- Tests that will pass after implementation

## Task
Implement a task management system with the following components:

### `models.py`:
- Abstract `Task` class with `execute()` and `cancel()` methods
- `AsyncTask` subclass for async operations
- `RetryableTask` subclass with retry logic
- `TaskStatus` enum (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
- `TaskResult` dataclass for task outcomes

### `decorators.py`:
- `@timeout(seconds)` decorator to enforce task timeout
- `@retry(max_attempts, delay)` decorator for retry logic
- `@log_execution(logger)` decorator for logging
- `@validate_input(**validators)` decorator for input validation

### `scheduler.py`:
- `TaskScheduler` class with async task scheduling
- `schedule_task(task: Task, delay: float)` method
- `cancel_task(task_id: str)` method
- `get_task_status(task_id: str) -> TaskStatus`
- `get_all_tasks() -> List[Task]`
- Concurrent task execution support

### `validators.py`:
- Input validation functions and classes
- `Validator` base class
- `RangeValidator`, `TypeValidator`, `CustomValidator`

### `exceptions.py`:
- `TaskTimeoutError`, `TaskExecutionError`, `InvalidTaskError`

## Constraints
- Use Python's `asyncio` for async operations
- All methods must have proper type hints
- Use `abc` module for abstract classes
- Thread-safe operations where needed
- Max complexity: O(n log n) for scheduling operations

## Success Criteria
- All tests pass including async tests
- Code coverage > 90%
- Proper error handling with specific exceptions
- No linting errors

## Validation
Run: `pytest test_task_manager.py -v --asyncio-mode=auto`