# rev - Quick Start Developer Guide

## For Bug Fixing and Test Development

This is a condensed guide to get you started quickly with fixing bugs and building tests in the rev codebase.

## 📚 Documentation Index

Start here based on what you need:

| Need | Document | Description |
|------|----------|-------------|
| **Understand the architecture** | [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) | Complete architecture, components, data flow |
| **Fix a bug** | [BUG_FIXING_GUIDE.md](BUG_FIXING_GUIDE.md) | Common bugs, debugging techniques, error messages |
| **Write tests** | [TESTING_STRATEGY.md](TESTING_STRATEGY.md) | Testing philosophy, how to write tests, coverage gaps |
| **User features** | [README.md](README.md) | User-facing features and usage |
| **System architecture** | [ARCHITECTURE.md](ARCHITECTURE.md) | High-level design |
| **Test coverage** | [COVERAGE.md](COVERAGE.md) | Coverage details and gaps |

## 🚀 Quick Setup (5 minutes)

```bash
# 1. Clone and navigate
cd rev/

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For testing

# 3. Install Ollama (if not already)
# macOS: brew install ollama
# Linux: curl -fsSL https://ollama.ai/install.sh | sh
# Windows: Download from https://ollama.ai

# 4. Start Ollama and pull a model
ollama serve &
ollama pull llama3.1:latest

# 5. Run tests to verify setup
pytest tests/ -v

# 6. Run the tool
python -m rev "Review all Python files"
```

## 🔍 Codebase at a Glance

```
rev/
├── main.py              # CLI entry point ← Start here
├── config.py            # Global configuration
├── models/task.py       # Task and ExecutionPlan models
├── execution/           # Agent implementations
│   ├── planner.py       # Creates execution plans
│   ├── executor.py      # Runs tasks (sequential/concurrent)
│   ├── reviewer.py      # Validates plans and actions
│   ├── validator.py     # Post-execution verification
│   └── safety.py        # Safety checks for destructive ops
├── llm/client.py        # Ollama API integration
├── tools/               # Tool implementations
│   ├── registry.py      # Tool execution router
│   ├── file_ops.py      # File operations
│   ├── git_ops.py       # Git operations
│   └── code_ops.py      # Code analysis
└── cache/               # Caching system

tests/
├── test_agent.py             # Agent behaviors and tools
├── test_advanced_planning.py # Planning/review/execution coverage
└── ...                       # Additional integration tests
```

**Execution Flow:**
```
User Input → Planning Agent → Review Agent → Execution Agent → Validation Agent
```

## 🐛 Fixing Bugs: Quick Reference

### Step 1: Reproduce the Bug

```bash
# Enable debug mode
OLLAMA_DEBUG=1 python -m rev "task that triggers bug"

# Test in REPL for faster iteration
python -m rev --repl
agent> task that triggers bug
```

### Step 2: Find the Bug Location

**Common bug locations:**

| Symptom | Likely Location | File |
|---------|----------------|------|
| "Model not using tools" | LLM client | `llm/client.py:75-200` |
| "Path escapes repo" | File operations | `tools/file_ops.py` |
| Concurrency issues | Execution | `execution/executor.py:400-600` |
| Cache problems | Cache system | `cache/implementations.py` |
| Git errors | Git operations | `tools/git_ops.py` |

### Step 3: Write a Test First (TDD)

```python
# In tests/test_agent.py

def test_bug_reproduction():
    """Test that reproduces the bug."""
    # Setup: Create conditions that trigger bug
    test_input = "input that causes bug"

    # Execute: Run the code
    result = function_that_has_bug(test_input)

    # Verify: This should fail initially
    assert result == expected_correct_output
```

### Step 4: Fix the Bug

```python
# In the appropriate module (e.g., tools/file_ops.py)

def function_that_has_bug(input):
    # OLD CODE (buggy):
    # result = buggy_implementation(input)

    # NEW CODE (fixed):
    result = fixed_implementation(input)

    return result
```

### Step 5: Verify the Fix

