# Gemini Schema Sanitization Fix

## Problem

Gemini API was rejecting tool schemas with error:
```
400 * GenerateContentRequest.tools[0].function_declarations[13].parameters.properties[add].items.required[1]: property is not defined
```

## Root Cause

The `rewrite_python_function_parameters` tool (tool index 13) has a schema where:
1. There's a property named `"add"` which is an array
2. The array items have a property named `"default"` (used to specify default parameter values)
3. The schema also uses `"default"` as a keyword to provide default values for optional fields

Example:
```json
"add": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "default": {"type": "string"}  // ← Property NAME
        },
        "required": ["name", "default"]
    },
    "default": []  // ← Schema KEYWORD
}
```

**The Issue**: The original sanitization removed ALL occurrences of `"default"`, including when it was used as a property name. This made the `required` array invalid because it referenced a property (`"default"`) that no longer existed in `properties`.

## Solution

Enhanced `_sanitize_schema()` in `gemini_provider.py` to distinguish between:

1. **Property names** (keys inside `"properties"` dict) - PRESERVE these
2. **Schema keywords** (like `"default": []` providing default values) - REMOVE these

### Key Changes

**Before**: Removed "default" everywhere, breaking property names
```python
if key in {"default", "oneOf", "anyOf", "allOf"}:
    continue
```

**After**: Preserve property names, only remove schema keywords
```python
# Special handling for "properties" - preserve ALL property names
if key == "properties":
    result[key] = {
        prop_name: self._sanitize_schema(prop_value, is_property_value=True)
        for prop_name, prop_value in value.items()
        # ← Property names like "default", "add", etc. are preserved
    }
    continue

# Remove "default" only as a schema keyword
if key == "default":
    continue  # Skip default values
```

## Files Modified

- **rev/llm/providers/gemini_provider.py**
  - `_sanitize_schema()` (lines 113-173) - Enhanced to preserve property names

## Files Created

- **tests/test_gemini_schema_sanitization.py** - Comprehensive test suite (7 tests)
- **tests/test_gemini_rewrite_params_tool.py** - Specific test for the problematic tool
- **docs/GEMINI_SCHEMA_FIX.md** - This document

## Test Results

All tests passing ✅

**test_gemini_schema_sanitization.py**:
- Removes unsupported keywords ✓
- Filters invalid required fields ✓
- Sanitizes nested array items ✓
- Sanitizes deeply nested schemas ✓
- Handles arrays with primitive items ✓
- Removes empty required arrays ✓
- Full tool conversion ✓

**test_gemini_rewrite_params_tool.py**:
- Property name 'default' preserved ✓
- Schema keyword 'default' removed ✓
- Required fields validated correctly ✓

## Sanitized Output

**Before** (broken):
```json
"add": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"}
            // ← "default" property MISSING!
        },
        "required": ["name", "default"]  // ← Invalid! "default" doesn't exist
    }
}
```

**After** (fixed):
```json
"add": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "default": {"type": "string"}  // ← Property preserved
        },
        "required": ["name", "default"]  // ← Valid!
    }
    // "default": [] removed (schema keyword)
}
```

## Impact

Gemini integration now works correctly with all tools, including:
- `rewrite_python_function_parameters`
- Any other tools with property names that match schema keywords (`default`, `type`, etc.)

## Usage

No changes needed - fix is automatic when using Gemini provider:

```bash
rev "your request" --llm-provider gemini --model gemini-2.0-flash-exp
```

## Related Issues

This fix also improves handling of:
- Properties named "type", "format", "pattern" (though these are less common)
- Nested schemas in array items with complex required fields
- Deeply nested object schemas

## Technical Details

### Gemini Schema Requirements

1. ✅ No "default" keyword (for providing default values)
2. ✅ No "oneOf", "anyOf", "allOf" keywords
3. ✅ "required" arrays must only reference properties that exist
4. ✅ Property names can be anything (including "default")

### Sanitization Strategy

1. **Preserve structure**: Don't remove property names from `properties` dict
2. **Remove keywords**: Remove unsupported schema keywords at schema level
3. **Validate required**: Filter `required` arrays to only include existing properties
4. **Recursive**: Apply to all nested schemas (items, additionalProperties, etc.)

---

**Status**: ✅ Complete and tested
**Affected Providers**: Gemini only (OpenAI, Anthropic, Ollama use different schemas)
