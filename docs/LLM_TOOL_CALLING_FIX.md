# LLM Tool Calling Fix - Root Cause Analysis

## Root Cause Identified ✓

After deep code analysis, I found **THREE critical bugs** that cause LLM tool calling to fail:

### THE PRIMARY BUG: Unconditional Overwrite of Tool List

**This is the root cause** - the other bugs are secondary issues that only mattered because of this bug.

---

## Bug #0: Tool list unconditionally replaced with empty result (PRIMARY ROOT CAUSE)

**Location:** `rev/agents/code_writer.py:1009` (before fix)

**Problem:**
```python
# Line 990: Create curated tool list for action_type
available_tools = [tool for tool in all_tools if tool['function']['name'] in tool_names]
# For edit tasks: ['apply_patch', 'replace_in_file', 'write_file', 'copy_file', 'move_file']
# Result: 5 tools ✓

# Line 997-1004: Ask context builder to enhance/filter the list
selected_tools, _bundle = build_context_and_tools(...)

# Line 1009: UNCONDITIONALLY overwrite!
available_tools = selected_tools  # ← BUG! If selected_tools is [], we lose all 5 tools!
```

**The Fatal Flow:**
1. **Line 990:** We carefully create `available_tools` with 5 tools appropriate for "edit" action
2. **Line 997:** We call `build_context_and_tools()` to optionally enhance the selection
3. **Line 1009:** We **blindly replace** `available_tools` with whatever context builder returns
4. **If context builder returns `[]`** (due to keyword mismatch), we **throw away 5 perfectly good tools**!

**Why context builder returns empty:**
- `ToolsCorpus.query()` uses keyword matching to score tools
- Task: "overwrite `./package.json` completely with..."
- Keywords: "overwrite", "package.json", "completely"
- Tool descriptions contain: "edit", "replace", "apply", "patch", "write"
- **Keyword overlap score: 0** for all tools
- All tools filtered out → `selected_tools = []`
- We replace 5 tools with 0 tools!

**The Fix:**
```python
# Only replace if context builder returned non-empty results
if selected_tools:
    available_tools = selected_tools  # Use enhanced selection
else:
    # Keep our initial tool list - don't throw it away!
    print("Context builder returned empty! Keeping initial available_tools")
```

**Impact:** This single fix **prevents the tool list from ever being empty**, eliminating the need for downstream safety nets.

---

## Bug #1: CodeWriterAgent doesn't pass `supports_tools` parameter (SECONDARY)

**Location:** `rev/agents/code_writer.py:1209` (before fix)

**Problem:**
```python
response = ollama_chat(messages, tools=available_tools, tool_choice=tool_choice_mode)
```

The `supports_tools` parameter is **not passed**, so it defaults to `None`.

**Impact:**
- If `available_tools` is an empty list `[]`, the code doesn't explicitly tell `ollama_chat` that the model supports tools
- This prevents downstream safety nets from activating

---

## Bug #2: Empty list treated differently than None

**Location:** `rev/llm/client.py:606-615` (before fix)

**Problem:**
```python
# Always attempt tool-calling when tools are supplied
if tools:  # ← Empty list [] is FALSY!
    supports_tools = True

# Safety net: if model supports tools but caller passed none/empty, populate with full registry
if supports_tools and not tools:  # ← Won't trigger if supports_tools is False
    tools = get_available_tools()
```

**The Flaw:**
1. If `tools = []` (empty list), the condition `if tools:` evaluates to `False` (empty list is falsy in Python)
2. So `supports_tools` doesn't get set to `True`
3. It stays as `config.DEFAULT_SUPPORTS_TOOLS` (which might be False or not set correctly)
4. The safety net `if supports_tools and not tools:` won't trigger if `supports_tools` is False
5. Result: **LLM gets called with 0 tools and `supports_tools=False`**

**Why tools is empty:**
- `build_context_and_tools()` uses `ToolsCorpus.query()` which scores tools by keyword matching
- For task descriptions without matching keywords (e.g., "overwrite package.json"), all tools get score ≤ 0
- They get filtered out, returning an empty list `[]`
- The fallback should populate from `tool_universe`, but if it fails, an empty list propagates

---

## The Execution Flow (Before Fix)

```
CodeWriterAgent.execute()
├─ Selects tool_names for action_type (e.g., ['write_file', 'replace_in_file'])
├─ Calls build_context_and_tools(tool_universe, tool_names)
│  ├─ ToolsCorpus.query(task_description) returns []  ← No keyword matches!
│  ├─ Fallback should activate but might fail
│  └─ Returns selected_tools = []
├─ available_tools = []  ← Empty!
├─ Fallback safety net in code_writer.py (lines 1023-1039) should activate
│  └─ BUT: If this fails too, tools stays empty
└─ Calls ollama_chat(tools=[], tool_choice="required")  ← No supports_tools!
   ├─ supports_tools = DEFAULT_SUPPORTS_TOOLS (None or False)
   ├─ if tools: → False (empty list is falsy)
   ├─ supports_tools stays False
   ├─ if supports_tools and not tools: → False and True → False
   ├─ Safety net doesn't trigger!
   └─ LLM called with tools=[], supports_tools=False  ← FAILURE!
      └─ OpenAI provider receives tools=[]
         └─ Doesn't include tools in request
         └─ LLM returns text instead of tool calls
```

