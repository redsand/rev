# LLM Tool Calling Failure - Diagnostic Report

## Issue Summary

LLM tool calling was failing with the error: **"Write action completed without tool execution"**

The logs showed:
```json
{
  "supports_tools": false,
  "tools_provided": false,
  "tools_count": 0,
  "tools_names": []
}
```

This indicates that the LLM was being called with **zero tools**, even though the CodeWriterAgent should have been providing tools for edit/write operations.

## Root Cause Analysis

### Tool Provisioning Pipeline

The tool provisioning pipeline has several stages:

1. **CodeWriterAgent.execute()** (rev/agents/code_writer.py:924)
   - Determines which tools are appropriate for the action_type
   - For `action_type="edit"`: provides `['apply_patch', 'replace_in_file', 'write_file', 'copy_file', 'move_file']`

2. **build_context_and_tools()** (rev/agents/context_provider.py:136)
   - Calls ContextBuilder to retrieve relevant tools based on semantic similarity to the query
   - Filters retrieved tools to only those in candidate_tool_names
   - Has a fallback mechanism if filtering removes all tools

3. **ContextBuilder.build_minimal() / build()** (rev/retrieval/context_builder.py)
   - Uses ToolsCorpus.query() to find tools based on keyword/semantic matching
   - Returns tools ranked by relevance score

4. **ollama_chat()** (rev/llm/client.py:569)
   - Receives tools from CodeWriterAgent
   - Sets `supports_tools = True` if tools are provided
   - Has a safety net to auto-populate tools if none provided

### Where Tools Were Being Lost

The issue was that the **ToolsCorpus.query()** method (rev/retrieval/context_builder.py:593) uses a scoring system based on keyword matching. If the query/task description doesn't contain keywords that match the tool names or descriptions, tools get a score of 0 and are filtered out:

```python
if score <= 0:
    continue  # Tool is excluded!
```

For tasks like "overwrite `./package.json` completely with...", the query might not contain keywords like "edit", "replace", "apply", "patch", etc., resulting in **all tools getting filtered out**.

### Safety Nets

There were two safety nets that should have prevented this:

1. **context_provider.py lines 192-199**: Fallback to tool_universe if filtering removes all tools
2. **code_writer.py lines 1023-1039**: Fallback to all candidate tools if context builder returns empty

However, these safety nets were not logging enough information to diagnose when they were failing to activate.

## Solution Implemented

### Comprehensive Diagnostic Logging

Added detailed logging at each stage of the tool provisioning pipeline:

#### 1. CodeWriterAgent (rev/agents/code_writer.py)

```python
# Log initial tool selection
print(f"  [TOOL_PROVISION] action_type={task.action_type}, tool_names={tool_names}")
print(f"  [TOOL_PROVISION] Initial available_tools count: {len(available_tools)}, names: {[...]}")

# Log what context builder returned
print(f"  [TOOL_PROVISION] Context builder returned {len(selected_tools)} tools: {[...]}")

# Log filtering results
print(f"  [TOOL_PROVISION] After filtering to allowed names: {before_filter} -> {len(available_tools)}")

# Log safety net activation
if not available_tools:
    print(f"  [TOOL_PROVISION] CRITICAL: No tools after filtering! Activating safety net...")

# Log final state before LLM call
print(f"  [TOOL_PROVISION] FINAL: Sending {len(available_tools)} tools to LLM: {[...]}")
print(f"  [TOOL_PROVISION] Calling ollama_chat with {len(available_tools)} tools, tool_choice={tool_choice_mode}")
```

#### 2. Context Provider (rev/agents/context_provider.py)

```python
# Log retrieval results
print(f"  [CONTEXT_PROVIDER] Retrieved {len(selected_tool_schemas)} tools from retrieval: {[...]}")
print(f"  [CONTEXT_PROVIDER] Candidate tool names: {candidate_tool_names}")

# Log filtering
print(f"  [CONTEXT_PROVIDER] After filtering to candidates: {before_count} -> {len(selected_tool_schemas)}")

# Log fallback activation
if not selected_tool_schemas and candidate_tool_names:
    print(f"  [CONTEXT_PROVIDER] Filtering removed all tools! Activating fallback to tool_universe")
    print(f"  [CONTEXT_PROVIDER] Fallback populated {len(selected_tool_schemas)} tools: {[...]}")
```

