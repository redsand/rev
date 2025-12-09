# rev - Testing Strategy and Test Development Guide

## Overview

This guide provides comprehensive information on testing strategy, how to write new tests, and how to improve test coverage for the rev codebase.

**Current Status:**
- **136 tests** in test suite
- **80% code coverage** (production-ready)
- **99% test code coverage** (tests are well-tested)
- **100% pass rate**

## Table of Contents

- [Testing Philosophy](#testing-philosophy)
- [Test Structure](#test-structure)
- [Writing New Tests](#writing-new-tests)
- [Test Categories](#test-categories)
- [Coverage Gaps](#coverage-gaps)
- [Mocking Strategy](#mocking-strategy)
- [Best Practices](#best-practices)
- [Running Tests](#running-tests)

## Testing Philosophy

### Goals

1. **Reliability**: Tests should pass consistently
2. **Isolation**: Each test should be independent
3. **Coverage**: Aim for 80%+ code coverage
4. **Speed**: Tests should run quickly (< 10 seconds total)
5. **Clarity**: Tests should be readable and maintainable

### Test Pyramid

```
        ┌───────────────┐
        │  Integration  │  10% - End-to-end workflows
        │     Tests     │
        ├───────────────┤
        │  Integration  │  30% - Module interactions
        │     Tests     │
        ├───────────────┤
        │     Unit      │  60% - Individual functions
        │     Tests     │
        └───────────────┘
```

**Current Distribution:**
- **Unit Tests**: ~80 tests (functions, classes, utilities)
- **Integration Tests**: ~40 tests (agent coordination, tool execution)
- **End-to-End Tests**: ~16 tests (full planning → execution → validation)

## Test Structure

### Test File Organization

```
tests/
└── test_agent_min.py    # Main test file (136 tests)
    ├── File Operations Tests (25 tests)
    ├── Git Operations Tests (18 tests)
    ├── Code Operations Tests (12 tests)
    ├── Task Management Tests (15 tests)
    ├── Execution Mode Tests (10 tests)
    ├── Caching Tests (20 tests)
    ├── CLI/REPL Tests (10 tests)
    ├── Safety Tests (8 tests)
    └── Utility Tests (18 tests)
```

### Test Naming Convention

```python
def test_<component>_<scenario>_<expected_outcome>():
    """
    Test that <component> <does something> when <scenario>.

    This test verifies <specific behavior>.
    """
    # Arrange: Setup test data
    # Act: Execute function
    # Assert: Verify results
```

**Examples:**
- `test_read_file_returns_content()` - Basic success case
- `test_read_file_missing_file_returns_error()` - Error case
- `test_execution_mode_completes_all_tasks()` - Integration test
- `test_concurrent_execution_respects_dependencies()` - Complex scenario

## Writing New Tests

### Step 1: Identify What to Test

**Prioritize:**
1. **Core functionality** - Main user-facing features
2. **Edge cases** - Boundary conditions, errors
3. **Bug fixes** - Prevent regressions
4. **Complex logic** - Hard to reason about code

**Skip:**
- Trivial getters/setters
- Third-party library code
- Generated code

### Step 2: Choose Test Type

**Unit Test** - Test a single function in isolation
```python
def test_safe_path_validates_relative_paths():
    """Test that _safe_path accepts valid relative paths."""
    from rev.tools.file_ops import _safe_path

    # Should accept relative paths
    result = _safe_path("subdir/file.txt")
    assert "subdir/file.txt" in str(result)
```

**Integration Test** - Test multiple components together
```python
def test_planning_and_execution_integration():
    """Test that planning generates a valid plan and execution runs it."""
    # Mock LLM responses
    with patch('rev.llm.client.ollama_chat') as mock_chat:
        # Setup mock responses for planning
        mock_chat.return_value = {...}

        # Generate plan
        plan = planning_mode("Add feature X")

        # Execute plan
        success = execution_mode(plan, auto_approve=True)

        assert success
        assert plan.is_complete()
```

**End-to-End Test** - Test full user workflow
```python
def test_full_workflow_one_shot_mode(tmp_path):
    """Test complete workflow from CLI to execution."""
    # Create test repo
    repo = tmp_path / "repo"
    repo.mkdir()

    # Mock everything
    with patch('rev.llm.client.ollama_chat'), \
         patch('rev.config.ROOT', repo):
        # Run main CLI
        sys.argv = ['rev', 'Add logging']
        main()

        # Verify results
        assert (repo / "logger.py").exists()
```

### Step 3: Write the Test

Follow the **Arrange-Act-Assert** pattern:

```python
def test_example_function():
    """Test example function does something."""

    # ARRANGE: Set up test data and mocks
    test_input = "test data"
    expected_output = "expected result"

    with patch('module.dependency') as mock_dep:
        mock_dep.return_value = "mocked value"

        # ACT: Execute the function being tested
        result = example_function(test_input)

        # ASSERT: Verify the results
        assert result == expected_output
        mock_dep.assert_called_once_with(test_input)
```

### Step 4: Add Fixtures if Needed

```python
@pytest.fixture
def sample_execution_plan():
    """Create a sample execution plan for testing."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "review")
    plan.add_task("Task 2", "edit")
    plan.add_task("Task 3", "test")
    return plan

def test_plan_completion(sample_execution_plan):
    """Test that plan tracks completion correctly."""
    plan = sample_execution_plan

    # Initially not complete
    assert not plan.is_complete()

    # Mark all tasks complete
    for task in plan.tasks:
        plan.mark_task_complete(task, "Done")

    # Now complete
    assert plan.is_complete()
```

### Step 5: Run and Verify

```bash
# Run the new test
pytest tests/test_agent_min.py::test_example_function -v

# Check coverage
pytest tests/test_agent_min.py::test_example_function --cov=rev --cov-report=term-missing
```

## Test Categories

### 1. File Operations Tests

**What to test:**
- Basic CRUD operations (create, read, update, delete)
- Path validation and security
- Error handling (missing files, permissions)
- Edge cases (empty files, large files, special characters)

**Example:**
```python
def test_read_file_returns_content(tmp_path):
    """Test that read_file returns file content."""
    test_file = tmp_path / "test.txt"
    test_content = "Hello, World!"
    test_file.write_text(test_content)

    with patch('rev.config.ROOT', tmp_path):
        result = read_file(str(test_file.relative_to(tmp_path)))

    assert result == test_content

def test_read_file_missing_returns_error(tmp_path):
    """Test that read_file returns error for missing file."""
    with patch('rev.config.ROOT', tmp_path):
        result = read_file("nonexistent.txt")

    assert "error" in result.lower()
```

**Coverage gaps:**
- Binary file handling
- File encoding edge cases (UTF-16, special chars)
- Symlink following
- Very large files (> 5MB)

### 2. Git Operations Tests

**What to test:**
- Git commands execute correctly
- Output parsing
- Error handling (not a repo, conflicts)
- Edge cases (empty repo, merge conflicts)

**Example:**
```python
@patch('subprocess.run')
def test_git_status_returns_status(mock_run):
    """Test that git_status returns git status output."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="On branch main\nnothing to commit"
    )

    result = git_status()

    assert "On branch main" in result
    mock_run.assert_called_once()
    assert "git status" in mock_run.call_args[0][0]

def test_git_diff_with_changes(mock_git):
    """Test git_diff returns diff when changes exist."""
    mock_git.return_value = "diff --git a/file.py b/file.py\n+new line"

    result = git_diff()

    assert "diff --git" in result
    assert "+new line" in result
```

**Coverage gaps:**
- Git submodules
- Large diffs (> 1000 lines)
- Binary file diffs
- Merge conflict resolution

### 3. Task Management Tests

**What to test:**
- Task creation and state transitions
- ExecutionPlan operations
- Dependency tracking
- Thread safety
- Checkpoint save/load

**Example:**
```python
def test_task_status_transitions():
    """Test task status transitions through lifecycle."""
    task = Task("Test task", "review")

    # Initial state
    assert task.status == TaskStatus.PENDING

    # Start task
    task.status = TaskStatus.IN_PROGRESS
    assert task.status == TaskStatus.IN_PROGRESS

    # Complete task
    task.status = TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED

def test_execution_plan_thread_safety():
    """Test that ExecutionPlan is thread-safe."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "review")

    def mark_complete():
        task = plan.get_current_task()
        plan.mark_task_complete(task, "Done")

    # Run in parallel
    import threading
    threads = [threading.Thread(target=mark_complete) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should not crash or corrupt data
    assert plan.current_index <= len(plan.tasks)
```

**Coverage gaps:**
- Checkpoint corruption recovery
- Very large plans (1000+ tasks)
- Complex dependency graphs
- Circular dependency detection

### 4. Execution Mode Tests

**What to test:**
- Sequential execution flow
- Concurrent execution with dependencies
- Tool calling and result handling
- Error recovery
- Interrupt handling

**Example:**
```python
@patch('rev.llm.client.ollama_chat')
def test_execution_mode_executes_all_tasks(mock_chat):
    """Test that execution mode completes all tasks."""
    # Setup plan
    plan = ExecutionPlan()
    plan.add_task("Review code", "review")
    plan.add_task("Fix bug", "edit")

    # Mock LLM responses
    mock_chat.side_effect = [
        {"message": {"content": "TASK_COMPLETE"}},
        {"message": {"content": "TASK_COMPLETE"}},
    ]

    # Execute
    success = execution_mode(plan, auto_approve=True)

    # Verify
    assert success
    assert plan.is_complete()
    assert all(t.status == TaskStatus.COMPLETED for t in plan.tasks)

@patch('rev.llm.client.ollama_chat')
def test_concurrent_execution_respects_dependencies(mock_chat):
    """Test that concurrent execution waits for dependencies."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "review", dependencies=[])
    plan.add_task("Task 2", "edit", dependencies=[0])  # Depends on Task 1
    plan.add_task("Task 3", "test", dependencies=[1])  # Depends on Task 2

    mock_chat.return_value = {"message": {"content": "TASK_COMPLETE"}}

    execution_order = []

    def track_execution(task, *args, **kwargs):
        execution_order.append(task.description)
        return [], "Done"

    with patch('rev.execution.executor.execute_single_task', side_effect=track_execution):
        concurrent_execution_mode(plan, max_workers=3, auto_approve=True)

    # Verify order
    assert execution_order == ["Task 1", "Task 2", "Task 3"]
```

**Coverage gaps:**
- Deadlock detection
- Task timeout handling
- Memory limits during concurrent execution
- Dynamic task addition during execution

### 5. Caching Tests

**What to test:**
- Cache hit/miss logic
- TTL expiration
- Invalidation triggers
- Persistence and loading
- Thread safety

**Example:**
```python
def test_file_cache_returns_cached_content():
    """Test that file cache returns cached content on hit."""
    cache = FileContentCache()

    # Cache a value
    cache.set("file.txt", "content", ttl=60)

    # Should return cached value
    result = cache.get("file.txt")
    assert result == "content"

    # Stats should show hit
    stats = cache.get_stats()
    assert stats["hits"] == 1

def test_llm_cache_invalidates_after_ttl():
    """Test that LLM cache invalidates after TTL expires."""
    cache = LLMResponseCache()

    # Cache with short TTL
    cache.set("key", "value", ttl=0.1)

    # Immediate hit
    assert cache.get("key") == "value"

    # Wait for expiration
    import time
    time.sleep(0.2)

    # Should miss
    assert cache.get("key") is None
```

**Coverage gaps:**
- Cache eviction strategies (LRU, LFU)
- Maximum cache size enforcement
- Cache corruption recovery
- Distributed caching

### 6. Safety and Security Tests

**What to test:**
- Scary operation detection
- Command injection prevention
- Path traversal prevention
- Secret detection
- Review agent security checks

**Example:**
```python
def test_is_scary_operation_detects_deletion():
    """Test that scary operation detection flags file deletion."""
    # Should detect file deletion
    assert is_scary_operation("delete_file", {"file_path": "test.txt"})

    # Should detect rm command
    assert is_scary_operation("run_cmd", {"command": "rm -rf /"})

    # Should not flag safe operations
    assert not is_scary_operation("read_file", {"file_path": "test.txt"})

def test_command_injection_detection():
    """Test that command injection is detected."""
    from rev.execution.reviewer import _fast_security_check

    # Should detect injection
    issues = _fast_security_check(
        "run_cmd",
        {"command": "ls; rm -rf /"}
    )
    assert len(issues) > 0
    assert "injection" in issues[0].lower()
```

**Coverage gaps:**
- SQL injection in database operations
- XSS in generated HTML/markdown
- SSRF in web_fetch
- Timing attack vulnerabilities

## Coverage Gaps

### Current Coverage: 80%

**Uncovered Areas (20%):**

1. **Error Recovery Paths** (~5%)
   - Rare error conditions (disk full, OOM)
   - Network failures and retries
   - Corrupt file recovery

2. **Edge Cases** (~5%)
   - Very large inputs (files > 100MB, plans > 1000 tasks)
   - Unicode edge cases (emoji, RTL text)
   - Platform-specific code paths

3. **Interactive Features** (~5%)
   - REPL command history
   - Terminal escape sequences
   - Signal handling on different platforms

4. **Optional Features** (~5%)
   - SSH operations (requires paramiko)
   - MCP server integration
   - Cloud model authentication flows

### Priority Test Additions

**High Priority:**
1. More concurrent execution edge cases
2. Checkpoint corruption recovery
3. Large file handling
4. Complex dependency graphs

**Medium Priority:**
1. Binary file operations
2. Git merge conflicts
3. Cache eviction strategies
4. Review agent edge cases

**Low Priority:**
1. REPL history
2. SSH edge cases (requires infrastructure)
3. MCP server mocking
4. Performance benchmarks

## Mocking Strategy

### When to Mock

**Always mock:**
- External APIs (Ollama, web requests)
- Filesystem operations (in most tests)
- Network calls
- Expensive operations (LLM inference)

**Sometimes mock:**
- Git commands (mock for unit tests, real for integration)
- File operations (mock for unit, real for integration)
- System calls

**Never mock:**
- Pure functions (no side effects)
- Data models (Task, ExecutionPlan)
- Simple utilities

### Mocking Techniques

#### 1. Function Mocking

```python
from unittest.mock import patch, MagicMock

@patch('rev.llm.client.ollama_chat')
def test_with_function_mock(mock_chat):
    """Test with function mocked."""
    mock_chat.return_value = {"message": {"content": "response"}}

    result = some_function_that_calls_ollama_chat()

    assert result == expected
    mock_chat.assert_called_once()
```

#### 2. Object Mocking

```python
from unittest.mock import Mock

def test_with_object_mock():
    """Test with object mocked."""
    mock_plan = Mock(spec=ExecutionPlan)
    mock_plan.is_complete.return_value = False
    mock_plan.get_current_task.return_value = mock_task

    result = execution_mode(mock_plan)

    mock_plan.is_complete.assert_called()
```

#### 3. Side Effects

```python
@patch('module.function')
def test_with_side_effects(mock_func):
    """Test with different return values per call."""
    mock_func.side_effect = [
        "first call",
        "second call",
        Exception("third call fails")
    ]

    assert function_under_test() == "first call"
    assert function_under_test() == "second call"

    with pytest.raises(Exception):
        function_under_test()
```

#### 4. Context Manager Mocking

```python
@patch('builtins.open', create=True)
def test_file_opening(mock_open):
    """Test file operations with mocked open()."""
    mock_open.return_value.__enter__.return_value.read.return_value = "content"

    result = read_file("test.txt")

    assert result == "content"
```

### Mock Best Practices

1. **Use spec**: Prevents typos and ensures mock matches real interface
   ```python
   mock = Mock(spec=RealClass)  # Only allows real methods
   ```

2. **Reset mocks**: Between tests or test cases
   ```python
   mock.reset_mock()
   ```

3. **Assert calls**: Verify mock was called correctly
   ```python
   mock.assert_called_once_with(expected_args)
   mock.assert_called()
   mock.assert_not_called()
   ```

4. **Use return_value vs side_effect**:
   - `return_value`: Same result every time
   - `side_effect`: Different results per call or raise exceptions

## Best Practices

### 1. Test Independence

Each test should be completely independent:

```python
# BAD: Tests share state
global_state = []

def test_1():
    global_state.append(1)
    assert len(global_state) == 1  # Fails if test_2 runs first

def test_2():
    global_state.append(2)
    assert len(global_state) == 1  # Fails if test_1 runs first

# GOOD: Tests are independent
def test_1():
    local_state = []
    local_state.append(1)
    assert len(local_state) == 1

def test_2():
    local_state = []
    local_state.append(2)
    assert len(local_state) == 1
```

### 2. Clear Assertions

```python
# BAD: Unclear what's being tested
assert result

# GOOD: Explicit assertion with message
assert result == expected, f"Expected {expected}, got {result}"

# BETTER: Multiple specific assertions
assert result.status == "success"
assert result.data == expected_data
assert result.error is None
```

### 3. Test One Thing

```python
# BAD: Testing multiple things
def test_everything():
    result1 = function1()
    assert result1 == expected1

    result2 = function2()
    assert result2 == expected2

    result3 = function3()
    assert result3 == expected3

# GOOD: One test per behavior
def test_function1_returns_correct_value():
    result = function1()
    assert result == expected1

def test_function2_returns_correct_value():
    result = function2()
    assert result == expected2
```

### 4. Descriptive Names

```python
# BAD
def test_1():
    ...

def test_file():
    ...

# GOOD
def test_read_file_returns_content_when_file_exists():
    ...

def test_read_file_raises_error_when_file_missing():
    ...
```

### 5. Use Fixtures for Shared Setup

```python
@pytest.fixture
def sample_plan():
    """Create a sample execution plan."""
    plan = ExecutionPlan()
    plan.add_task("Task 1", "review")
    plan.add_task("Task 2", "edit")
    return plan

def test_plan_completion(sample_plan):
    # Use shared fixture
    assert not sample_plan.is_complete()

def test_plan_current_task(sample_plan):
    # Reuse same fixture
    assert sample_plan.get_current_task().description == "Task 1"
```

### 6. Test Error Paths

```python
def test_happy_path():
    """Test normal successful case."""
    result = function("valid input")
    assert result == expected

def test_error_path_invalid_input():
    """Test error handling for invalid input."""
    with pytest.raises(ValueError):
        function("invalid input")

def test_error_path_none_input():
    """Test error handling for None input."""
    with pytest.raises(TypeError):
        function(None)
```

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_agent_min.py

# Run specific test
pytest tests/test_agent_min.py::test_read_file_returns_content

# Run tests matching pattern
pytest tests/ -k "file_operations"

# Verbose output
pytest tests/ -v

# Show print statements
pytest tests/ -s

# Stop on first failure
pytest tests/ -x
```

### Coverage Commands

```bash
# Run with coverage report
pytest tests/ --cov=rev --cov-report=term-missing

# Generate HTML coverage report
pytest tests/ --cov=rev --cov-report=html
# Opens in htmlcov/index.html

# Coverage for specific module
pytest tests/ --cov=rev.execution --cov-report=term-missing

# Fail if coverage below threshold
pytest tests/ --cov=rev --cov-fail-under=80
```

### Performance and Profiling

```bash
# Show slowest tests
pytest tests/ --durations=10

# Profile test execution
pytest tests/ --profile

# Parallel execution
pytest tests/ -n auto  # Requires pytest-xdist
```

### Debugging Tests

```bash
# Drop into debugger on failure
pytest tests/ --pdb

# Drop into debugger on first failure
pytest tests/ --pdb -x

# Show local variables on failure
pytest tests/ -l

# Detailed traceback
pytest tests/ --tb=long
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Run tests
        run: pytest tests/ --cov=rev --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v2
        with:
          file: ./coverage.xml
```

## Next Steps

### Immediate Improvements

1. Add tests for concurrent execution edge cases
2. Improve checkpoint save/load testing
3. Add performance benchmarks
4. Test large file handling

### Long-term Goals

1. Achieve 90%+ code coverage
2. Add integration tests with real Ollama
3. Add performance regression tests
4. Implement mutation testing

## Related Documentation

- **CODEBASE_GUIDE.md**: Architecture and components
- **BUG_FIXING_GUIDE.md**: Debugging techniques
- **COVERAGE.md**: Current coverage details
- **TEST_PLAN.md**: Testing roadmap

---

**Last Updated**: 2025-11-22
