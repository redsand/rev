# rev - Bug Fixing and Debugging Guide

## Overview

This guide provides systematic approaches to debugging and fixing bugs in the rev codebase. It covers common issues, debugging techniques, and step-by-step troubleshooting procedures.

## Table of Contents

- [Quick Debugging Checklist](#quick-debugging-checklist)
- [Common Bug Categories](#common-bug-categories)
- [Debugging Tools and Techniques](#debugging-tools-and-techniques)
- [Known Issues and Workarounds](#known-issues-and-workarounds)
- [Error Message Guide](#error-message-guide)
- [Performance Issues](#performance-issues)
- [Testing Bugs](#testing-bugs)

## Quick Debugging Checklist

When encountering a bug, follow this checklist:

1. **Reproduce the bug consistently**
   - Document exact steps to reproduce
   - Note the environment (OS, Python version, Ollama model)
   - Check if bug occurs with different models

2. **Check the basics**
   - Is Ollama running? `ollama list`
   - Does the model support tools? `ollama show <model>`
   - Are dependencies installed? `pip list`
   - Is the working directory correct?

3. **Enable debug mode**
   ```bash
   OLLAMA_DEBUG=1 python -m rev "task"
   ```

4. **Check logs and output**
   - Look for Python exceptions
   - Check Ollama API error messages
   - Review tool execution output

5. **Isolate the problem**
   - Test in REPL mode for faster iteration
   - Run a minimal reproducible case
   - Use unit tests to isolate components

## Common Bug Categories

### 1. Model/LLM Issues

#### Issue: "Model does not support tool calling"

**Symptoms:**
- Tasks fail with "Model not using tools" error
- LLM doesn't return function calls
- Tool execution never happens

**Causes:**
- Using an older model without tool support (codellama:7b, deepseek-coder:6.7b)
- Ollama version too old (< 0.1.30)
- Cloud model not properly authenticated

**Location:** `rev/llm/client.py:75-200`, `rev/execution/executor.py:150-250`

**Debug:**
```bash
# Check Ollama version
ollama --version

# Check if model supports tools
ollama show llama3.1:latest | grep -i tool

# Enable debug output
OLLAMA_DEBUG=1 python -m rev --model llama3.1:latest "test task"
```

**Fix:**
```bash
# Option 1: Use a model with tool support
ollama pull llama3.1:latest
python -m rev --model llama3.1:latest "task"

# Option 2: Use qwen2.5 (good code model)
ollama pull qwen2.5:7b
python -m rev --model qwen2.5:7b "task"

# Option 3: Cloud models (requires auth)
python -m rev --model qwen3-coder:480b-cloud "task"
```

#### Issue: "401 Unauthorized" for Cloud Models

**Symptoms:**
- Cloud model requests fail with 401
- Authentication prompt appears but doesn't work

**Causes:**
- Cloud model not authenticated
- Authentication token expired
- Ollama not running locally (cloud models proxy through local)

**Location:** `rev/llm/client.py:100-150`

**Debug:**
```bash
# Ensure Ollama is running
ollama serve

# Try authenticating manually
ollama pull qwen3-coder:480b-cloud
```

**Fix:**
1. Visit the authentication URL shown in the error
2. Sign in with Ollama account
3. Authorize the device
4. Re-run the command

#### Issue: "500 Internal Server Error" from Ollama

**Symptoms:**
- Random 500 errors during execution
- Ollama crashes or becomes unresponsive

**Causes:**
- Model out of memory
- Ollama service crashed
- Corrupt model files

**Location:** `rev/llm/client.py:100-200`

**Debug:**
```bash
# Check Ollama logs
# On Linux/Mac: Check systemd/docker logs
# On Windows: Check Ollama app logs

# Test Ollama directly
curl http://localhost:11434/api/generate -d '{"model":"llama3.1:latest","prompt":"test"}'

# Check available memory
free -h  # Linux
vm_stat  # macOS
```

**Fix:**
```bash
# Restart Ollama
killall ollama
ollama serve

# Use a smaller model
ollama pull llama3.1:8b  # Instead of 70b

# Increase GPU/CPU memory allocation
```

### 2. File Operation Bugs

#### Issue: "Path escapes repo" Error

**Symptoms:**
- File operations fail with security error
- Cannot read/write files

**Causes:**
- Trying to access files outside repository root
- Absolute paths instead of relative paths
- Symlinks pointing outside repo

**Location:** `rev/tools/file_ops.py` - `_safe_path()` function

**Debug:**
```python
# Test path safety
from rev.tools.file_ops import _safe_path
try:
    safe = _safe_path("/absolute/path/file.txt")
    print(f"Safe path: {safe}")
except ValueError as e:
    print(f"Invalid path: {e}")
```

**Fix:**
- Use relative paths from repository root
- Check that `config.ROOT` is set correctly
- Avoid using `../` to escape the repository

#### Issue: File Not Found Despite Existing

**Symptoms:**
- `read_file()` fails even though file exists
- Inconsistent file existence checks

**Causes:**
- Case-sensitive filesystem (Linux) vs case-insensitive (Windows)
- File encoding issues
- Cache not invalidated

**Location:** `rev/tools/file_ops.py:50-150`, `rev/cache/implementations.py`

**Debug:**
```bash
# Check file actually exists
ls -la path/to/file

# Check cache stats
python -m rev "Show cache statistics"

# Clear cache
python -m rev "Clear all caches"
```

**Fix:**
- Ensure exact case match for filenames
- Clear file cache: `clear_caches()`
- Check file permissions: `ls -l`

### 3. Git Operation Bugs

#### Issue: Git Commands Fail

**Symptoms:**
- `git_diff()`, `git_status()` return errors
- "Not a git repository" error

**Causes:**
- Current directory not a git repo
- Git not installed
- Invalid git command syntax

**Location:** `rev/tools/git_ops.py`

**Debug:**
```bash
# Test git directly
git status
git --version

# Check current directory
pwd
ls -la .git
```

**Fix:**
- Initialize git repo: `git init`
- Install git if missing
- Check `config.ROOT` is correct

#### Issue: Patch Application Fails

**Symptoms:**
- `apply_patch()` fails even with valid diff
- "Patch does not apply" error
 - Patches get truncated in the prompt because they are very large

**Causes:**
- File already modified
- Line numbers don't match
- Whitespace differences
 - Patch is too large to reliably preview/apply in one go

**Location:** `rev/tools/git_ops.py` - `apply_patch()`

**Debug:**
```bash
# Test patch manually
git apply --check patch.diff
git apply --verbose patch.diff

# Check for whitespace issues
git apply --whitespace=fix patch.diff
```

**Fix:**
- Use `git apply --reject` to apply partial patches
- Regenerate patch from clean state
- Fix whitespace: `--whitespace=fix`
- Split the change into smaller, file-scoped patches so previews don't truncate

### 4. Concurrency Bugs

#### Issue: Race Conditions in Concurrent Execution

**Symptoms:**
- Tasks execute in wrong order
- Duplicate task execution
- Data corruption in ExecutionPlan

**Causes:**
- Missing lock protection
- Shared state without synchronization
- Dependencies not properly enforced

**Location:** `rev/execution/executor.py:400-600`, `rev/models/task.py`

**Debug:**
```python
# Add debug logging
import threading
print(f"Current thread: {threading.current_thread().name}")
print(f"Plan lock: {plan.lock}")

# Test with sequential execution
python -m rev -j 1 "task"  # Forces sequential
```

**Fix:**
- Ensure all plan modifications use `with plan.lock:`
- Check dependency graph in `concurrent_execution_mode()`
- Use thread-safe data structures

#### Issue: Interrupt Handling in Parallel Mode

**Symptoms:**
- Ctrl+C doesn't stop all threads
- Some tasks continue after interrupt
- Checkpoint not saved on interrupt

**Causes:**
- Signal handlers only work in main thread
- Worker threads don't check escape flag
- Interrupt flag not propagated

**Location:** `rev/execution/executor.py:400-600`, `rev/llm/client.py:20-40`

**Debug:**
```python
# Check escape interrupt flag
from rev.config import get_escape_interrupt
print(f"Interrupt requested: {get_escape_interrupt()}")
```

**Fix:**
- Check `get_escape_interrupt()` in worker threads
- Use `threading.Event()` for cross-thread signaling
- Ensure checkpoint saving in interrupt handler

### 5. Cache-Related Bugs

#### Issue: Stale Data from Cache

**Symptoms:**
- File reads return old content
- LLM returns cached response for different input
- Dependency analysis outdated

**Causes:**
- Cache not invalidated on file change
- TTL too long
- Cache key collision

**Location:** `rev/cache/implementations.py`

**Debug:**
```python
# Check cache stats
from rev.cache import get_llm_cache, get_file_cache
print(get_file_cache().get_stats())
print(get_llm_cache().get_stats())

# Clear specific cache
from rev.tools.cache_ops import clear_caches
clear_caches(["file", "llm"])
```

**Fix:**
- Reduce cache TTL in `rev/cache/implementations.py`
- Implement proper invalidation logic
- Use file modification time for cache keys

#### Issue: Cache Persistence Errors

**Symptoms:**
- Cache not persisted across runs
- "Permission denied" when writing cache
- Cache directory not created

**Causes:**
- Cache directory not writable
- Disk full
- Concurrent writes to cache file

**Location:** `rev/cache/implementations.py` - `persist()` method

**Debug:**
```bash
# Check cache directory
ls -la .rev/cache/
df -h .  # Check disk space

# Test cache write manually
python -c "from rev.cache import persist_caches; persist_caches()"
```

**Fix:**
- Ensure `.rev/cache/` is writable
- Free up disk space
- Add lock for cache file writes

### 6. Safety/Security Bugs

#### Issue: Scary Operation Not Detected

**Symptoms:**
- Destructive command executes without prompt
- File deletion happens automatically

**Causes:**
- Pattern not in `SCARY_OPERATIONS` list
- Regex not matching command
- Safety check bypassed

**Location:** `rev/execution/safety.py`

**Debug:**
```python
# Test scary detection
from rev.execution.safety import is_scary_operation
result = is_scary_operation("delete_file", {"file_path": "test.txt"})
print(f"Is scary: {result}")
```

**Fix:**
- Add pattern to `SCARY_OPERATIONS` in `safety.py`
- Update regex patterns
- Test with various command variations

#### Issue: Command Injection Vulnerability

**Symptoms:**
- User input executed as shell command
- Unescaped special characters in commands

**Causes:**
- `run_cmd()` doesn't sanitize input
- Command arguments not validated
- Shell=True used incorrectly

**Location:** `rev/tools/file_ops.py`, `rev/execution/reviewer.py`

**Debug:**
```python
# Test command injection detection
from rev.execution.reviewer import _fast_security_check
result = _fast_security_check("run_cmd", {"command": "ls; rm -rf /"})
print(f"Security issues: {result}")
```

**Fix:**
- Validate and sanitize all command input
- Use shell=False in subprocess
- Implement command whitelist
- Add command injection detection to `_fast_security_check()`

## Debugging Tools and Techniques

### 1. Enable Debug Logging

```bash
# Enable Ollama API debug output
OLLAMA_DEBUG=1 python -m rev "task"

# Python logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. Use REPL Mode for Fast Iteration

```bash
python -m rev --repl

# In REPL:
agent> test command
agent> /status  # Check what's been done
agent> /clear   # Clear session
```

### 3. Sequential Execution for Debugging

```bash
# Run tasks one at a time (easier to debug)
python -m rev -j 1 "task"
```

### 4. Inspect Tool Calls

Add debug output in `execute_tool()`:

```python
# In rev/tools/registry.py
def execute_tool(tool_name, args):
    print(f"[DEBUG] Tool: {tool_name}")
    print(f"[DEBUG] Args: {args}")
    result = tool_function(**args)
    print(f"[DEBUG] Result: {result}")
    return result
```

### 5. Mock Ollama for Testing

```python
# In tests
from unittest.mock import patch

with patch('rev.llm.client.ollama_chat') as mock_chat:
    mock_chat.return_value = {
        "message": {"content": "test response"}
    }
    # Run code
```

### 6. Check Thread State

```python
import threading
print(f"Active threads: {threading.active_count()}")
for t in threading.enumerate():
    print(f"  {t.name}: {t.is_alive()}")
```

### 7. Profile Performance

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run code

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumtime')
stats.print_stats(20)
```

## Known Issues and Workarounds

### Issue: Windows Path Separators

**Problem:** Windows uses `\` but Python strings use `\` for escape

**Workaround:**
```python
# Use raw strings or forward slashes
path = r"C:\Users\name\file.txt"  # Raw string
path = "C:/Users/name/file.txt"    # Forward slash (works on Windows)
```

### Issue: Model Context Length Exceeded

**Problem:** Large codebases exceed model context window

**Workaround:**
- Use smaller context in planning (limit git log, file listings)
- Split large tasks into smaller chunks
- Use research agent with shallow depth
- Enable caching to reduce repeated context

### Issue: Checkpoint Resume with Modified Tasks

**Problem:** Resuming after code changes may cause issues

**Workaround:**
- Avoid resuming if task definitions changed
- Delete old checkpoints: `rm -rf .rev/checkpoints/`
- Use `--list-checkpoints` to check before resuming

## Error Message Guide

### "Connection refused"

**Meaning:** Cannot connect to Ollama API

**Fix:**
```bash
ollama serve  # Start Ollama
```

### "Model not found"

**Meaning:** Requested model not downloaded

**Fix:**
```bash
ollama pull <model-name>
```

### "Path escapes repo"

**Meaning:** Security check preventing access outside repository

**Fix:** Use relative paths from repository root

### "Patch does not apply"

**Meaning:** Git patch doesn't match current file state

**Fix:** Ensure file hasn't been modified, regenerate patch

### "Task timed out"

**Meaning:** Task took too long (network issues, slow model)

**Fix:** Increase timeout, check network, use faster model

### "Checkpoint not found"

**Meaning:** Resume file doesn't exist

**Fix:** Use `--list-checkpoints` to see available checkpoints

## Performance Issues

### Slow LLM Responses

**Causes:**
- Model too large for hardware
- Network latency (cloud models)
- Not using cache effectively

**Debug:**
```bash
# Check cache hit rate
python -m rev "Show cache statistics"

# Monitor Ollama CPU/GPU usage
top  # Linux
Activity Monitor  # macOS
Task Manager  # Windows
```

**Fix:**
- Use smaller, faster models
- Enable LLM response cache
- Use local models instead of cloud

### Slow File Operations

**Causes:**
- Not using file cache
- Reading large files repeatedly
- Inefficient glob patterns

**Debug:**
```python
# Time file operations
import time
start = time.time()
content = read_file("large_file.txt")
print(f"Took {time.time() - start:.2f}s")
```

**Fix:**
- Enable file content cache
- Use `read_file_lines()` for large files
- Optimize glob patterns (avoid `**/*`)

### Memory Leaks

**Causes:**
- Cache growing unbounded
- LLM conversation history not trimmed
- Large files held in memory

**Debug:**
```python
import psutil
import os

process = psutil.Process(os.getpid())
print(f"Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")
```

**Fix:**
- Set cache size limits
- Trim old messages from conversation
- Stream large files instead of reading fully

## Testing Bugs

### Test Failures Due to Mocking

**Issue:** Tests fail because mocks don't match actual API

**Debug:**
- Compare mock response to actual Ollama response
- Use OLLAMA_DEBUG=1 to see real responses
- Update mocks to match current API

**Fix:**
```python
# Update mock to match real API
mock_response = {
    "message": {
        "content": "response",
        "tool_calls": [{"function": {"name": "tool", "arguments": "{}"}}]
    }
}
```

### Flaky Tests (Timing Issues)

**Issue:** Tests sometimes pass, sometimes fail

**Causes:**
- Race conditions in concurrent tests
- Filesystem delays
- External dependencies

**Fix:**
```python
# Add explicit waits
import time
time.sleep(0.1)  # Small delay for filesystem

# Use retry logic
@pytest.mark.flaky(reruns=3)
def test_flaky():
    ...
```

### Test Isolation Issues

**Issue:** Tests affect each other

**Causes:**
- Shared state (global variables)
- Not cleaning up temp files
- Cache not cleared between tests

**Fix:**
```python
# Use fixtures for cleanup
@pytest.fixture
def clean_cache():
    clear_caches()
    yield
    clear_caches()

# Use tmp_path for files
def test_file_ops(tmp_path):
    test_file = tmp_path / "test.txt"
    ...
```

## Next Steps

For more information:

- **CODEBASE_GUIDE.md**: Architecture and component details
- **TEST_PLAN.md**: Testing strategy
- **COVERAGE.md**: Test coverage details
- **TROUBLESHOOTING.md**: User-facing troubleshooting

---

**Last Updated**: 2025-11-22
