# Test Plan for rev

## Overview

This document outlines a comprehensive test strategy for rev, focusing on model handling, Ollama integration, cloud authentication, and edge cases.

## Test Categories

### 1. Unit Tests
### 2. Integration Tests
### 3. End-to-End Tests
### 4. Edge Case Tests
### 5. Performance Tests
### 6. Regression Tests

---

## 1. Unit Tests

### 1.1 Configuration Module (`tests/test_config.py`)

#### Test Cases:

**TC-1.1.1: Default Configuration Values**
```python
def test_default_ollama_model():
    """Verify default OLLAMA_MODEL is 'codellama:latest'"""
    from rev import config
    # Reset to default if changed
    assert config.OLLAMA_MODEL == "codellama:latest"

def test_default_ollama_base_url():
    """Verify default OLLAMA_BASE_URL is 'http://localhost:11434'"""
    from rev import config
    assert config.OLLAMA_BASE_URL == "http://localhost:11434"
```

**TC-1.1.2: Configuration Mutability**
```python
def test_config_can_be_changed():
    """Verify config values can be changed at runtime"""
    from rev import config
    original_model = config.OLLAMA_MODEL

    # Change config
    config.OLLAMA_MODEL = "test-model:custom"
    assert config.OLLAMA_MODEL == "test-model:custom"

    # Restore
    config.OLLAMA_MODEL = original_model
```

**TC-1.1.3: Environment Variable Override**
```python
def test_env_var_override():
    """Verify environment variables override defaults"""
    import os
    from rev import config

    os.environ["OLLAMA_MODEL"] = "env-model:test"
    # Reload config module
    import importlib
    importlib.reload(config)

    assert config.OLLAMA_MODEL == "env-model:test"

    # Cleanup
    del os.environ["OLLAMA_MODEL"]
    importlib.reload(config)
```

---

### 1.2 Ollama Client (`tests/test_ollama_client.py`)

#### Test Cases:

**TC-1.2.1: Module Import Pattern**
```python
def test_client_uses_module_import():
    """Verify client.py uses module import, not direct import"""
    import ast
    import inspect
    from rev.llm import client

    # Read client.py source
    source = inspect.getsource(client)
    tree = ast.parse(source)

    # Find import statements
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

    # Verify pattern: "from rev import config" exists
    config_imports = [
        node for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module == "rev"
        and any(alias.name == "config" for alias in node.names)
    ]

    assert len(config_imports) > 0, "Should use 'from rev import config'"

    # Verify anti-pattern doesn't exist: "from rev.config import OLLAMA_MODEL"
    bad_imports = [
        node for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module == "rev.config"
    ]

    assert len(bad_imports) == 0, "Should NOT use 'from rev.config import ...'"
```

**TC-1.2.2: Request Payload Construction**
```python
@patch('requests.post')
def test_payload_uses_current_model(mock_post):
    """Verify API payload uses current config.OLLAMA_MODEL value"""
    from rev import config
    from rev.llm.client import ollama_chat

    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": "test"}
    }
    mock_post.return_value = mock_response

    # Change model at runtime
    original_model = config.OLLAMA_MODEL
    config.OLLAMA_MODEL = "runtime-model:test"

    # Make request
    ollama_chat([{"role": "user", "content": "test"}])

    # Verify payload used runtime model
    call_kwargs = mock_post.call_args[1]
    payload = call_kwargs['json']
    assert payload['model'] == "runtime-model:test"

    # Restore
    config.OLLAMA_MODEL = original_model
```

**TC-1.2.3: Request URL Construction**
```python
@patch('requests.post')
def test_url_uses_current_base_url(mock_post):
    """Verify API URL uses current config.OLLAMA_BASE_URL value"""
    from rev import config
    from rev.llm.client import ollama_chat

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": {"role": "assistant", "content": "test"}}
    mock_post.return_value = mock_response

    original_url = config.OLLAMA_BASE_URL
    config.OLLAMA_BASE_URL = "http://custom-server:8080"

    ollama_chat([{"role": "user", "content": "test"}])

    # Verify URL
    call_args = mock_post.call_args[0]
    url = call_args[0]
    assert url == "http://custom-server:8080/api/chat"

    config.OLLAMA_BASE_URL = original_url
```

