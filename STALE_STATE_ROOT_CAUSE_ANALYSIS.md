# Root Cause Analysis: Stale State & Repeating Plans

## Problem Statement

System was generating 60+ tasks upfront and not making progress:
- Same tasks regenerated repeatedly in follow-up iterations
- File changes not detected between task phases
- System continued attempting tasks already in the plan
- Destructive operations (splitting classes) would be executed, then planned again
- No adaptation to actual file state changes

---

## Root Causes Identified

### 1. **File Cache Not Invalidated on Writes** ❌

**Issue**: When write_file(), replace_in_file(), etc. completed, the file cache was never cleared.

**Flow**:
```
1. LLM calls write_file("lib/analysts/breakout_analyst.py", content)
2. File written to disk successfully ✓
3. Cache NOT invalidated ❌
4. Next read_file("lib/analysts/breakout_analyst.py") returns CACHED VERSION ❌
5. Planner thinks file doesn't exist or has old content
```

**Files Affected**:
- `rev/tools/file_ops.py` - write_file, replace_in_file, append_to_file, delete_file, move_file
- Had NO cache invalidation calls

**Impact**: HIGH - Caused immediate visibility issues in next task

---

### 2. **Repo Context Captured Once, Never Updated** ❌

**Issue**: Repository context was captured at orchestrator start and reused for entire execution.

**Flow**:
```
Orchestrator starts:
  ├─ repo_context = get_repo_context()  ← Captures file list ONCE
  └─ self.context.repo_context = repo_context

Task Iteration 1:
  ├─ Execute: Write 5 new files
  └─ repo_context UNCHANGED (still from start)

Planning Iteration 1:
  ├─ Read planning prompts with OLD repo_context
  └─ LLM doesn't know about new files

Task Iteration 2:
  ├─ Execute: Write same 5 files AGAIN
  └─ repo_context UNCHANGED (still from start)
```

**Location**: `rev/execution/orchestrator.py` line 719
- Only one call to `self.context.update_repo_context()`
- Executed once at orchestrator start
- No updates after task phases complete

**Impact**: CRITICAL - Planner used stale file list, couldn't see completed work

---

### 3. **LLM Response Cache Never Cleared** ❌

**Issue**: LLM response cache was keyed by message hash, not file state.

**Flow**:
```
Iteration 1:
  ├─ Planning prompt: "What files need to be created?"
  ├─ LLM response: ["breakout_analyst.py", "candlestick_analyst.py", ...]
  └─ Response CACHED with hash of prompt

Iteration 2:
  ├─ Planning prompt: SAME prompt (identical message)
  ├─ Cache lookup: SAME hash → SAME cached response
  └─ LLM returns SAME file list (doesn't know some already created) ❌
```

**TTL**: 3600 seconds (1 hour)

**Location**: `rev/cache/implementations.py` - LLMResponseCache
- Cached by message hash only
- No consideration of file state or repo context

**Impact**: HIGH - Planner gets stale LLM analysis

---

### 4. **AST & Dependency Analysis Cached Without Invalidation** ❌

**Issue**: File analysis caches became stale when files changed.

**Flow**:
```
Iteration 1:
  ├─ Analyze lib/analysts.py
  ├─ Cache: ast_cache["lib/analysts.py:{mtime}"] = AST
  └─ Cached for 10 minutes

File Write:
  ├─ File modified but mtime may not update instantly
  └─ AST cache not invalidated

Iteration 2:
  ├─ Analyze lib/analysts.py (which now has different classes)
  └─ Cache lookup finds old AST (mtime hasn't changed yet)
```

**Caches affected**:
- ASTAnalysisCache (600-second TTL)
- DependencyTreeCache (600-second TTL)

**Impact**: MEDIUM - Wrong analysis of file structure

---

### 5. **Large Upfront Planning Without Iterative Refinement** ❌

**Issue**: System generated all 60+ tasks at once, then executed them linearly.

**Expected behavior**: Generate tasks → Execute → Adapt → Generate more → Execute

