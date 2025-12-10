# Development Guide for rev

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Model Handling System](#model-handling-system)
3. [Common Issues and Edge Cases](#common-issues-and-edge-cases)
4. [Testing Strategy](#testing-strategy)
5. [Bug Fixing Guide](#bug-fixing-guide)

---

## Architecture Overview

### Project Structure

```
rev/
├── rev/                          # Main package
│   ├── __main__.py              # Entry point (python -m rev)
│   ├── main.py                  # CLI argument parsing
│   ├── config.py                # Configuration constants
│   ├── llm/
│   │   ├── client.py            # Ollama API integration
│   │   └── __init__.py
│   ├── execution/               # 6-Agent System
│   │   ├── planner.py           # Planning Agent
│   │   ├── executor.py          # Execution Agent
│   │   ├── reviewer.py          # Review Agent
│   │   ├── validator.py         # Validation Agent
│   │   ├── researcher.py        # Research Agent
│   │   ├── learner.py           # Learning Agent
│   │   ├── orchestrator.py      # Orchestrator (meta-agent)
│   │   └── safety.py            # Safety checks
│   ├── tools/                   # 41 tool functions
│   ├── cache/                   # Intelligent caching system
│   ├── models/                  # Data models (Task, ExecutionPlan, etc.)
│   └── terminal/                # Interactive REPL mode
├── tests/                        # Comprehensive test suite
└── examples/                     # Usage examples
```

### Key Components

#### 1. CLI Entry Point (`rev/main.py`)
- **Lines 37-40**: `--model` argument definition
- **Lines 121-122**: Configuration update (critical for model handling)
- **Lines 124-132**: Startup output display

#### 2. Configuration System (`rev/config.py`)
- **Lines 20-21**: Default configuration values
- Configuration is **mutable** and updated by CLI arguments
- Used as module import (not direct variable import) to ensure runtime value access

#### 3. Ollama Client (`rev/llm/client.py`)
- **Line 11**: Module import pattern (CRITICAL - see "Module Import Pattern" below)
- **Lines 38-45**: API request payload construction
- **Lines 78-111**: Cloud model authentication handling
- **Lines 113-124**: Tool support fallback mechanism
- **Lines 58-141**: Retry logic with exponential timeout

---

## Model Handling System

### Configuration Flow

```
┌─────────────────────────────────────────────────┐
│  1. Default Configuration (config.py:20-21)    │
│     OLLAMA_MODEL = "gpt-oss:120b-cloud"          │
│     OLLAMA_BASE_URL = "http://localhost:11434"│
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  2. CLI Argument Parsing (main.py:37-44)       │
│     --model qwen3-coder:480b-cloud             │
│     --base-url http://localhost:11434          │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  3. Configuration Update (main.py:121-122)     │
│     config.OLLAMA_MODEL = args.model           │
│     config.OLLAMA_BASE_URL = args.base_url     │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  4. Runtime Access (client.py:42)              │
│     payload = {"model": config.OLLAMA_MODEL}   │
└─────────────────────────────────────────────────┘
```

### Module Import Pattern (CRITICAL)

**The Problem:**
Python imports create **copies** of variables at import time. If you import a variable directly, you capture its value at module load time, not runtime.

**Broken Pattern (OLD):**
```python
# client.py - WRONG
from rev.config import OLLAMA_MODEL  # Captures default value at import

# Later, even though main.py updates config.OLLAMA_MODEL,
# this module still uses the old value "gpt-oss:120b-cloud"
payload = {"model": OLLAMA_MODEL}  # Always uses default!
```

**Working Pattern (CURRENT):**
```python
# client.py - CORRECT
from rev import config  # Import module, not variable

# Now we read the attribute at runtime
payload = {"model": config.OLLAMA_MODEL}  # Uses current value
```

**Why This Matters:**
- CLI arguments are parsed **after** all imports
- Module imports happen when Python loads the file
- Direct variable imports create **frozen snapshots**
- Module imports create **dynamic references**

**Files Using This Pattern:**
- `rev/llm/client.py:11` - Uses module import (CORRECT)
- All agent files import and use `ollama_chat()` function

### Cloud Model Handling

#### Detection
Cloud models are identified by:
1. Model name ending with `-cloud` suffix (e.g., `qwen3-coder:480b-cloud`)
2. HTTP 401 Unauthorized response from Ollama API

#### Authentication Flow

```
┌─────────────────────────────────────────────────┐
│  User: rev --model qwen3-coder:480b-cloud      │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  Ollama API Request (client.py:72)             │
│  POST http://localhost:11434/api/chat          │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  Response: 401 Unauthorized (client.py:79)     │
│  {                                             │
│    "signin_url": "https://ollama.com/..."     │
│  }                                             │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  Display Authentication Prompt (client.py:86)  │
│  - Show signin URL                             │
│  - Wait for user to authenticate               │
│  - Retry request after confirmation            │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  Retry Request with Session (client.py:104)    │
│  - Authentication persists in Ollama session   │
└─────────────────────────────────────────────────┘
```

**Implementation Details:**
- `client.py:78-111` - Handles 401 responses
- `client.py:84` - Prevents repeated auth prompts (`auth_prompted` flag)
- `client.py:98-101` - Waits for user input (Ctrl+C to cancel)
- Authentication state managed by Ollama, not the CLI

---

## Common Issues and Edge Cases

### 1. Model Not Found (404 Error)

**Symptom:**
```
Error: Ollama API error: 404 Client Error: Not Found
{"error":"model 'qwen3-coder:480b-cloud' not found"}
```

**Possible Causes:**
1. **Ollama Not Running** - Most common!
   - Check: `ollama serve` or system service
   - Solution: Start Ollama service

2. **Model Not Pulled** - For local models
   - Check: `ollama list`
   - Solution: `ollama pull <model-name>`

3. **Typo in Model Name**
   - Check: Model name spelling
   - Solution: Verify with `ollama list` or Ollama docs

4. **Cloud Model Not Available Locally**
   - Cloud models need Ollama to be running to proxy requests
   - Ollama routes cloud models to cloud API
   - Solution: Ensure Ollama is running AND authenticated

**Testing:**
```bash
# Verify Ollama is running
curl http://localhost:11434/api/version

# List available models
ollama list

# Pull a model if needed
ollama pull gpt-oss:120b-cloud
```

### 2. Model Parameter Not Honored

**Fixed in commit `3088c5d` (Nov 21, 2024)**

**Symptom:**
```bash
rev --model qwen3-coder:480b-cloud "task"
# Shows: Model: qwen3-coder:480b-cloud
# But actually uses: gpt-oss:120b-cloud
```

**Root Cause:**
Direct variable import in `client.py` captured default value at import time.

**Fix:**
Changed from `from rev.config import OLLAMA_MODEL` to `from rev import config`

**Test Cases to Prevent Regression:**
```python
def test_model_parameter_honored():
    """Ensure --model parameter is used in API calls"""
    # Set custom model
    config.OLLAMA_MODEL = "custom-model:test"

    # Make API call
    # Should use "custom-model:test", not default

def test_runtime_config_changes():
    """Config changes at runtime should affect API calls"""
    # Change config after import
    original = config.OLLAMA_MODEL
    config.OLLAMA_MODEL = "different-model"

    # Verify new value is used
    # Restore original
    config.OLLAMA_MODEL = original
```

### 3. Cloud Authentication Loop

**Symptom:**
Repeatedly asks for authentication even after completing it.

**Possible Causes:**
1. **Browser Authentication Not Completed** - User didn't finish auth flow
2. **Ollama Session Lost** - Ollama restarted or session expired
3. **Network Issues** - Connection interrupted during auth

**Prevention:**
- `auth_prompted` flag prevents repeated prompts in same call (`client.py:63`)
- User can Ctrl+C to cancel (`client.py:100-101`)

**Testing:**
```python
def test_cloud_auth_single_prompt():
    """Should only prompt once per call, even with retries"""
    # Mock 401 response
    # Ensure auth prompt only shows once
    # Subsequent retries should not re-prompt
```

### 4. Tool Support Fallback

**Symptom:**
```
[DEBUG] Got 400 with tools, retrying without tools...
```

**Cause:**
Model doesn't support function/tool calling.

**Behavior:**
- First request includes `tools` array (`client.py:48-49`)
- If 400 error, retry without tools (`client.py:113-124`)
- Graceful degradation for older models

**Models Without Tool Support:**
- `gpt-oss:120b-cloud` (7B, 13B, 34B)
- `deepseek-coder:*` (some versions)
- Legacy models

**Models With Tool Support:**
- `llama3.1:*` (8B, 70B, 405B)
- `mistral-nemo`, `mistral-large`
- `qwen2.5:*` (7B+)
- Cloud models (qwen3-coder:480b-cloud, etc.)

**Testing:**
```python
def test_tool_fallback():
    """Should retry without tools on 400 error"""
    # Mock 400 response with tools
    # Verify retry without tools
    # Ensure no tools in second request
```

### 5. Request Timeout

**Default Timeouts:**
- Attempt 1: 10 minutes (600s)
- Attempt 2: 20 minutes (1200s)
- Attempt 3: 30 minutes (1800s)

**Symptom:**
```
[DEBUG] Request timed out after 600s, will retry with longer timeout...
```

**Cause:**
- Large codebase analysis
- Complex planning task
- Slow model/hardware
- Cloud model latency

**Configuration:**
See `client.py:59-60` for timeout values.

**Testing:**
```python
def test_timeout_retry():
    """Should retry with longer timeout on timeout error"""
    # Mock timeout on first request
    # Verify retry with 2x timeout
    # Verify final timeout is 30m
```

---

## Testing Strategy

### Test Categories

#### 1. Unit Tests
Test individual functions in isolation.

**Priority Areas:**
- Configuration handling (`config.py`)
- Model parameter passing (`main.py:121-122`)
- Ollama client (`client.py`)
- Authentication flow
- Retry logic
- Tool fallback

**Example Test Structure:**
```python
# tests/test_model_handling.py
import pytest
from unittest.mock import patch, MagicMock
from rev import config
from rev.llm.client import ollama_chat

class TestModelParameter:
    def test_default_model(self):
        """Test default model configuration"""
        assert config.OLLAMA_MODEL == "gpt-oss:120b-cloud"

    def test_model_override(self):
        """Test model can be changed at runtime"""
        original = config.OLLAMA_MODEL
        config.OLLAMA_MODEL = "test-model"
        assert config.OLLAMA_MODEL == "test-model"
        config.OLLAMA_MODEL = original

    @patch('requests.post')
    def test_model_used_in_request(self, mock_post):
        """Test that current model is used in API request"""
        mock_post.return_value.json.return_value = {"message": {"content": "test"}}
        mock_post.return_value.status_code = 200

        config.OLLAMA_MODEL = "custom-model:test"
        ollama_chat([{"role": "user", "content": "test"}])

        # Verify API call used custom model
        call_args = mock_post.call_args
        assert call_args[1]['json']['model'] == "custom-model:test"
```

#### 2. Integration Tests
Test complete workflows.

**Scenarios:**
- CLI argument parsing → config update → API call
- Cloud model authentication flow
- Tool fallback behavior
- Multi-retry timeout handling

**Example:**
```python
# tests/test_integration.py
import subprocess
import pytest

def test_model_parameter_e2e():
    """End-to-end test of --model parameter"""
    # Run CLI with custom model
    result = subprocess.run(
        ['python', '-m', 'rev', '--model', 'test-model:custom', 'test task'],
        capture_output=True,
        text=True
    )

    # Verify output shows custom model
    assert 'test-model:custom' in result.stdout
```

#### 3. Edge Case Tests

**Critical Edge Cases:**

**A. Ollama Not Running**
```python
def test_ollama_connection_error():
    """Should handle Ollama not running gracefully"""
    # Stop Ollama or mock connection refused
    # Verify clear error message
```

**B. Invalid Model Name**
```python
def test_invalid_model_name():
    """Should handle model not found error"""
    # Request non-existent model
    # Verify helpful error message
```

**C. Network Interruption During Auth**
```python
def test_auth_network_failure():
    """Should handle network failure during auth"""
    # Mock network failure after auth prompt
    # Verify graceful error handling
```

**D. Model Switching Mid-Session**
```python
def test_model_switch_repl():
    """REPL mode should support switching models"""
    # Start REPL with model A
    # Switch to model B
    # Verify subsequent requests use model B
```

#### 4. Performance Tests

**Caching Effectiveness:**
```python
def test_llm_cache_hit():
    """Identical requests should use cache"""
    # Make same request twice
    # Second request should be nearly instant
    # Verify cache hit
```

**Timeout Handling:**
```python
def test_retry_timeout_progression():
    """Timeouts should increase: 10m, 20m, 30m"""
    # Mock timeout on attempts 1, 2
    # Verify timeout values increase
    # Verify max 3 attempts
```

### Test Data Requirements

**Mock Responses:**
```python
# tests/fixtures.py
MOCK_OLLAMA_SUCCESS = {
    "message": {
        "role": "assistant",
        "content": "Test response"
    }
}

MOCK_OLLAMA_401 = {
    "error": "Unauthorized",
    "signin_url": "https://ollama.com/connect?key=test123"
}

MOCK_OLLAMA_404 = {
    "error": "model 'test-model:404' not found"
}

MOCK_OLLAMA_400_TOOLS = {
    "error": "this model does not support tools"
}
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=rev --cov-report=term-missing

# Run specific category
pytest tests/test_model_handling.py -v

# Run with debug output
OLLAMA_DEBUG=1 pytest tests/ -v -s
```

---

## Bug Fixing Guide

### General Debugging Process

1. **Enable Debug Mode**
   ```bash
   export OLLAMA_DEBUG=1
   rev --model <model> "task"
   ```

2. **Check Ollama Status**
   ```bash
   curl http://localhost:11434/api/version
   ollama list
   ```

3. **Verify Configuration**
   ```python
   # Add to client.py temporarily
   print(f"[DEBUG] Config module: {config}")
   print(f"[DEBUG] OLLAMA_MODEL: {config.OLLAMA_MODEL}")
   print(f"[DEBUG] OLLAMA_BASE_URL: {config.OLLAMA_BASE_URL}")
   ```

4. **Test API Directly**
   ```bash
   curl http://localhost:11434/api/chat -d '{
     "model": "qwen3-coder:480b-cloud",
     "messages": [{"role": "user", "content": "test"}],
     "stream": false
   }'
   ```

### Common Bug Patterns

#### 1. Import-Time vs Runtime Issues

**Symptom:** Configuration changes don't affect behavior

**Check:**
```python
# Look for this pattern (BAD):
from rev.config import OLLAMA_MODEL

# Should be (GOOD):
from rev import config
# ... later ...
config.OLLAMA_MODEL
```

**Files to Check:**
- Any file using configuration values
- Any file calling Ollama API
- Agent files using `ollama_chat()`

#### 2. Authentication State Issues

**Symptom:** Repeated auth prompts or auth failures

**Check:**
```python
# client.py:63 - auth_prompted flag
auth_prompted = False

# Ensure it's checked before showing prompt
if signin_url and not auth_prompted:
    auth_prompted = True
    # ... show prompt ...
```

**Potential Issues:**
- Flag not being set
- Flag scope incorrect (should be in retry loop)
- Multiple instances of client

#### 3. Retry Logic Issues

**Symptom:** Requests fail without retrying or retry infinitely

**Check:**
```python
# client.py:59-60 - max retries
max_retries = 3
base_timeout = 600  # 10 minutes

# Verify loop range
for attempt in range(max_retries):  # 0, 1, 2
    timeout = base_timeout * (attempt + 1)  # 600, 1200, 1800
```

**Test:**
- Verify exactly 3 attempts
- Verify timeout increases
- Verify error returned after max attempts

### Adding Debug Logging

**Temporary Debug Code:**
```python
# In client.py, add before API call
import traceback
print(f"[DEBUG] Call stack:\n{''.join(traceback.format_stack())}")
print(f"[DEBUG] Model: {config.OLLAMA_MODEL}")
print(f"[DEBUG] URL: {url}")
print(f"[DEBUG] Payload: {json.dumps(payload, indent=2)}")
```

**Permanent Debug Code:**
```python
# Use OLLAMA_DEBUG environment variable
if OLLAMA_DEBUG:
    print(f"[DEBUG] ...")
```

### Fixing Ollama Connection Issues

**Issue:** Cannot connect to Ollama

**Solutions:**
```bash
# 1. Check if Ollama is running
ps aux | grep ollama

# 2. Start Ollama
ollama serve  # macOS/Linux
# Or use system service

# 3. Verify connectivity
curl http://localhost:11434/api/version

# 4. Check custom base URL
export OLLAMA_BASE_URL="http://custom:11434"
rev --base-url http://custom:11434 "task"
```

---

## Recent Fixes Reference

### Fix: --model Parameter Not Being Honored (Commit 3088c5d)

**Date:** Nov 21, 2024
**Files Changed:** `rev/llm/client.py`

**Problem:**
The `--model` parameter was displayed correctly but not used in API calls.

**Root Cause:**
Python's import-time variable binding. Direct imports (`from X import Y`) create copies at module load time.

**Solution:**
Changed from direct import to module import:

```diff
- from rev.config import OLLAMA_BASE_URL, OLLAMA_MODEL
+ from rev import config

- url = f"{OLLAMA_BASE_URL}/api/chat"
+ url = f"{config.OLLAMA_BASE_URL}/api/chat"

- payload = {"model": OLLAMA_MODEL, ...}
+ payload = {"model": config.OLLAMA_MODEL, ...}
```

**Verification:**
```bash
# Before fix: Always used gpt-oss:120b-cloud
# After fix: Uses specified model
rev --model qwen3-coder:480b-cloud "test"
```

**Lines Changed:**
- Line 11: Import statement
- Line 38: Base URL reference
- Line 42: Model reference
- Line 53: Debug output
- Line 89: Error message
- Line 120: Retry payload

**Test Coverage:**
Add regression tests to verify model parameter is honored:
```python
def test_model_parameter_regression():
    """Prevent regression of model parameter bug"""
    config.OLLAMA_MODEL = "custom:test"
    # Verify API uses custom model, not default
```

---

## Contributing

When fixing bugs or adding features:

1. **Update This Document** - Add new edge cases, patterns, or fixes
2. **Add Tests** - Prevent regressions with test coverage
3. **Enable Debug Mode** - Use `OLLAMA_DEBUG=1` during development
4. **Check Module Imports** - Always use `from rev import config` pattern
5. **Test Cloud Models** - Verify cloud authentication flow
6. **Test Local Models** - Verify fallback behavior
7. **Document Assumptions** - Add comments explaining non-obvious code

---

## Quick Reference

### Key Files
- `rev/main.py:121-122` - Configuration update (CLI args → config)
- `rev/config.py:20-21` - Default values
- `rev/llm/client.py:11` - Module import pattern
- `rev/llm/client.py:38-45` - API request construction
- `rev/llm/client.py:78-111` - Cloud auth handling

### Debug Commands
```bash
# Enable debug output
export OLLAMA_DEBUG=1

# Test Ollama connection
curl http://localhost:11434/api/version

# List models
ollama list

# Test specific model
rev --model <model-name> "test task"

# Test with custom base URL
rev --base-url http://custom:11434 --model <model> "task"
```

### Testing Commands
```bash
# Run all tests
pytest tests/ -v

# Test with coverage
pytest tests/ --cov=rev --cov-report=html

# Test specific file
pytest tests/test_model_handling.py -v

# Debug test
pytest tests/test_model_handling.py::test_name -v -s
```