**TC-1.2.4: Cloud Authentication Flow**
```python
@patch('requests.post')
@patch('builtins.input', return_value='')  # Simulate user pressing Enter
def test_cloud_auth_flow(mock_input, mock_post):
    """Verify 401 triggers authentication prompt and retry"""
    from rev.llm.client import ollama_chat

    # First call: 401 with signin_url
    auth_response = MagicMock()
    auth_response.status_code = 401
    auth_response.json.return_value = {
        "signin_url": "https://ollama.com/connect?key=test123"
    }

    # Second call: Success after auth
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {
        "message": {"role": "assistant", "content": "authenticated"}
    }

    # Return 401 first, then success
    mock_post.side_effect = [auth_response, success_response]

    result = ollama_chat([{"role": "user", "content": "test"}])

    # Verify authentication prompt was shown (input was called)
    assert mock_input.called

    # Verify retry happened (2 calls total)
    assert mock_post.call_count == 2

    # Verify success after auth
    assert result["message"]["content"] == "authenticated"
```

**TC-1.2.5: Tool Support Fallback**
```python
@patch('requests.post')
def test_tool_fallback_on_400(mock_post):
    """Verify 400 error with tools triggers retry without tools"""
    from rev.llm.client import ollama_chat

    # First call with tools: 400
    error_response = MagicMock()
    error_response.status_code = 400
    error_response.text = "model does not support tools"

    # Second call without tools: Success
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {
        "message": {"role": "assistant", "content": "no tools"}
    }

    mock_post.side_effect = [error_response, success_response]

    # Call with tools
    tools = [{"type": "function", "function": {"name": "test"}}]
    result = ollama_chat([{"role": "user", "content": "test"}], tools=tools)

    # Verify 2 calls made
    assert mock_post.call_count == 2

    # Verify first call had tools
    first_call = mock_post.call_args_list[0]
    assert 'tools' in first_call[1]['json']

    # Verify second call had no tools
    second_call = mock_post.call_args_list[1]
    assert 'tools' not in second_call[1]['json']
```

**TC-1.2.6: Retry Logic with Timeouts**
```python
@patch('requests.post')
def test_timeout_retry_progression(mock_post):
    """Verify timeouts increase: 600s, 1200s, 1800s"""
    from rev.llm.client import ollama_chat
    import requests

    # All attempts timeout
    mock_post.side_effect = requests.exceptions.Timeout("timeout")

    result = ollama_chat([{"role": "user", "content": "test"}])

    # Verify 3 attempts made
    assert mock_post.call_count == 3

    # Verify timeout values
    timeouts = [call[1]['timeout'] for call in mock_post.call_args_list]
    assert timeouts == [600, 1200, 1800]

    # Verify error returned
    assert "error" in result
    assert "timeout" in result["error"].lower()
```

**TC-1.2.7: Cache Integration**
```python
@patch('requests.post')
def test_llm_cache_hit(mock_post):
    """Verify identical requests use cache"""
    from rev.llm.client import ollama_chat
    from rev.cache import get_llm_cache

    # Clear cache
    cache = get_llm_cache()
    cache.clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": "cached"}
    }
    mock_post.return_value = mock_response

    messages = [{"role": "user", "content": "test"}]

    # First call
    result1 = ollama_chat(messages)
    assert mock_post.call_count == 1

    # Second call with same messages
    result2 = ollama_chat(messages)

    # Should still be 1 (used cache)
    assert mock_post.call_count == 1

    # Results should match
    assert result1 == result2
```

---

### 1.3 CLI Argument Parsing (`tests/test_cli.py`)

#### Test Cases:

**TC-1.3.1: Model Argument Parsing**
```python
def test_model_argument_default():
    """Verify --model defaults to config.OLLAMA_MODEL"""
    # Test with CLI
    # (Use subprocess or argparse directly)

def test_model_argument_custom():
    """Verify --model accepts custom value"""
    # Parse args with --model custom-model:test
    # Verify args.model == "custom-model:test"

def test_model_argument_updates_config():
    """Verify --model updates config.OLLAMA_MODEL"""
    # After parsing args with --model custom
    # Verify config.OLLAMA_MODEL == "custom"
```

**TC-1.3.2: Base URL Argument Parsing**
```python
def test_base_url_argument_default():
    """Verify --base-url defaults to config.OLLAMA_BASE_URL"""

def test_base_url_argument_custom():
    """Verify --base-url accepts custom value"""

def test_base_url_argument_updates_config():
    """Verify --base-url updates config.OLLAMA_BASE_URL"""
```

---

## 2. Integration Tests

### 2.1 CLI → Config → Client Flow (`tests/test_integration.py`)

**TC-2.1.1: End-to-End Model Parameter**
```python
@patch('requests.post')
def test_e2e_model_parameter(mock_post):
    """Test complete flow: CLI arg → config → API call"""
    import subprocess

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": {"role": "assistant", "content": "test"}}
    mock_post.return_value = mock_response

    # Run CLI with custom model
    # Capture what model was used in API call
    # Verify it matches CLI argument
```

**TC-2.1.2: End-to-End Cloud Model Auth**
```python
def test_e2e_cloud_model_auth():
    """Test cloud model authentication flow end-to-end"""
    # Mock Ollama API responses (401 then 200)
    # Mock user input (simulate Enter press)
    # Run CLI with cloud model
    # Verify auth prompt appears
    # Verify retry succeeds
```

---

## 3. End-to-End Tests

### 3.1 Real Ollama Integration (`tests/test_e2e.py`)

**Note:** These tests require Ollama running locally.

**TC-3.1.1: Real API Call**
```python
@pytest.mark.integration
def test_real_ollama_request():
    """Test actual request to running Ollama"""
    from rev.llm.client import ollama_chat
    from rev import config
    import requests

    # Skip if Ollama not running
    try:
        requests.get(f"{config.OLLAMA_BASE_URL}/api/version", timeout=1)
    except:
        pytest.skip("Ollama not running")

    # Make real request
    result = ollama_chat([{"role": "user", "content": "Say 'test' in one word"}])

    # Verify response format
    assert "message" in result or "error" in result
```

**TC-3.1.2: Model Switching**
```python
@pytest.mark.integration
def test_real_model_switching():
    """Test switching models works correctly"""
    from rev import config
    import requests

    # Skip if Ollama not running
    try:
        requests.get(f"{config.OLLAMA_BASE_URL}/api/version", timeout=1)
    except:
        pytest.skip("Ollama not running")

    # Get available models
    models = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags").json()

    if len(models.get("models", [])) < 2:
        pytest.skip("Need at least 2 models for this test")

    # Test switching between models
    # Verify each request uses correct model
```

---

## 4. Edge Case Tests

### 4.1 Error Conditions (`tests/test_edge_cases.py`)

**TC-4.1.1: Ollama Not Running**
```python
@patch('requests.post')
def test_connection_refused(mock_post):
    """Test behavior when Ollama is not running"""
    from rev.llm.client import ollama_chat
    import requests

    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    result = ollama_chat([{"role": "user", "content": "test"}])

    assert "error" in result
    assert "Connection" in result["error"] or "connection" in result["error"]
```

**TC-4.1.2: Model Not Found**
```python
@patch('requests.post')
def test_model_not_found_404(mock_post):
    """Test 404 model not found error"""
    from rev.llm.client import ollama_chat

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = '{"error":"model \'nonexistent:model\' not found"}'
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    mock_post.return_value = mock_response

    result = ollama_chat([{"role": "user", "content": "test"}])

    assert "error" in result
```

**TC-4.1.3: Invalid JSON Response**
```python
@patch('requests.post')
def test_invalid_json_response(mock_post):
    """Test handling of malformed JSON"""
    from rev.llm.client import ollama_chat

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = json.JSONDecodeError("bad json", "", 0)
    mock_response.text = "not json"
    mock_post.return_value = mock_response

    result = ollama_chat([{"role": "user", "content": "test"}])

    assert "error" in result
```