```bash
# Run the test
pytest tests/test_agent.py::test_bug_reproduction -v

# Run all tests to ensure no regressions
pytest tests/ --cov=rev --cov-report=term-missing
```

## ✅ Writing Tests: Quick Reference

### Test Template

```python
def test_<component>_<scenario>_<expected>():
    """
    Test that <component> <does something> when <scenario>.

    Verifies <specific behavior>.
    """
    # ARRANGE: Setup test data
    test_data = create_test_data()

    # Mock external dependencies
    with patch('module.dependency') as mock_dep:
        mock_dep.return_value = "mocked value"

        # ACT: Execute function
        result = function_under_test(test_data)

        # ASSERT: Verify results
        assert result == expected_output
        mock_dep.assert_called_once()
```

### Common Test Patterns

**1. File Operations Test**
```python
def test_read_file_returns_content(tmp_path):
    """Test reading file content."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    with patch('rev.config.ROOT', tmp_path):
        result = read_file("test.txt")

    assert result == "content"
```

**2. Git Operations Test**
```python
@patch('subprocess.run')
def test_git_status(mock_run):
    """Test git status execution."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="On branch main"
    )

    result = git_status()

    assert "On branch main" in result
```

**3. Execution Test**
```python
@patch('rev.llm.client.ollama_chat')
def test_execution_completes_tasks(mock_chat):
    """Test task execution."""
    plan = ExecutionPlan()
    plan.add_task("Review code", "review")

    mock_chat.return_value = {
        "message": {"content": "TASK_COMPLETE"}
    }

    success = execution_mode(plan, auto_approve=True)

    assert success
    assert plan.is_complete()
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_agent.py::test_name -v

# Run with coverage
pytest tests/ --cov=rev --cov-report=term-missing

# Run tests matching pattern
pytest tests/ -k "file_operations" -v
```

## 🎯 Common Tasks

### Add a New Tool

1. **Define tool in appropriate module** (e.g., `tools/code_ops.py`)
```python
def my_new_tool(arg1: str, arg2: int) -> str:
    """
    Description of what the tool does.

    Args:
        arg1: Description
        arg2: Description

    Returns:
        Description of return value
    """
    # Implementation
    return result
```

2. **Register tool in registry** (`tools/registry.py`)
```python
TOOL_REGISTRY["my_new_tool"] = {
    "function": my_new_tool,
    "description": "Tool description for LLM",
    "parameters": {
        "arg1": "string - Description",
        "arg2": "integer - Description"
    }
}
```

3. **Export from tools** (`tools/__init__.py`)
```python
from .code_ops import my_new_tool

__all__ = [..., "my_new_tool"]
```

4. **Write tests** (`tests/test_agent.py`)
```python
def test_my_new_tool_success():
    """Test my_new_tool with valid input."""
    result = my_new_tool("test", 42)
    assert result == expected
```

### Add a New Agent Feature

1. **Modify agent module** (e.g., `execution/planner.py`)
2. **Update system prompt** if needed
3. **Write tests** for new behavior
4. **Update documentation** (README.md, CODEBASE_GUIDE.md)

### Fix a Performance Issue

1. **Profile the code**:
```python
import cProfile
profiler = cProfile.Profile()
profiler.enable()
# Code to profile
profiler.disable()
profiler.print_stats(sort='cumtime')
```

2. **Common fixes**:
   - Add caching (see `cache/implementations.py`)
   - Reduce LLM calls
   - Optimize file operations
   - Use concurrent execution

3. **Verify improvement**:
```bash
time python -m rev "task"  # Before
# Apply fix
time python -m rev "task"  # After
```

## 📊 Test Coverage Targets

**Current:** 80% (production-ready)
**Goal:** 85%+

**Priority areas for new tests:**
1. Concurrent execution edge cases
2. Checkpoint corruption recovery
3. Large file handling (> 5MB)
4. Complex dependency graphs
5. Error recovery paths

**Check coverage:**
```bash
pytest tests/ --cov=rev --cov-report=html
# Open htmlcov/index.html to see uncovered lines
```

