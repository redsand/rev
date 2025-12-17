# Complete Fix Summary: Stale State & Task Re-evaluation

## The Problem You Reported

> "i see that it created 60+ tasks and did not continue to review if there were more items to be done before removing the original file it was replacing."

### What Was Happening

1. **Upfront Planning**: System generated 60+ tasks all at once
2. **Batch Execution**: Executed them all without pausing
3. **No Mid-Execution Evaluation**:
   - Task 1: Extract BreakoutAnalyst ✓
   - Task 2: Extract CandlestickAnalyst ✓
   - ...
   - Task 60: **DELETE original lib/analysts.py** ← Destructive!
4. **Only After All Tasks**: Check if goal achieved
   - Response: "Still need to extract classes" (too late, they're gone!)
5. **Loop Back**: Regenerate same plan → execute same tasks again

---

## Root Causes (4 Issues)

### 1. **File Cache Not Invalidated After Writes** ❌
- When `write_file()` completed, cache wasn't cleared
- Subsequent `read_file()` returned stale content
- System thought files didn't exist

### 2. **Repo Context Frozen at Start** ❌
- Captured once at orchestrator start
- Never updated after task phases
- Planner always saw original file state
- Didn't know about newly created files

### 3. **Analysis Caches Never Cleared** ❌
- LLM response cache returned same analysis
- AST cache showed outdated file structure
- Dependency cache became invalid

### 4. **Batch Execution Without Per-Task Evaluation** ❌ (MOST CRITICAL)
- Tasks executed in loops with no pauses
- No check after each task
- No way to detect "this task invalidates remaining tasks"
- System only evaluated after entire batch completed

---

## Complete Fix (4 Solutions)

### FIX 1: File Cache Invalidation on Writes

**Files**: `rev/cache/implementations.py`, `rev/tools/file_ops.py`

**What**: When files are written, invalidate their cache entries

**Where**: 5 file operations
- `write_file()` - invalidate cache after write
- `delete_file()` - invalidate cache after delete
- `move_file()` - invalidate cache for source and destination
- `append_to_file()` - invalidate cache after append
- `replace_in_file()` - invalidate cache after replacement

**Effect**: Next `read_file()` call gets fresh content from disk

---

### FIX 2: Update Repo Context After Task Execution

**File**: `rev/execution/orchestrator.py`

**What**: Call `update_repo_context()` explicitly after tasks complete

**Where**:
- Line 793: After task batch executes
- Line 862: After verification task completes

**Effect**: Planner knows about new files created during execution

---

### FIX 3: Clear Analysis Caches Between Iterations

**Files**: `rev/cache/__init__.py`, `rev/execution/orchestrator.py`

**What**: Created `clear_analysis_caches()` function that clears:
- LLM response cache (same prompt may have different answer)
- AST analysis cache (file structure changed)
- Dependency tree cache (files changed)

**Where**: Line 797 in orchestrator, after task execution

**Effect**: Next planning iteration gets fresh analysis

---

### FIX 4: Per-Task Reevaluation (THE KEY FIX) ⭐

**File**: `rev/execution/orchestrator.py`

**What**: After each task completes, check if execution should pause

**How**:
1. New method `_should_pause_for_task_reevaluation()` (lines 617-668)
   - Checks if task was destructive
   - Checks if pending tasks reference modified files
   - Returns True if replan needed

2. Integrated into task loop (lines 576-589)
   - After task completes, call reevaluation method
   - If True, add replan request and stop batch
   - Return early to orchestrator

3. Orchestrator handles replan signal (lines 799-839)
   - Detects replan request
   - Regenerates plan with fresh file state
   - Continues with updated tasks

**Effect**: Pauses execution after destructive operations to check if remaining tasks are still valid

---

## Execution Flow Transformation

### BEFORE: Batch Execution (Stuck in Loop)
```
Phase 1: Generate 60+ tasks
Phase 2: Execute all 60 tasks in batch
  ├─ No pauses
  ├─ No evaluation mid-execution
  └─ Destructive operations proceed unchecked

Phase 3: Check goal (after all tasks)
  └─ Response: "Still need to do task X" (but X is already done/impossible)

Phase 4: Regenerate same plan
  └─ LOOP BACK to Phase 2
```

### AFTER: Per-Task Reevaluation (Adaptive)
```
Phase 1: Generate tasks
Phase 2: Execute with per-task evaluation
  ├─ Execute Task 1
  ├─ After Task 1: Check file state
  │  ├─ File modified? Yes
  │  ├─ Pending tasks affected? Yes
  │  └─ ACTION: Pause and replan
  │
  ├─ Phase 3: Regenerate plan (with fresh state)
  │  └─ Old plan: [Task 2, Task 3, ..., DELETE original]
  │  └─ New plan: [Task 2, Task 3, ...] (modified based on new state)
  │
  └─ Continue Phase 2 with new tasks

Phase 4: (Only when goal achieved)
  └─ Completion confirmed
```

---

## The 4-Part Solution

```
┌─────────────────────────────────────────────────────────────┐
│ SOLUTION 1: Cache Invalidation                              │
│ ├─ File writes invalidate file cache                        │
│ └─ Fresh reads guaranteed after writes                      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ SOLUTION 2: Repo Context Updates                            │
│ ├─ Updated after task execution                             │
│ └─ Planner knows about file changes                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ SOLUTION 3: Analysis Cache Clearing                         │
│ ├─ Clear LLM, AST, dependency caches                        │
│ └─ Fresh analysis for next iteration                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ SOLUTION 4: Per-Task Reevaluation ⭐ CRITICAL              │
│ ├─ Check after each task if plan needs update              │
│ ├─ Detect destructive operations affecting pending tasks   │
│ └─ Pause, replan, continue (not loop)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## What Changed

### File: `rev/execution/orchestrator.py`

**New method** (lines 617-668):
```python
def _should_pause_for_task_reevaluation(self, completed_task: Task, context: RevContext) -> bool:
    """Check if task changes invalidate pending tasks."""
    # Returns True if replan needed
```

**In task loop** (lines 576-589):
```python
if self._should_pause_for_task_reevaluation(task, context):
    # Add replan request and stop batch
    context.agent_requests.append({
        "type": "replan_immediately",
        "reason": f"File state changed after task {task.task_id}"
    })
    return overall_success  # Exit early
```

**In main loop** (lines 799-839):
```python
# Check for replan requests from tasks
if should_replan_immediately or self._check_for_immediate_replan_after_destructive_task(...):
    # Regenerate plan with fresh file state
    followup_plan = self._regenerate_followup_plan(...)
```

### File: `rev/cache/__init__.py`

**New function** (lines 99-116):
```python
def clear_analysis_caches():
    """Clear LLM, AST, dependency caches."""
    _LLM_CACHE.clear()
    _AST_CACHE.clear()
    _DEP_CACHE.clear()
```

### File: `rev/cache/implementations.py`

**New method** (lines 53-59):
```python
def invalidate_file(self, file_path: pathlib.Path):
    """Invalidate all cache entries for a file."""
```

### File: `rev/tools/file_ops.py`

**Cache invalidation calls** in:
- `write_file()` (lines 260-263)
- `delete_file()` (lines 335-338)
- `move_file()` (lines 355-359)
- `append_to_file()` (lines 377-380)
- `replace_in_file()` (lines 409-412)

---

## Expected Behavior After Fixes

### Scenario: Split 10 Analyst Classes into 10 Files

**OLD BEHAVIOR** (before fixes):
```
Iteration 1:
  ├─ Plan: [Extract class 1, Extract class 2, ..., DELETE lib/analysts.py]
  ├─ Execute: All 60 tasks without pause
  └─ Result: Original file deleted, unable to extract remaining classes

Iteration 2:
  └─ Same plan regenerated (LOOP)
```

**NEW BEHAVIOR** (after fixes):
```
Iteration 1:
  ├─ Plan: [Extract class 1, Extract class 2, ...]
  ├─ Execute with evaluation:
  │   ├─ Extract class 1 ✓
  │   ├─ PAUSE: Check if file changed & affects pending tasks
  │   ├─ Detect: Yes, remaining extracts need original file
  │   └─ ACTION: Replan
  │
  ├─ Replanning (fresh file state):
  │   └─ New plan: [Extract classes 2-10, then delete, then update imports]
  │
  └─ Continue with new plan

Iterations 2-N:
  ├─ Extract class 2, Evaluate, Continue
  ├─ Extract class 3, Evaluate, Continue
  ├─ ... (Each task properly sequenced)
  │
  └─ Final: Delete original file only when ALL extracts complete ✓

Result: Completion in N iterations with proper sequencing
(NOT stuck in loop regenerating same plan)
```

---

## Verification Checklist

- [x] File cache invalidation added to 5 write operations
- [x] Repo context updated after task execution
- [x] Analysis caches cleared between iterations
- [x] Per-task reevaluation implemented
- [x] Replan signal propagated to orchestrator
- [x] Agent requests cleared after handling
- [x] Code compiles without errors
- [x] Backward compatible with existing code

---

## Files Modified Summary

| File | Change | Lines |
|------|--------|-------|
| `rev/cache/implementations.py` | Add `invalidate_file()` | 53-59 |
| `rev/cache/__init__.py` | Add `clear_analysis_caches()` | 99-116 |
| `rev/cache/__init__.py` | Export new function | 26 |
| `rev/tools/file_ops.py` | Cache invalidation × 5 | Various |
| `rev/execution/orchestrator.py` | Add `_should_pause_for_task_reevaluation()` | 617-668 |
| `rev/execution/orchestrator.py` | Per-task evaluation in dispatch | 576-589 |
| `rev/execution/orchestrator.py` | Handle replan signals in main loop | 799-839 |

**Total changes**: ~150 lines across 5 files

---

## Impact on Problem Symptoms

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| "Created 60+ tasks" | Upfront planning | No change needed (acceptable) |
| "Did not review" | Batch execution | ✅ Per-task evaluation |
| "Did not check before deleting" | No mid-execution pause | ✅ Per-task reevaluation |
| "Destructive operations before dependent tasks" | No replan signal | ✅ Replan request mechanism |
| "Same plan regenerated repeatedly" | Stale file/analysis state | ✅ Cache clearing & repo context updates |
| "No progress between iterations" | Undetected completed work | ✅ Fresh file reads + evaluation |

---

## Next Steps

1. **Test the fixes** with the analyst splitting task
   - Should see "Pausing for plan re-evaluation" messages
   - Should see different follow-up plans (not same 60+)
   - Should complete without destructive issues

2. **Monitor execution logs**
   - Watch for per-task reevaluation messages
   - Verify replan happens at right times
   - Confirm destructive ops are properly sequenced

3. **Verify completion**
   - Task should complete in reasonable iterations
   - No regeneration of same plan repeatedly
   - Proper incremental progress toward goal

---

## Summary

The complete fix addresses the stale state problem through **4 complementary solutions**:

1. ✅ **Fresh File Reads**: Cache invalidation on writes
2. ✅ **Fresh State Knowledge**: Repo context updates
3. ✅ **Fresh Analysis**: Cache clearing between iterations
4. ✅ **Adaptive Execution**: Per-task reevaluation with replanning

Together, these ensure the system **evaluates after each task** and **adapts the plan** based on actual file state changes, preventing the loop of repeating 60+ tasks and allowing proper incremental progress toward completion.