**Actual behavior**: Generate 60+ → Execute all → Regenerate same 60+ → Execute all again

**Root cause**: Combination of all above issues preventing system from detecting progress

---

## Why This Causes Repeating Plans

```
Initial Request: "Split 10 analyst classes into individual files"

Iteration 1:
  Step A: Plan generation
    ├─ Reads repo_context (empty dir, no analysts files yet)
    ├─ Generates: "Create 10 files + Update imports + Run tests + ..."
    └─ Creates 60+ tasks

  Step B: Task execution
    ├─ Execute tasks 1-30 (create files)
    ├─ Files written to disk
    ├─ File cache NOT invalidated
    ├─ Repo context NOT updated
    └─ Analysis caches NOT cleared

  Step C: Check if goal achieved
    ├─ Query: "Have we completed the request?"
    ├─ Uses STALE repo_context (still shows no analysts files)
    ├─ Uses CACHED LLM analysis (doesn't know files created)
    └─ Response: "No, need to create the analyst files"

Iteration 2:
  Step A: Plan regeneration
    ├─ Reads STALE repo_context
    ├─ Sees NO analyst files (they're hidden by stale cache)
    ├─ Generates: "Create 10 files + Update imports + Run tests + ..." ← SAME PLAN
    └─ Creates 60+ tasks AGAIN

  Step B: Task execution
    ├─ Execute SAME tasks again
    ├─ Partial overwrites of already-created files
    ├─ More stale caches
    └─ More confusion
```

---

## The Fixes

### Fix 1: Invalidate File Cache After Writes

**What**: Added `file_cache.invalidate_file(path)` after all write operations

**Where**: 5 functions in `rev/tools/file_ops.py`

**Effect**: Next read_file() gets fresh content

### Fix 2: Update Repo Context After Tasks

**What**: Call `self.context.update_repo_context()` after task execution

**Where**: `rev/execution/orchestrator.py` lines 724 and 862

**Effect**: Next planning iteration knows about new files

### Fix 3: Clear Analysis Caches Between Iterations

**What**: Added `clear_analysis_caches()` function that clears:
- LLM response cache
- AST analysis cache
- Dependency tree cache

**Where**: `rev/execution/orchestrator.py` line 728

**Effect**: Next planning iteration gets fresh analysis

---

## Verification

### Before Fixes
```
Write file A → File cache has A
Read file A → Gets cached A (correct)

Execute tasks → Write file B
Read file B → STALE OR NOT FOUND (cache not invalidated)

Plan iteration 1 → Sees repo state at T0 (start)
Plan iteration 2 → Still sees repo state at T0 (never updated)
```

### After Fixes
```
Write file A → Invalidate cache for A
Read file A → Gets fresh A from disk

Execute tasks → Write file B
Invalidate cache for B
Read file B → Gets fresh B from disk

Plan iteration 1 → repo_context updated after tasks
Plan iteration 2 → repo_context reflects all changes
LLM cache cleared → Fresh analysis each iteration
```

---

## System Flow Diagram

### Before Fixes (Stuck in Loop)
```
┌─────────────────────────────────────┐
│ Planning (with stale data)          │
│ ├─ repo_context from start          │
│ ├─ LLM cache from start             │
│ └─ Generate 60+ tasks               │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Execution                           │
│ ├─ Execute tasks 1-30               │
│ ├─ Write files A, B, C              │
│ └─ Cache NOT invalidated            │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Evaluation (with stale data)        │
│ ├─ repo_context UNCHANGED           │
│ ├─ LLM cache UNCHANGED              │
│ ├─ "Still need to create files..."  │
│ └─ Return False (need more tasks)   │
└────────────┬────────────────────────┘
             │
             ▼ LOOP BACK (repeat steps above)
        [STUCK IN LOOP]
```