## 🔧 Debugging Checklist

When debugging an issue:

- [ ] Can you reproduce it consistently?
- [ ] What's the error message? (Check [BUG_FIXING_GUIDE.md](BUG_FIXING_GUIDE.md))
- [ ] Enable debug mode: `OLLAMA_DEBUG=1`
- [ ] Check Ollama is running: `ollama list`
- [ ] Try with different model: `--model llama3.1:latest`
- [ ] Test in REPL mode: `python -m rev --repl`
- [ ] Check cache stats: Clear if needed
- [ ] Run with sequential execution: `-j 1`
- [ ] Add print debugging at suspected location
- [ ] Write a minimal test case

## 📝 Code Quality Checklist

Before committing:

- [ ] All tests pass: `pytest tests/ -v`
- [ ] Code is formatted: `black rev/`
- [ ] Linting passes: `ruff check .`
- [ ] Coverage maintained/improved: `pytest --cov=rev`
- [ ] New functions have docstrings
- [ ] Complex logic has comments
- [ ] Tests added for new functionality
- [ ] Documentation updated if needed

## 🚨 Common Pitfalls

**❌ Don't:**
- Modify files outside the repository root
- Run without tests passing
- Commit commented-out code
- Use `print()` instead of returning errors
- Mock too much (makes tests brittle)
- Write tests that depend on each other

**✅ Do:**
- Use relative paths from `config.ROOT`
- Write tests for bug fixes
- Follow existing code style
- Return structured errors (`{"error": "message"}`)
- Mock external dependencies only
- Keep tests independent

## 📞 Getting Help

1. **Check documentation**:
   - [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) - Architecture
   - [BUG_FIXING_GUIDE.md](BUG_FIXING_GUIDE.md) - Debugging
   - [TESTING_STRATEGY.md](TESTING_STRATEGY.md) - Testing

2. **Look for similar code**:
   - Find similar functionality in codebase
   - Check how it's tested
   - Follow the same pattern

3. **Debug systematically**:
   - Reproduce the issue
   - Isolate the problem
   - Write a failing test
   - Fix the bug
   - Verify the fix

## 🎓 Learning Path

**Day 1:** Setup and Run Tests
- Set up environment
- Run full test suite
- Run rev on a simple task
- Read CODEBASE_GUIDE.md overview

**Day 2:** Understand Architecture
- Trace execution flow through code
- Read main.py and execution/ modules
- Understand agent coordination
- Read CODEBASE_GUIDE.md in detail

**Day 3:** Write Your First Test
- Pick a simple function
- Write a test following patterns
- Run and debug test
- Read TESTING_STRATEGY.md

**Day 4:** Fix Your First Bug
- Find a bug or known issue
- Write a test that reproduces it
- Fix the bug
- Verify all tests pass
- Read BUG_FIXING_GUIDE.md

**Day 5+:** Contribute
- Add new features
- Improve test coverage
- Optimize performance
- Help others

## 📚 Complete Documentation

- **[CODEBASE_GUIDE.md](CODEBASE_GUIDE.md)** - Full architecture documentation
- **[BUG_FIXING_GUIDE.md](BUG_FIXING_GUIDE.md)** - Debugging and troubleshooting
- **[TESTING_STRATEGY.md](TESTING_STRATEGY.md)** - Testing philosophy and practices
- **[README.md](README.md)** - User-facing features
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design
- **[COVERAGE.md](COVERAGE.md)** - Test coverage details
- **[TEST_PLAN.md](TEST_PLAN.md)** - Testing roadmap
- **[ADVANCED_PLANNING.md](ADVANCED_PLANNING.md)** - Planning system
- **[CACHING.md](CACHING.md)** - Cache system

---

**Ready to start? Pick a task:**
1. Run the test suite: `pytest tests/ -v`
2. Fix a bug from issues
3. Add tests for uncovered code
4. Improve documentation

**Questions?** Check the detailed guides above or explore the codebase!

---

**Last Updated**: 2025-11-22