#### 3. LLM Client (rev/llm/client.py)

```python
# Log tool counts before/after auto-population
tools_count_before = len(tools) if tools else 0
# ... (auto-population logic)
tools_count_after = len(tools) if tools else 0

if tools_count_after == 0:
    print(f"  [LLM_CLIENT] WARNING: Calling LLM with 0 tools! supports_tools_before={supports_tools_before}, supports_tools_after={supports_tools}, ...")
elif tools_count_before != tools_count_after:
    print(f"  [LLM_CLIENT] Tools auto-populated: {tools_count_before} -> {tools_count_after}")
```

## How to Use the Diagnostics

### Running a Test

When you run your next task, you'll see detailed logging like:

```
CodeWriterAgent executing task: overwrite `./package.json` ...
  [TOOL_PROVISION] action_type=edit, tool_names=['apply_patch', 'replace_in_file', 'write_file', 'copy_file', 'move_file']
  [TOOL_PROVISION] Initial available_tools count: 5, names: ['apply_patch', 'replace_in_file', 'write_file', 'copy_file', 'move_file']
  [CONTEXT_PROVIDER] Retrieved 3 tools from retrieval: ['apply_patch', 'replace_in_file', 'write_file']
  [CONTEXT_PROVIDER] Candidate tool names: ['apply_patch', 'replace_in_file', 'write_file', 'copy_file', 'move_file']
  [CONTEXT_PROVIDER] After filtering to candidates: 3 -> 3
  [TOOL_PROVISION] Context builder returned 3 tools: ['apply_patch', 'replace_in_file', 'write_file']
  [TOOL_PROVISION] After filtering to allowed names: 3 -> 3
  [TOOL_PROVISION] FINAL: Sending 3 tools to LLM: ['apply_patch', 'replace_in_file', 'write_file']
  [TOOL_PROVISION] Calling ollama_chat with 3 tools, tool_choice=required
```

### If Tools Are Still Being Lost

If you see:
```
  [TOOL_PROVISION] CRITICAL: No tools after filtering! Activating safety net...
```

This indicates the safety net is being triggered. Check:
1. What tools the context builder returned
2. Whether the filtering step removed all tools
3. Whether the fallback successfully populated tools

If you see:
```
  [LLM_CLIENT] WARNING: Calling LLM with 0 tools!
```

This is a **critical error** - the LLM is being called without tools. Check the previous logs to see where tools were lost.

### If Tool Calling Still Fails

If the LLM receives tools but still doesn't call them, check:
```
  [TOOL_PROVISION] LLM response keys: ['message', 'done', 'usage']
  [TOOL_PROVISION] Message keys: ['role', 'content']  # Missing 'tool_calls'!
```

This indicates the LLM returned text instead of tool calls. Possible causes:
1. Model doesn't support tool calling (check `supports_tools` flag)
2. Model ignoring `tool_choice="required"` parameter
3. Provider not correctly passing through tool parameters

## Next Steps

1. **Run a test task** to see the diagnostic logging in action
2. **Check the log files** in `../test-app/.rev/logs/` for:
   - `rev_run_*.log` - Contains the [TOOL_PROVISION] and [CONTEXT_PROVIDER] logs
   - `llm_transactions.log` - Contains the LLM request/response details with tools_count
3. **Report back** with the diagnostic output so we can identify the exact failure point

## Files Modified

1. `rev/agents/code_writer.py` - Added comprehensive tool provisioning logging
2. `rev/agents/context_provider.py` - Added context builder tool selection logging
3. `rev/llm/client.py` - Added LLM client tool parameter logging

## Rollback

If the logging is too verbose, you can disable it by commenting out the print statements with the prefixes:
- `[TOOL_PROVISION]`
- `[CONTEXT_PROVIDER]`
- `[LLM_CLIENT]`
