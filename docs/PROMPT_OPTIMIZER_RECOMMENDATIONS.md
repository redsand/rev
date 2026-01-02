# Prompt Optimizer Recommendations - Based on Your Execution Log

## Executive Summary

You identified a critical architectural gap: **The prompt optimizer should automatically improve agent prompts when they fail, not require manual user intervention.**

Your execution log shows exactly this problem:
1. RefactoringAgent only calls `read_file` (never `write_file`)
2. Verification correctly detects this failure: "No files created"
3. System retries with the **exact same failing prompt**
4. Results in infinite loop of DEBUG/INVESTIGATE/REFACTOR with no progress

**Solution**: Implement runtime adaptive prompt optimization (in progress).

## What's Been Done

### ✓ New Adaptive Prompt Optimizer Module
**File**: `rev/execution/adaptive_prompt_optimizer.py`

Provides:
- `analyze_tool_call_pattern()` - Detects failure patterns ("only reads, no writes")
- `get_agent_prompt_improvement()` - Asks LLM to improve the system prompt
- `should_attempt_prompt_improvement()` - Decides if improvement is worthwhile
- `AdaptivePromptOptimizer` class - Manages improvement history and retries

### ✓ RefactoringAgent Enhancement
**File**: `rev/agents/refactoring.py` (modified)

Changes:
- Added support for `_override_system_prompt` on task
- Accepts system_prompt parameter in `_execute_simple_refactoring_task()`
- Falls back to default if none provided
- Logs when improved prompt is used

## What Still Needs to Be Done

### 1. **Integrate Optimization into Orchestrator** (Critical)
**File**: `rev/execution/orchestrator.py` → `_continuous_sub_agent_execution()`

**Current Code Flow (line 468-484):**
```python
if not verification_result.passed:
    # Just mark as failed and try decomposition
    next_task.status = TaskStatus.FAILED
    decomposed_task = self._decompose_extraction_task(next_task)
    if decomposed_task:
        next_task = decomposed_task
        iteration -= 1
```

**Needs to Be:**
```python
if not verification_result.passed:
    # First, try to improve the agent's prompt
    if should_attempt_adaptive_improvement(next_task):
        improved, new_prompt = improve_prompt_for_retry(
            agent_type=next_task.action_type,
            task=next_task,
            verification_failure=verification_result.message,
            tool_calls=captured_tool_calls,  # ← Need to capture these
            original_prompt=get_agent_system_prompt(next_task.action_type),
            retry_attempt=getattr(next_task, '_retry_count', 0) + 1
        )

        if improved:
            # Attach improved prompt and retry
            next_task._override_system_prompt = new_prompt
            next_task._retry_count = getattr(next_task, '_retry_count', 0) + 1

            print(f"  [ADAPTIVE] Improved {next_task.action_type} prompt (attempt {next_task._retry_count})")
            print(f"    Issue detected: {failure_pattern}")
            print(f"    Retrying with improved instructions...")

            iteration -= 1  # Don't count as new iteration
            continue  # Retry same task with improved prompt

    # If adaptive improvement didn't work, try decomposition
    next_task.status = TaskStatus.FAILED
    decomposed_task = self._decompose_extraction_task(next_task)
    if decomposed_task:
        next_task = decomposed_task
        iteration -= 1
```

### 2. **Capture Tool Calls from Agent Execution** (Critical)

**Current Issue**: We don't know what tools the agent actually called

**Solution**: Store tool calls when agent executes

```python
# In _dispatch_to_sub_agents():
agent = AgentRegistry.get_agent_instance(task.action_type)
result = agent.execute(task, context)

# Capture tool calls
if hasattr(agent, 'get_last_tool_calls'):
    task._tool_calls = agent.get_last_tool_calls()
elif hasattr(context, 'last_tool_calls'):
    task._tool_calls = context.last_tool_calls
```

### 3. **Add Helper Functions to Orchestrator**

```python
def should_attempt_adaptive_improvement(task: Task) -> bool:
    """Should we try adaptive prompt improvement?"""
    # Don't retry more than 3 times
    if getattr(task, '_retry_count', 0) >= 3:
        return False

    # Only for structural tasks (extract, refactor, create)
    structural_types = ["refactor", "create", "edit", "add"]
    return task.action_type.lower() in structural_types

def get_agent_system_prompt(action_type: str) -> str:
    """Get the current system prompt for an agent type"""
    if action_type == "refactor":
        from rev.agents.refactoring import REFACTORING_SYSTEM_PROMPT
        return REFACTORING_SYSTEM_PROMPT
    # Add other agent types as needed
    return ""
```