**TC-4.1.4: Network Timeout Mid-Request**
```python
@patch('requests.post')
def test_network_timeout(mock_post):
    """Test network timeout during request"""
    from rev.llm.client import ollama_chat
    import requests

    mock_post.side_effect = requests.exceptions.Timeout()

    result = ollama_chat([{"role": "user", "content": "test"}])

    assert "error" in result
    assert "timeout" in result["error"].lower()
```

**TC-4.1.5: Auth Cancelled by User**
```python
@patch('requests.post')
@patch('builtins.input', side_effect=KeyboardInterrupt())
def test_auth_cancelled(mock_input, mock_post):
    """Test user cancelling authentication"""
    from rev.llm.client import ollama_chat

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {
        "signin_url": "https://ollama.com/connect?key=test"
    }
    mock_post.return_value = mock_response

    result = ollama_chat([{"role": "user", "content": "test"}])

    assert "error" in result
    assert "cancelled" in result["error"].lower()
```

**TC-4.1.6: Empty Messages List**
```python
def test_empty_messages():
    """Test handling of empty messages list"""
    from rev.llm.client import ollama_chat

    result = ollama_chat([])

    # Should handle gracefully (either error or make request)
    assert isinstance(result, dict)
```

**TC-4.1.7: Very Large Messages**
```python
@patch('requests.post')
def test_large_message_payload(mock_post):
    """Test handling of very large messages"""
    from rev.llm.client import ollama_chat

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": {"role": "assistant", "content": "ok"}}
    mock_post.return_value = mock_response

    # Create large message (1MB)
    large_content = "x" * (1024 * 1024)
    result = ollama_chat([{"role": "user", "content": large_content}])

    # Should handle without error
    assert "error" not in result or mock_post.called
```

---

## 5. Performance Tests

### 5.1 Caching Performance (`tests/test_performance.py`)

**TC-5.1.1: Cache Speed Improvement**
```python
def test_cache_performance():
    """Verify cache provides speed improvement"""
    import time
    from rev.llm.client import ollama_chat
    from rev.cache import get_llm_cache

    cache = get_llm_cache()
    cache.clear()

    messages = [{"role": "user", "content": "test"}]

    # First call (no cache)
    start1 = time.time()
    result1 = ollama_chat(messages)
    duration1 = time.time() - start1

    # Second call (from cache)
    start2 = time.time()
    result2 = ollama_chat(messages)
    duration2 = time.time() - start2

    # Cache should be significantly faster
    assert duration2 < duration1 * 0.1  # 10x faster
```

**TC-5.1.2: Cache Memory Usage**
```python
def test_cache_memory_reasonable():
    """Verify cache doesn't use excessive memory"""
    from rev.cache import get_llm_cache
    import sys

    cache = get_llm_cache()

    # Add many entries
    for i in range(1000):
        cache.set_response(
            [{"role": "user", "content": f"test {i}"}],
            {"message": {"role": "assistant", "content": f"response {i}"}}
        )

    # Check size
    cache_size = sys.getsizeof(cache)
    assert cache_size < 100 * 1024 * 1024  # Less than 100MB
```

---

## 6. Regression Tests

### 6.1 Prevent Known Bugs (`tests/test_regressions.py`)

**TC-6.1.1: Model Parameter Bug (Commit 3088c5d)**
```python
def test_regression_model_parameter_3088c5d():
    """
    Regression test for: --model parameter not being honored

    Bug: Direct import captured default value at import time
    Fix: Changed to module import for runtime value access
    Commit: 3088c5d
    Date: Nov 21, 2024
    """
    from rev import config
    from rev.llm import client
    import inspect

    # Verify fix is in place
    source = inspect.getsource(client)
    assert "from rev import config" in source
    assert "from rev.config import OLLAMA_MODEL" not in source

    # Functional test
    original = config.OLLAMA_MODEL
    config.OLLAMA_MODEL = "regression-test:model"

    # Verify config change is used
    # (Mock API call and check payload)

    config.OLLAMA_MODEL = original
```

