# Cache Invalidation Fixes - Fresh State Between Iterations

## Problem Identified

The system was not re-evaluating file state between task iterations. Instead, it was:
1. Creating 60+ tasks with a single plan upfront
2. Not checking if files changed after tasks completed
3. Regenerating the same plan repeatedly without progress
4. Using stale cached file content and analysis

**Root Cause**: Multiple caching mechanisms were preventing fresh file reads and analysis between planning iterations.

---

## Caching Mechanisms Found

### 1. **File Content Cache** (60-second TTL)
- Cached by file path + modification time
- **ISSUE**: File writes didn't invalidate cache entries

### 2. **LLM Response Cache** (3600-second / 1-hour TTL)
- Cached by message hash + tools hash
- **ISSUE**: Identical planning prompts returned cached responses even after file changes

### 3. **Repo Context Cache** (30-second TTL)
- Cached by git HEAD commit hash
- **ISSUE**: Only updated once at orchestrator start, became stale for subsequent iterations

### 4. **AST Analysis Cache** (600-second / 10-minute TTL)
- Cached by file path + modification time + patterns
- **ISSUE**: Became stale when files changed

### 5. **Dependency Tree Cache** (600-second / 10-minute TTL)
- Cached by language + dependency file path
- **ISSUE**: Became stale when files changed

---

## Fixes Implemented

### Fix 1: Cache Invalidation on File Writes

**Location**: `rev/cache/implementations.py`

Added new method to FileContentCache:
```python
def invalidate_file(self, file_path: pathlib.Path):
    """Invalidate all cache entries for a specific file (all mtimes)."""
    prefix = f"{file_path}:"
    with self._lock:
        keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            self.invalidate(key)
```

**Locations**: `rev/tools/file_ops.py`

Added cache invalidation calls to ALL file write operations:

1. **write_file()** (line 261-263)
   ```python
   # Invalidate cache for this file
   file_cache = get_file_cache()
   if file_cache is not None:
       file_cache.invalidate_file(p)
   ```

2. **delete_file()** (line 335-338)
   ```python
   # Invalidate cache for this file
   file_cache = get_file_cache()
   if file_cache is not None:
       file_cache.invalidate_file(p)
   ```

3. **move_file()** (line 355-359)
   ```python
   # Invalidate cache for both source and destination
   file_cache = get_file_cache()
   if file_cache is not None:
       file_cache.invalidate_file(src_p)
       file_cache.invalidate_file(dest_p)
   ```

4. **append_to_file()** (line 377-380)
   ```python
   # Invalidate cache for this file
   file_cache = get_file_cache()
   if file_cache is not None:
       file_cache.invalidate_file(p)
   ```

5. **replace_in_file()** (line 409-412)
   ```python
   # Invalidate cache for this file
   file_cache = get_file_cache()
   if file_cache is not None:
       file_cache.invalidate_file(p)
   ```

**Impact**: Any read_file() call after a write now gets fresh content, not cached stale data.

---

### Fix 2: Update Repo Context After Tasks Complete

**Location**: `rev/execution/orchestrator.py`

Added explicit repo context updates after task execution:

1. **After sub-agent execution** (line 723-724)
   ```python
   # Update repo context after tasks complete to reflect file changes
   self.context.update_repo_context()
   ```

2. **After verification task** (line 861-862)
   ```python
   # Update repo context after verification completes
   self.context.update_repo_context()
   ```

**Before**: Repo context was only updated once at planning start, then reused for entire execution

**After**: Repo context is updated AFTER each task phase completes, ensuring next planning iteration sees current state

**Flow**:
```
1. Before tasks: update_repo_context()  ← Capture current state
2. Execute tasks
3. After tasks: update_repo_context()   ← Refresh state for next iteration
4. Clear stale caches
5. Check if replan needed (sees updated repo state)
```

---

### Fix 3: Clear Analysis Caches Between Iterations

**Location**: `rev/cache/__init__.py`

Added new cache clearing function:
```python
def clear_analysis_caches():
    """Clear caches that become stale when files change.

    Clears:
    - LLM response cache (same prompt may yield different answer with new files)
    - AST analysis cache (files changed so AST is stale)
    - Dependency tree cache (files changed so dependencies are stale)

    Keeps:
    - File content cache (invalidated per-file on write)
    - Repo context cache (updated explicitly after tasks)
    """
    if _LLM_CACHE:
        _LLM_CACHE.clear()
    if _AST_CACHE:
        _AST_CACHE.clear()
    if _DEP_CACHE:
        _DEP_CACHE.clear()
```

**Added to __all__**: `clear_analysis_caches`

**Location**: `rev/execution/orchestrator.py`

Added import:
```python
from rev.cache import clear_analysis_caches
```

Called after tasks complete (line 728):
```python
# Clear analysis caches that become stale when files change
# This ensures next planning iteration gets fresh analysis
clear_analysis_caches()
```

