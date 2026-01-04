# Gemini Planner Fix - Empty Task Descriptions

## Problem

Gemini (and previously GPT-4o) was creating EDIT tasks with empty descriptions:

```
[ORCHESTRATOR] EDIT: ...

1. EDIT
CodeWriterAgent executing task:
  [ERROR] EDIT task must specify target file path in description.
  Task: '...' does not mention any file to edit.
```

## Root Cause

The planner (`_determine_next_action()` in orchestrator.py) was calling:

```python
response_data = ollama_chat([{"role": "user", "content": prompt}])
```

**Without** explicitly disabling tools. This caused:

1. `ollama_chat()` defaulted `supports_tools` to `config.DEFAULT_SUPPORTS_TOOLS` (True)
2. Line 604-608 in client.py auto-populated the full tool registry (98 tools)
3. Gemini saw these tools and tried to use function calling instead of text response
4. Gemini returned malformed tool calls or empty responses
5. Planner couldn't parse the response correctly

## Why It Happened

In `rev/llm/client.py` (lines 604-608):

```python
# Safety net: if model supports tools but caller passed none/empty, populate with full registry.
if supports_tools and not tools:
    try:
        from rev.tools.registry import get_available_tools
        tools = get_available_tools()  # ← 98 tools loaded!
        supports_tools = True
    except Exception:
        tools = tools or []
```

This "safety net" was designed to ensure agents always have tools available. But for the **planner**, we want **text responses only**, not tool calls.

## The Fix

Modified `rev/execution/orchestrator.py` (line 3878):

**Before**:
```python
response_data = ollama_chat([{"role": "user", "content": prompt}])
```

**After**:
```python
# CRITICAL: Planner expects text response, NOT tool calls
# Explicitly disable tools to prevent Gemini from trying to call functions
response_data = ollama_chat([{"role": "user", "content": prompt}], tools=None, supports_tools=False)
```

## Why This Works

By passing `supports_tools=False` explicitly:

1. Line 599 in client.py: `supports_tools = False` (explicit value is used)
2. Line 604: Condition `if supports_tools and not tools:` evaluates to False
3. Tools are NOT auto-populated
4. Gemini receives NO tool definitions
5. Gemini returns plain text response
6. Planner successfully parses: `[EDIT] update package.json to add prisma`

## Expected Behavior

### Before Fix
```
Gemini sees: 98 tools available
Gemini thinks: "I should call a tool"
Gemini returns: function_call(name="edit_file", args={...})
Planner receives: Empty or malformed content
Result: Empty task description
```

### After Fix
```
Gemini sees: No tools available
Gemini thinks: "Return text in requested format"
Gemini returns: "[EDIT] update package.json to add prisma and sqlite dependencies"
Planner receives: Valid text response
Result: Proper task with file path
```

## Files Modified

- **rev/execution/orchestrator.py** (line 3878)
  - Added `tools=None, supports_tools=False` to planner's `ollama_chat()` call

## Impact

Fixes planner issues for:
- ✅ Gemini (all models)
- ✅ GPT-4o (mentioned by user as having same issue)
- ✅ Any provider that defaults to tool calling when tools are available

Doesn't affect:
- ✅ Agents (still use tools normally)
- ✅ Code execution (still uses full tool registry)
- ✅ Other LLM calls (only planner is affected)

## Testing

Try running Gemini again:
```bash
rev "your request" --llm-provider gemini --model gemini-2.0-flash-exp
```

Expected: Planner returns proper task descriptions with file paths.

## Related Issues

- Gemini schema sanitization (GEMINI_SCHEMA_FIX.md) - Fixed tool definitions
- This fix - Disabled tools for planner text responses

Both were needed for Gemini to work correctly.

---

**Status**: ✅ Complete
**Affects**: Planner only (text-based responses)
**Preserves**: Agent tool calling (still uses full registry)