---

## Test Execution

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific category
pytest tests/test_config.py -v
pytest tests/test_ollama_client.py -v
pytest tests/test_edge_cases.py -v

# Run with coverage
pytest tests/ --cov=rev --cov-report=html --cov-report=term-missing

# Run integration tests only (requires Ollama)
pytest tests/ -v -m integration

# Skip integration tests
pytest tests/ -v -m "not integration"

# Run regression tests only
pytest tests/test_regressions.py -v

# Run with debug output
pytest tests/ -v -s

# Run parallel (faster)
pytest tests/ -n auto
```

### Continuous Integration

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install -r requirements.txt pytest pytest-cov

      - name: Run unit tests
        run: pytest tests/ -v --cov=rev --cov-report=xml -m "not integration"

      - name: Upload coverage
        uses: codecov/codecov-action@v2

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Install Ollama
        run: curl -fsSL https://ollama.ai/install.sh | sh

      - name: Pull test model
        run: ollama pull codellama:latest

      - name: Run integration tests
        run: pytest tests/ -v -m integration
```

---

## Test Coverage Goals

| Component | Target Coverage | Priority |
|-----------|----------------|----------|
| `config.py` | 100% | High |
| `llm/client.py` | 95% | High |
| `main.py` | 90% | High |
| `execution/*` | 80% | Medium |
| `tools/*` | 75% | Medium |
| `cache/*` | 85% | Medium |

---

## Manual Testing Checklist

### Cloud Model Testing

- [ ] Start Ollama: `ollama serve`
- [ ] Run cloud model: `rev --model qwen3-coder:480b-cloud "test"`
- [ ] Verify authentication prompt appears
- [ ] Complete authentication in browser
- [ ] Verify request succeeds after auth
- [ ] Run again - verify no re-auth needed

### Model Switching Testing

- [ ] Pull multiple models: `ollama pull llama3.1:latest`, `ollama pull qwen2.5:7b`
- [ ] Test each model: `rev --model llama3.1:latest "test"`
- [ ] Verify correct model used in debug output
- [ ] Test invalid model name - verify error message

### Error Condition Testing

- [ ] Stop Ollama - verify clear error message
- [ ] Use non-existent model - verify helpful error
- [ ] Start Ollama mid-request - verify retry works
- [ ] Network disconnect during request - verify error handling

---

## Future Test Improvements

1. **Mutation Testing** - Use `mutmut` to verify test quality
2. **Property-Based Testing** - Use `hypothesis` for edge cases
3. **Load Testing** - Test with many concurrent requests
4. **Security Testing** - Test for injection vulnerabilities
5. **Fuzzing** - Test with malformed inputs

---

## Test Documentation

Each test should include:

```python
def test_example():
    """
    Test description: What this test verifies

    Given: Initial conditions
    When: Action taken
    Then: Expected outcome

    Related: TC-X.Y.Z
    """
    # Arrange
    # ... setup ...

    # Act
    # ... perform action ...

    # Assert
    # ... verify results ...
```

---

## Appendix: Mock Data Examples

```python
# Mock Ollama Responses
MOCK_SUCCESS = {
    "model": "llama3.1:latest",
    "created_at": "2024-11-21T00:00:00Z",
    "message": {
        "role": "assistant",
        "content": "Test response"
    },
    "done": True
}

MOCK_401_CLOUD = {
    "error": "Unauthorized",
    "signin_url": "https://ollama.com/connect?name=test-device&key=abc123"
}

MOCK_404_NOT_FOUND = {
    "error": "model 'nonexistent:model' not found"
}

MOCK_400_NO_TOOLS = {
    "error": "this model does not support tools"
}

MOCK_TIMEOUT = requests.exceptions.Timeout("Request timed out")

MOCK_CONNECTION_ERROR = requests.exceptions.ConnectionError("Connection refused")
```