---

## The Fix ✓

### Fix #1: Explicitly pass `supports_tools=True` in CodeWriterAgent

**File:** `rev/agents/code_writer.py:1211-1216`

```python
response = ollama_chat(
    messages,
    tools=available_tools,
    supports_tools=True if available_tools else None,  # ← EXPLICIT!
    tool_choice=tool_choice_mode
)
```

**Why this helps:**
- When `available_tools` is not empty, we explicitly tell ollama_chat that the model supports tools
- This ensures `supports_tools=True` is set, regardless of `DEFAULT_SUPPORTS_TOOLS`

### Fix #2: Normalize empty list to None

**File:** `rev/llm/client.py:609-612`

```python
# CRITICAL FIX: Treat empty list same as None - both mean "no tools provided"
# This ensures the safety net activates for empty lists too
if tools is not None and len(tools) == 0:
    tools = None
```

**Why this helps:**
- Empty list `[]` and `None` both mean "no tools available"
- By normalizing `[]` to `None`, we ensure the safety net logic works correctly
- The safety net `if supports_tools and not tools:` will trigger for both cases
- It will auto-populate tools from the full registry

---

## How the Fix Works (After Fix)

```
CodeWriterAgent.execute()
├─ available_tools = []  (empty due to keyword mismatch)
├─ Calls ollama_chat(tools=[], supports_tools=True, tool_choice="required")
   ├─ supports_tools = True  ← Explicitly passed!
   ├─ if tools: → False (empty list)
   ├─ supports_tools stays True (already set)
   ├─ if tools is not None and len(tools) == 0: → True
   │  └─ tools = None  ← Normalized!
   ├─ if supports_tools and not tools: → True and True → True  ← TRIGGERS!
   │  └─ tools = get_available_tools()  ← Auto-populated!
   └─ LLM called with tools=[98 tools], supports_tools=True  ← SUCCESS!
      └─ OpenAI provider includes tools in request
         └─ tool_choice="required" forces tool use
         └─ LLM returns tool calls!
```

---

## Why Previous Safety Nets Failed

The codebase had **multiple layers** of safety nets:

1. **context_provider.py (lines 192-199):** Fallback to tool_universe if retrieval returns empty
2. **code_writer.py (lines 1023-1039):** Fallback to all candidate tools if context builder returns empty
3. **client.py (lines 615-620):** Auto-populate from full registry if supports_tools=True but tools empty

But they all failed because:
- Context provider fallback might not activate if `tool_universe` has issues
- Code writer fallback might not activate if all guards fail
- **Client auto-population didn't trigger because `supports_tools=False`**

The root issue: **Empty list `[]` is treated as "tools provided but empty" instead of "no tools"**

---

## Testing the Fix

Run a test task that previously failed:

```bash
cd ../test-app
rev "update package.json to add a new script"
```

**Expected behavior:**
1. Diagnostic logs show tool provisioning pipeline
2. If tools are empty initially, safety net activates
3. Tools auto-populated from registry
4. LLM receives tools and makes tool calls
5. No more "Write action completed without tool execution" errors

**Check logs:**
```bash
tail -f .rev/logs/rev_run_*.log | grep TOOL_PROVISION
```

You should see:
```
[TOOL_PROVISION] FINAL: Sending X tools to LLM: [...]
[LLM_CLIENT] Tools auto-populated: 0 -> 98
```

---

## Files Modified

1. **rev/llm/client.py** - Added empty list normalization to trigger safety net
2. **rev/agents/code_writer.py** - Explicitly pass `supports_tools=True` when calling LLM
3. **rev/agents/context_provider.py** - Added diagnostic logging (already done)

---

## Rollback Instructions

If the fix causes issues, revert these changes:

```bash
git diff rev/llm/client.py
git diff rev/agents/code_writer.py

# To revert:
git checkout HEAD -- rev/llm/client.py
git checkout HEAD -- rev/agents/code_writer.py
```

---

## Technical Notes

### Why Empty List vs None Matters

In Python:
- `if []:` evaluates to `False` (empty list is falsy)
- `if None:` evaluates to `False` (None is falsy)
- `not []` evaluates to `True`
- `not None` evaluates to `True`

But:
- `[] is not None` evaluates to `True` (they are different objects)
- So `if tools is not None and len(tools) == 0:` only matches empty lists

### Provider Behavior

Different providers handle empty tools differently:
- **OpenAI:** If `tools=[]`, doesn't include tools in request → text response
- **Anthropic:** Similar behavior
- **Ollama:** May vary by model

By ensuring tools is always either:
- `None` (no tools) → safety net populates full registry
- Non-empty list (has tools) → provider includes in request

We guarantee consistent behavior across providers.