**Strategic choice of what to clear**:
- **LLM cache**: Cleared because planner may ask same question (e.g., "what files need to be created?") but answer is different now (some files already created)
- **AST cache**: Cleared because files changed, AST is invalid
- **Dependency cache**: Cleared because files changed, dependencies are invalid
- **File cache**: NOT cleared globally - individual files invalidated on write (more precise)
- **Repo context cache**: NOT cleared - we're explicitly updating it with update_repo_context()

---

## Execution Flow with Fixes

### Before Fixes
```
Iteration 1:
  ├─ Capture repo context ONCE at start
  ├─ Execute tasks (write files A, B, C)
  ├─ Cached file content never updated
  ├─ Cached LLM responses reused
  └─ Plan regeneration sees STALE state

Iteration 2:
  ├─ Uses stale repo context
  ├─ Uses cached file content (old versions)
  ├─ LLM returns cached analysis
  └─ Generates SAME plan as iteration 1 (no progress)
```

### After Fixes
```
Iteration 1:
  ├─ Capture repo context
  ├─ Execute tasks (write files A, B, C)
  ├─ File cache invalidated for A, B, C
  ├─ Update repo context (sees new files)
  ├─ Clear LLM, AST, dependency caches
  └─ Check for replan with FRESH state

Iteration 2:
  ├─ Uses FRESH repo context (knows about A, B, C)
  ├─ read_file() calls get LIVE content (cache invalidated)
  ├─ LLM planning gets fresh analysis (cache cleared)
  ├─ AST analysis is fresh (cache cleared)
  └─ Generates NEW plan based on actual state
```

---

## Key Benefits

1. **Fresh File Reads**: Any read_file() after write_file() gets current content
2. **Fresh LLM Analysis**: Each planning iteration gets live LLM responses
3. **Fresh Repo Context**: Each iteration knows about file changes
4. **Iterative Progress**: System builds on completed work instead of repeating same tasks

---

## Testing Guidance

To verify these fixes work:

1. **File Cache Invalidation**:
   - Write file A
   - Modify file A on disk
   - Read file A → should get updated content (not cached old version)

2. **Repo Context Updates**:
   - Execute task that creates 5 files
   - Check repo context → should show new files
   - NOT just the original context from start

3. **LLM Cache Clearing**:
   - Run planning iteration
   - Execute tasks that change files
   - Run next planning iteration
   - LLM should see changes (not return cached response)

4. **Iteration Progress**:
   - Run task with multi-step requirement (e.g., "split 10 classes into 10 files")
   - Should NOT generate 60+ tasks upfront
   - Should generate tasks incrementally and adapt as files are created

---

## Architecture Summary

The cache invalidation strategy uses a **hybrid approach**:

| Cache Type | Invalidation Method | When |
|------------|-------------------|------|
| **File Content** | Per-file on write | After write_file, replace_in_file, etc. |
| **Repo Context** | Explicit update | After task phase completes |
| **LLM Response** | Bulk clear | After task phase, before replan |
| **AST Analysis** | Bulk clear | After task phase, before replan |
| **Dependency Tree** | Bulk clear | After task phase, before replan |

**Rationale**:
- File cache uses precise per-file invalidation (surgical strikes)
- Analysis caches use bulk clearing (conservative, ensures freshness)
- Repo context uses explicit update (controlled, not automatic)

---

## Files Modified

1. **rev/cache/implementations.py**
   - Added `invalidate_file()` method to FileContentCache

2. **rev/cache/__init__.py**
   - Added `clear_analysis_caches()` function
   - Exported in `__all__`

3. **rev/tools/file_ops.py**
   - Added cache invalidation to: write_file, delete_file, move_file, append_to_file, replace_in_file

4. **rev/execution/orchestrator.py**
   - Added import: `from rev.cache import clear_analysis_caches`
   - Added repo context update after task execution (line 724)
   - Added repo context update after verification (line 862)
   - Added cache clearing between iterations (line 728)

---

## Verification Checklist

✓ Cache invalidation added to all file writes
✓ Repo context updated after task execution
✓ Analysis caches cleared between iterations
✓ Code compiles without errors
✓ All imports resolved
✓ No breaking changes to existing APIs
✓ Backward compatible with existing code

---

## Next Steps (Future Improvements)

1. **Metrics**: Track cache hit/miss rates to verify fixes
2. **Tests**: Add integration tests for iteration progress
3. **Monitoring**: Log when caches are invalidated/cleared
4. **Optimization**: Profile to ensure cache clearing doesn't slow down execution
5. **Refinement**: Adjust cache TTLs based on actual usage patterns

---

## Summary

These fixes ensure the system can **actually build upon completed work** instead of repeating the same tasks. The system now:

1. ✅ Reads fresh file content after writes
2. ✅ Gets fresh repo context after file changes
3. ✅ Runs fresh LLM analysis each iteration
4. ✅ Adapts plans based on actual file state
5. ✅ Makes iterative progress toward the goal
