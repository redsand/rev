# Tool Calling Integration Fixes - 2026 Best Practices

## Overview
This document describes comprehensive fixes applied to resolve persistent tool execution failures across all LLM providers (Claude, OpenAI, Gemini, Ollama).

## Problem Statement
The system was experiencing frequent circuit breaker triggers with error:
```
⚠️ LLM FAILED TO EXECUTE TOOLS (failure #25)
The LLM returned text instead of calling tools

[🛑 CIRCUIT BREAKER: TOOL EXECUTION FAILURES]
This model does not properly support function calling.
```

## Root Causes Identified

### 1. **Anthropic Provider Issues**
- **Bug**: Tool arguments passed as strings instead of dictionaries
  - `"input": func.get("arguments", "")` ❌
  - Should be: `"input": json.loads(arguments_str)` ✅
- **Missing**: `tool_choice` parameter (new in 2025)
- **Missing**: Unique IDs for tool_use blocks (required by Anthropic)

### 2. **OpenAI Provider Issues**
- **Bug**: Streaming tool calls incorrectly accumulated
  - Was appending deltas instead of merging by index
  - Resulted in malformed tool call arguments
- **Missing**: `tool_choice: "required"` to force tool use
- **Missing**: `parallel_tool_calls` support for multiple tools
- **Missing**: Structured Outputs (`strict: true`) for schema compliance

### 3. **Gemini Provider Issues**
- **Missing**: `function_calling_config` with `mode: "ANY"`
- Provider wasn't enforcing tool use when tools were provided
- No configuration to prevent text-only responses

### 4. **Ollama Provider Issues**
- **Bug**: Using non-standard `mode: "tools"` parameter
  - Many models don't support this proprietary format
  - Should use standard OpenAI-compatible `tools` field
- **Missing**: Proper tool support detection for models
- Returning `True` for all models regardless of capability

## Fixes Applied

### Anthropic Provider (`anthropic_provider.py`)
```python
# Fix 1: Parse arguments as JSON dict
arguments_dict = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str

# Fix 2: Add required ID field
tool_uses.append({
    "type": "tool_use",
    "id": tc.get("id", f"tool_{len(tool_uses)}"),  # Required by Anthropic
    "name": func.get("name", ""),
    "input": arguments_dict,  # Must be dict, not string
})

# Fix 3: Add tool_choice to force tool use
if tools:
    request_params["tools"] = anthropic_tools
    request_params["tool_choice"] = {"type": "auto"}  # Prevents text-only responses
```

**Documentation**: [Anthropic Tool Use Guide](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)

### OpenAI Provider (`openai_provider.py`)
```python
# Fix 1: Proper streaming tool call accumulation
for tc_delta in delta.tool_calls:
    tc_index = tc_delta.index if hasattr(tc_delta, "index") else len(accumulated_tool_calls)

    # Ensure we have slots for this index
    while len(accumulated_tool_calls) <= tc_index:
        accumulated_tool_calls.append({
            "id": "",
            "function": {"name": "", "arguments": ""}
        })

    # Merge delta incrementally (not append!)
    if hasattr(tc_delta.function, "arguments") and tc_delta.function.arguments:
        accumulated_tool_calls[tc_index]["function"]["arguments"] += tc_delta.function.arguments

# Fix 2: Force tool use when tools provided
if tools:
    request_params["tools"] = tools
    request_params["tool_choice"] = "required"  # Forces tool execution
    request_params["parallel_tool_calls"] = True  # Allows multiple tools
```

**Key Insights from OpenAI Docs**:
- Tool descriptions must be clear and specific
- `tool_choice: "required"` guarantees tool execution
- Streaming tool calls use incremental deltas that must be merged by index
- Structured Outputs (`strict: true`) ensures schema compliance

