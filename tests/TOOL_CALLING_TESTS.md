# Tool Calling Tests - Regression Prevention

## Overview

This document describes the comprehensive test suite for tool calling functionality across all LLM providers. These tests prevent regression of the critical bugs fixed in January 2026.

## Test Files

### 1. **test_tool_calling_integration.py** (NEW)
Comprehensive integration tests for all provider-specific tool calling fixes.

**Coverage:**
- ✅ Anthropic: Arguments parsed as dicts, not strings
- ✅ Anthropic: Required tool_use IDs present
- ✅ Anthropic: tool_choice parameter enforcement
- ✅ OpenAI: Streaming tool calls merged by index (not appended)
- ✅ OpenAI: tool_choice='required' forces tool execution
- ✅ OpenAI: parallel_tool_calls enabled
- ✅ Gemini: function_calling_config with mode='ANY'
- ✅ Gemini: Unsupported schema fields removed
- ✅ Ollama: Standard tools format (no 'mode: tools')
- ✅ Ollama: Cloud model detection (:cloud suffix)
- ✅ Ollama: Model family detection (llama3.1, qwen3, deepseek, etc.)

### 2. **test_provider_conformance.py** (EXISTING)
Interface compliance tests ensuring all providers implement the base interface correctly.

**Coverage:**
- Provider interface methods (chat, chat_stream, supports_tool_calling, etc.)
- Return type validation
- Error classification consistency
- Token counting accuracy
- Retry configuration validation

### 3. **test_llm_client.py** (UPDATED)
Legacy client tests - **updated to remove outdated 'mode: tools' check**.

**Changes:**
- ❌ Old: `assert payload["mode"] == "tools"`
- ✅ New: `assert "mode" not in payload`

## Running the Tests

### Quick Start
```bash
# Run all tests
make test

# Run with coverage
make coverage

# Run specific test file
python -m pytest tests/test_tool_calling_integration.py -v

# Run specific test class
python -m pytest tests/test_tool_calling_integration.py::TestAnthropicToolCalling -v

# Run specific test
python -m pytest tests/test_tool_calling_integration.py::TestAnthropicToolCalling::test_converts_tool_arguments_to_dict_not_string -v
```

### Detailed Test Execution

#### All Tool Calling Tests
```bash
pytest tests/test_tool_calling_integration.py -v --tb=short
```

#### Provider Conformance Tests
```bash
pytest tests/test_provider_conformance.py -v
```

#### With Coverage Report
```bash
pytest tests/test_tool_calling_integration.py --cov=rev.llm.providers --cov-report=html
open htmlcov/index.html  # View coverage report
```

## Test Categories

### 1. **Critical Regression Tests**
These tests prevent the specific bugs we fixed:

```python
# Anthropic: Arguments must be dicts, not strings
test_anthropic_arguments_are_not_strings()

# OpenAI: Streaming must merge by index, not append
test_streaming_tool_calls_merged_by_index()

# Ollama: No 'mode: tools' in payload
test_ollama_no_mode_tools_in_payload()
```

### 2. **Best Practices Enforcement**
These tests ensure 2026 best practices are followed:

```python
# Tool choice enforcement
test_includes_tool_choice_when_tools_provided()  # Anthropic
test_sets_tool_choice_required_when_tools_provided()  # OpenAI
test_includes_function_calling_config_with_tools()  # Gemini
```

### 3. **Cloud Model Detection**
These tests verify Ollama cloud model support:

```python
test_cloud_model_detection_with_cloud_suffix()
test_model_family_detection()
test_cloud_model_with_version_tag()
```

## Expected Test Results

All tests should **PASS** with the current implementation:

```
tests/test_tool_calling_integration.py::TestAnthropicToolCalling::test_converts_tool_arguments_to_dict_not_string PASSED
tests/test_tool_calling_integration.py::TestAnthropicToolCalling::test_adds_required_tool_use_id PASSED
tests/test_tool_calling_integration.py::TestAnthropicToolCalling::test_handles_malformed_json_arguments_gracefully PASSED
tests/test_tool_calling_integration.py::TestAnthropicToolCalling::test_includes_tool_choice_when_tools_provided PASSED
tests/test_tool_calling_integration.py::TestOpenAIToolCalling::test_streaming_tool_calls_merged_by_index PASSED
tests/test_tool_calling_integration.py::TestOpenAIToolCalling::test_sets_tool_choice_required_when_tools_provided PASSED
tests/test_tool_calling_integration.py::TestGeminiToolCalling::test_includes_function_calling_config_with_tools PASSED
tests/test_tool_calling_integration.py::TestGeminiToolCalling::test_removes_unsupported_schema_fields PASSED
tests/test_tool_calling_integration.py::TestOllamaToolCalling::test_uses_standard_tools_format_not_mode_tools PASSED
tests/test_tool_calling_integration.py::TestOllamaToolCalling::test_cloud_model_detection_with_cloud_suffix PASSED
tests/test_tool_calling_integration.py::TestOllamaToolCalling::test_model_family_detection PASSED
tests/test_tool_calling_integration.py::TestOllamaToolCalling::test_cloud_model_with_version_tag PASSED
```

## Continuous Integration

These tests should be run:
1. **Pre-commit** - Run before committing changes to provider code
2. **PR validation** - Run on all pull requests
3. **Nightly** - Full test suite with all providers
4. **Before release** - Complete validation with real API calls (optional)

## Troubleshooting

### Test Failures

#### "AssertionError: Tool input must be dict, not string!"
**Cause:** Anthropic provider is passing arguments as strings instead of dicts.
**Fix:** Check `anthropic_provider.py` lines 55-61 for JSON parsing logic.

#### "AssertionError: tool_choice not in call_kwargs"
**Cause:** Provider isn't setting tool_choice parameter.
**Fix:** Check provider's chat() method for tool_choice configuration.

#### "AssertionError: Should not use non-standard 'mode' parameter"
**Cause:** Ollama provider is using deprecated 'mode: tools' format.
**Fix:** Check `ollama.py` lines 271-274 and ensure "mode" is not in payload.

### Test Environment

If tests fail due to missing dependencies:
```bash
# Install test dependencies
pip install -e ".[dev]"

# Or install minimal test requirements
pip install pytest pytest-asyncio pytest-cov
```

## Verification Checklist

Before merging changes to LLM providers, verify:

- [ ] All tests in `test_tool_calling_integration.py` pass
- [ ] All tests in `test_provider_conformance.py` pass
- [ ] Updated `test_llm_client.py` passes
- [ ] No new deprecation warnings
- [ ] Code coverage >= 80% for changed files

## Adding New Tests

When adding new provider features:

1. **Add test to appropriate class:**
   ```python
   class TestNewFeature:
       def test_feature_works_correctly(self):
           provider = YourProvider(api_key="test")
           result = provider.new_feature()
           assert result == expected_value
   ```

2. **Add regression test:**
   ```python
   class TestToolCallingRegression:
       def test_new_bug_doesnt_regress(self):
           # Test that prevents the bug from returning
           pass
   ```

3. **Document the test** in this file

## References

- [Tool Calling Fixes Documentation](../TOOL_CALLING_FIXES.md)
- [Provider Conformance Guide](test_provider_conformance.py)
- [pytest Documentation](https://docs.pytest.org/)

## Version History

- **2026-01-02**: Initial test suite created
  - Comprehensive coverage for Anthropic, OpenAI, Gemini, Ollama
  - Cloud model detection tests
  - Regression prevention tests
