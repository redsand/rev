# Sub-Agent System Fixes

## Issues Fixed

### 1. ✅ Infinite Replan Loop
**Problem:** Sub-agents were requesting replans when LLM didn't return tool calls, causing infinite loops

**Solution:** Agents now fail gracefully without requesting replans
- Added debug output to show exactly what LLM returns
- Tasks marked as failed instead of triggering replan
- Prevents cascading replan requests

### 2. ✅ Invalid `current_plan` Parameter
**Problem:** `planning_mode()` was being called with non-existent `current_plan` parameter

**Solution:** Removed the invalid parameter from `_regenerate_followup_plan()`
```python
# Before (broken)
followup_plan = planning_mode(prompt, current_plan=original_plan, ...)

# After (fixed)
followup_plan = planning_mode(prompt, coding_mode=coding_mode, ...)
```

## Current Behavior

### When LLM Doesn't Return Tool Calls

Agents now provide detailed diagnostics:

```
  ⚠️ CodeWriterAgent: LLM returned text instead of tool call
  → Content: [first 200 chars of what LLM actually said]
  → Task will be marked as failed without requesting replan
```

Possible outputs:
- `LLM returned empty response` - No response from LLM
- `LLM response missing 'message' key` - Malformed response structure
- `LLM response missing 'tool_calls'` - LLM returned text instead of tool call
- `LLM tool_calls array is empty` - tool_calls exists but is []
- `LLM returned invalid JSON for arguments` - Tool call arguments can't be parsed

### What This Means

**Tasks will now fail clearly** instead of looping forever. You'll see:
1. Which agent failed (CodeWriterAgent, AnalysisAgent, etc.)
2. What the LLM actually returned
3. Why it couldn't be processed
4. Task marked as FAILED (not stuck in replan loop)

## Why Tool Calls Might Fail

The sub-agents rely on the LLM generating valid tool calls in JSON format. Tool calls can fail if:

1. **Model doesn't support tool calling well**
   - Some models aren't trained for function calling
   - Smaller models may struggle with tool call format

2. **System prompt confusion**
   - Agent prompts are very strict about JSON-only responses
   - Model might ignore the format requirements

3. **Tool schema complexity**
   - Too many tools or complex parameters
   - Model can't understand what tool to use

4. **Repository context too large**
   - Context window exceeded
   - Model gets confused by too much info

## Recommendations

### Option 1: Use Linear Mode (Recommended for Now)
```bash
# Traditional execution - more reliable
rev --execution-mode linear "your task"

# Or omit the flag (linear is default)
rev "your task"
```

Linear mode uses the battle-tested execution engine that doesn't rely on agent-specific tool calling.

### Option 2: Test with Simple Tasks
Try simple tasks to see if tool calling works:

```bash
rev --execution-mode sub-agent "create a file hello.py with print('hello')"
```

If you see tool call failures, the model may not support this pattern well.

### Option 3: Try Different Models
Some models handle tool calling better than others:

```bash
# Try a different model
rev --execution-mode sub-agent --model qwen3-coder:480b-cloud "your task"
```

### Option 4: Check Debug Output
The new debug output will show exactly what the LLM returns:

```
  ℹ️ CodeWriterAgent: LLM returned text instead of tool call
  → Content: I'll help you create that file. First, let me...
  → Task will be marked as failed without requesting replan
```

This tells you the model is explaining instead of calling tools.

## Expected Behavior Now

### Good Case (Tool Call Works):
```
🤖 Dispatching task 0 (add): Create hello.py
  → CodeWriterAgent will call tool 'write_file' with arguments: {'file_path': 'hello.py', ...}
  ✓ Task 0 completed successfully

📊 Sub-agent execution summary: 1/1 completed, 0 failed
```

### Failure Case (Tool Call Doesn't Work):
```
🤖 Dispatching task 0 (add): Create hello.py
  ⚠️ CodeWriterAgent: LLM returned text instead of tool call
  → Content: I understand you want me to create a file. Let me help...
  → Task will be marked as failed without requesting replan

📊 Sub-agent execution summary: 0/1 completed, 1 failed
```

**No more infinite loops!** The task fails cleanly and you can see why.

## Testing

To test if your model supports tool calling:

```bash
# Simple test
rev --execution-mode sub-agent "add a comment to any .py file"
```

Watch for:
- ✓ Tool calls being made successfully
- ⚠️ Debug messages showing what went wrong
- 📊 Summary showing completion status

## Summary

The sub-agent system now:
- ✅ Provides clear error messages
- ✅ Shows exactly what LLM returned
- ✅ Fails gracefully without infinite loops
- ✅ Works better with models that support tool calling
- ✅ Falls back to linear mode if needed

**If tool calling doesn't work well with your model, linear mode is the way to go!**