### After Fixes (Progressive)
```
┌─────────────────────────────────────┐
│ Planning                            │
│ ├─ repo_context from start          │
│ ├─ Generate 10 tasks                │
│ └─ Mark for execution               │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Execution                           │
│ ├─ Execute tasks 1-10               │
│ ├─ Write files A, B, C              │
│ ├─ Invalidate cache for A, B, C ✓   │
│ └─ Tasks complete                   │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Post-Task Updates                   │
│ ├─ Update repo_context ✓            │
│ ├─ Clear LLM cache ✓                │
│ ├─ Clear AST cache ✓                │
│ └─ Clear dependency cache ✓         │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ Evaluation (with fresh data)        │
│ ├─ repo_context shows A, B, C       │
│ ├─ LLM knows files created          │
│ ├─ "Files created, need imports..." │
│ └─ Return plan for next phase       │
└────────────┬────────────────────────┘
             │
             ▼ LOOP BACK WITH PROGRESS
        [ITERATIVE COMPLETION]
```

---

## Impact on Original Issue

**Original Symptom**: "it created 60+ tasks and did not continue to review if there were more items to be done before removing the original file"

**Root Cause**: All 3 cache issues combined meant system couldn't detect that it had already:
1. Created the split files
2. Updated imports
3. Run tests

**Fix**: Now system detects completion through:
1. Fresh file reads (invalidation on write)
2. Updated repo context (explicit updates)
3. Fresh analysis (cache clearing)

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `rev/cache/implementations.py` | Add `invalidate_file()` method | 53-59 |
| `rev/cache/__init__.py` | Add `clear_analysis_caches()` function | 99-116 |
| `rev/cache/__init__.py` | Export new function | 26 |
| `rev/tools/file_ops.py` | Cache invalidation in write_file | 260-263 |
| `rev/tools/file_ops.py` | Cache invalidation in delete_file | 335-338 |
| `rev/tools/file_ops.py` | Cache invalidation in move_file | 355-359 |
| `rev/tools/file_ops.py` | Cache invalidation in append_to_file | 377-380 |
| `rev/tools/file_ops.py` | Cache invalidation in replace_in_file | 409-412 |
| `rev/execution/orchestrator.py` | Import `clear_analysis_caches` | 50 |
| `rev/execution/orchestrator.py` | Update repo_context after tasks | 724 |
| `rev/execution/orchestrator.py` | Clear analysis caches | 728 |
| `rev/execution/orchestrator.py` | Update repo_context after verification | 862 |

---

## Testing Recommendations

1. **File Cache Invalidation**
   ```
   1. Create a file with write_file()
   2. Verify it exists on disk
   3. Read it back with read_file()
   4. Modify the disk file
   5. Read again → should get modified content
   ```

2. **Repo Context Updates**
   ```
   1. Print repo_context after planning phase
   2. Execute tasks that create 5 files
   3. Print repo_context after execution
   4. Should show 5 additional files
   ```

3. **Analysis Cache Clearing**
   ```
   1. Extract LLM cache stats before task execution
   2. Execute tasks that modify files
   3. Extract LLM cache stats after
   4. Should show cleared cache
   ```

4. **Iterative Progress**
   ```
   Request: "Split 10 classes into 10 files"
   Expected:
   - Iteration 1: Generate ~10 tasks, execute (create files)
   - Iteration 2: Generate ~5 tasks, execute (update imports, fix issues)
   - Iteration 3: Generate ~2 tasks, execute (run tests, cleanup)
   - Iteration 4: Completion confirmed

   NOT:
   - All iterations generating same 60+ tasks
   ```

---

## Summary

The system was stuck in a loop regenerating the same plan because:

1. ❌ File cache persisted after writes (couldn't see new files)
2. ❌ Repo context frozen at startup (couldn't see changes)
3. ❌ LLM cache never cleared (repeated same analysis)
4. ❌ Analysis caches became stale (wrong file structure info)

These fixes ensure:

1. ✅ Fresh file reads after writes
2. ✅ Updated repo context after execution
3. ✅ Fresh LLM analysis each iteration
4. ✅ Valid file structure analysis
5. ✅ **Iterative progress toward completion**