### 4. **Import the Adaptive Optimizer** (Simple)

At top of orchestrator.py:
```python
from rev.execution.adaptive_prompt_optimizer import (
    improve_prompt_for_retry,
    analyze_tool_call_pattern
)
```

## Integration Effort Estimate

| Task | Effort | Impact |
|------|--------|--------|
| Import adaptive optimizer | 5 min | Critical |
| Add tool call capture | 30 min | Critical |
| Update verification failure handler | 30 min | Critical |
| Add helper functions | 20 min | Important |
| Test and debug | 1-2 hours | Critical |
| **Total** | **2-3 hours** | **Solves the infinite loop** |

## Expected Behavior After Integration

### Before (Current - Broken)
```
RefactoringAgent tries extraction
  ↓ Only calls read_file
  ↓
Verification: FAIL - "No files created"
  ↓
Decompose to [CREATE]
  ↓
CodeWriterAgent tries (but also just reads)
  ↓
LOOP: DEBUG → INVESTIGATE → DEBUG → INVESTIGATE → ...
```

### After (Fixed)
```
RefactoringAgent tries extraction
  ↓ Only calls read_file
  ↓
Verification: FAIL - "No files created"
  ↓
[NEW] Analyze: "Agent only called read_file, never write_file"
  ↓
[NEW] Improve prompt: Make write_file requirement explicit
  ↓
Retry RefactoringAgent with improved prompt
  ↓ Calls write_file correctly
  ↓
Verification: PASS - "3 files created"
  ↓
Status: COMPLETED
```

## How This Solves Your Problem

Your log shows:
```
→ RefactoringAgent will call tool 'read_file'
→ Verifying execution...
[FAIL] No Python files in 'lib\analysts' - extraction created directory but extracted NO FILES

[DECOMPOSITION] LLM suggested decomposition:
  Action: create

→ DebuggingAgent will call tool 'read_file'
→ Verifying execution...
[OK] No specific verification available for action type 'debug'
→ ResearchAgent will call tool 'read_file'
```

**With adaptive optimization:**
```
→ RefactoringAgent will call tool 'read_file'
→ Verifying execution...
[FAIL] No Python files - extraction did not call write_file

[ADAPTIVE] Improved refactoring prompt
  Issue: "Agent reads files but never writes"
  Retrying with improved instructions...

→ RefactoringAgent will call tool 'read_file' → 'write_file' → 'write_file' → 'write_file'
→ Verifying execution...
[OK] 3 files created with valid imports

→ [COMPLETED] move individual analyst classes...
```

## Code Quality Checklist

- ✓ Adaptive optimizer module created
- ✓ RefactoringAgent updated
- ✓ Documentation provided
- ⏳ Orchestrator integration (needs to be done)
- ⏳ Testing (needs to be done)
- ⏳ Tool call capture (needs to be done)

## Files to Modify

1. `rev/execution/orchestrator.py` - Main integration (2-3 hours)
2. `rev/agents/refactoring.py` - Already done ✓
3. `rev/execution/adaptive_prompt_optimizer.py` - Already created ✓

## Next Steps

To complete the implementation:

1. Add import statement to orchestrator
2. Modify `_continuous_sub_agent_execution()` to use adaptive optimization before decomposition
3. Add tool call capture mechanism
4. Test with extraction task
5. Verify the infinite loop is broken

## Success Criteria

After implementation, running your original request should:

✓ RefactoringAgent attempts extraction
✓ Verification detects failure (no files)
✓ Prompt is automatically improved
✓ RefactoringAgent retries with better prompt
✓ Task completes successfully

No more infinite loops of DEBUG/INVESTIGATE/REFACTOR with no progress.

## Why This Matters

The core principle: **Systems should self-improve, not degrade gracefully.**

Instead of:
- "Oh, extraction failed, let me try debugging" (doesn't fix root cause)
- "Let me investigate" (just reads more)
- "Let me decompose" (routes to different agent with same problem)

We should:
- "Extraction failed because agent didn't use write_file"
- "Let me improve the agent's instructions to be explicit"
- "Retry with better prompt"

This is the difference between a brittle system that fails gracefully vs. an intelligent system that self-heals.

## Questions?

The implementation is straightforward because:
1. The adaptive optimizer module is ready
2. The RefactoringAgent accepts override prompts
3. The orchestrator just needs to wire them together

All the pieces are in place; it's just connecting them in the orchestrator.