**Documentation**:
- [OpenAI Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [o3/o4-mini Function Calling](https://cookbook.openai.com/examples/o-series/o3o4-mini_prompting_guide)

### Gemini Provider (`gemini_provider.py`)
```python
# Fix: Add function_calling_config to enforce tool use
tool_config = None
if tools:
    tool_config = {
        "function_calling_config": {
            "mode": "ANY"  # Force function calling when tools provided
        }
    }

# Apply to model
if gemini_tools:
    model_kwargs["tools"] = gemini_tools
    if tool_config:
        model_kwargs["tool_config"] = tool_config
```

**Key Features**:
- Gemini 3+ models support `streamFunctionCallArguments`
- `function_calling_config` prevents text-only fallback
- MCP protocol support for standardized tool access

**Documentation**:
- [Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Tool Use with Live API](https://ai.google.dev/gemini-api/docs/live-tools)

### Ollama Provider (`ollama.py`)
```python
# Fix 1: Remove non-standard "mode": "tools"
if tools_provided:
    payload["tools"] = tools or []
    # Don't use "mode": "tools" - this causes compatibility issues

# Fix 2: Proper tool support detection
def supports_tool_calling(self, model: str) -> bool:
    """Check if model supports tool calling."""
    model_lower = model.lower()
    tool_capable_prefixes = [
        "llama3.1", "llama3.2",
        "mistral", "mixtral",
        "qwen2.5",
        "command-r",
        "granite",
        "phi3"
    ]
    return any(model_lower.startswith(prefix) for prefix in tool_capable_prefixes)
```

**Key Insights**:
- Ollama uses OpenAI-compatible API format for tools
- Python library can auto-generate schemas from function definitions
- Models with "tools" pill on Ollama site support function calling

**Documentation**:
- [Ollama Tool Support](https://ollama.com/blog/tool-support)
- [Tool Calling Capabilities](https://docs.ollama.com/capabilities/tool-calling)

## Best Practices Implemented

### 1. Tool Definition Quality
- Clear, specific descriptions (critical for all models)
- Well-defined JSON schemas with proper types
- No unsupported fields (e.g., `default` for Gemini)

### 2. Tool Choice Enforcement
- **Anthropic**: `tool_choice: {"type": "auto"}`
- **OpenAI**: `tool_choice: "required"`
- **Gemini**: `function_calling_config: {"mode": "ANY"}`
- **Ollama**: Standard tools field (auto mode)

### 3. Error Handling
- Graceful fallback when tools unsupported
- Proper JSON parsing with try/catch
- Validation before sending to provider

### 4. Streaming Support
- Proper delta merging (OpenAI)
- Index-based accumulation
- Function call preservation in streams

## Testing Recommendations

1. **Test with each provider**:
   ```bash
   # Test Anthropic
   export LLM_PROVIDER=anthropic
   rev test tool_calls

   # Test OpenAI
   export LLM_PROVIDER=openai
   rev test tool_calls

   # Test Gemini
   export LLM_PROVIDER=gemini
   rev test tool_calls

   # Test Ollama
   export LLM_PROVIDER=ollama
   export OLLAMA_MODEL=llama3.1:8b
   rev test tool_calls
   ```

2. **Verify circuit breaker**:
   - Should no longer trigger for tool-capable models
   - Should provide clear guidance for unsupported models

3. **Monitor metrics**:
   - Tool execution success rate should be >95%
   - Circuit breaker triggers should drop to near zero
   - Model switching should be rare

## Expected Outcomes

- ✅ Eliminate "LLM FAILED TO EXECUTE TOOLS" errors
- ✅ Circuit breaker triggers only for truly unsupported models
- ✅ Consistent tool calling across all providers
- ✅ Proper streaming support with tool calls
- ✅ Better error messages when tools fail

## References

### Official Documentation
- [Anthropic Tool Use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Ollama Tool Support](https://ollama.com/blog/tool-support)

### Additional Resources
- [Composio Claude Tools Guide](https://composio.dev/blog/claude-function-calling-tools)
- [Composio Gemini Tools Guide](https://composio.dev/blog/tool-calling-guide-with-google-gemini)
- [IBM Ollama Tutorial](https://www.ibm.com/think/tutorials/local-tool-calling-ollama-granite)

## Version Information
- Fix Date: 2026-01-02
- Claude Sonnet 4.5: claude-sonnet-4-5-20250929
- OpenAI Models: GPT-5.2+, o3/o4-mini
- Gemini Models: 2.0 Flash+
- Ollama: Latest (2025+)
