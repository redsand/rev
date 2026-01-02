# Timeout Handling Fix - Complete Auto-Healing for Watch Mode

## Issues Found in Log `rev_run_20260101_224547.log`

### Issue 1: Timeout Occurred But Output Not Diagnostic
**Lines 43-58**:
```
→ run_tests test: ['npm', 'run', 'test']...
(600 second gap)
StdoutTail:
 → Test timed out in 5000ms.
If this is a long...
✗ [FAILED] npm run test | Reason: run_tests: error: command exceeded 600s timeout
```

**Problem**: The timeout worked and captured partial output, but:
1. The error message was generic: "command exceeded 600s timeout"
2. No diagnosis that this is watch mode
3. No suggested fix for the user or LLM
4. Rev couldn't auto-heal by detecting and fixing the `package.json`

---

## Fixes Applied

### Fix 1: Return Partial Output on Timeout

**File**: `rev/tools/command_runner.py` (lines 313-334)

**Before**:
```python
except subprocess.TimeoutExpired:
    proc.kill()
    stdout_data, stderr_data = proc.communicate()
    return {
        "timeout": timeout,
        "cmd": original_cmd_str,
        "cwd": str(resolved_cwd),
        "rc": -1,
        "error": f"command exceeded {timeout}s timeout",
    }
    # stdout_data and stderr_data were captured but NOT returned!
```

**After**:
```python
except subprocess.TimeoutExpired:
    proc.kill()
    stdout_data, stderr_data = proc.communicate()
    result = {
        "timeout": timeout,
        "cmd": original_cmd_str,
        "cwd": str(resolved_cwd),
        "rc": -1,
        "stdout": stdout_data or "",  # ✅ NOW RETURNED
        "stderr": stderr_data or "",  # ✅ NOW RETURNED
        "error": f"command exceeded {timeout}s timeout",
    }

    # Enhance timeout error with diagnostic information
    try:
        from rev.execution.timeout_recovery import enhance_timeout_error
        result = enhance_timeout_error(result)
    except Exception:
        pass  # Graceful degradation

    return result
```

**Impact**: LLM can now see what the command printed before timing out.

---

### Fix 2: Intelligent Timeout Diagnosis

**New File**: `rev/execution/timeout_recovery.py`

**Functions**:

1. **`analyze_timeout_output(result)`** - Detects common timeout causes:
   - Watch mode indicators: "watching for file changes", "press h for help", etc.
   - Hanging servers: "server listening on port", "application started"
   - Interactive prompts: "press", "waiting for input"

2. **`enhance_timeout_error(result)`** - Adds diagnosis and fix suggestions:
   ```python
   {
       "error": "command exceeded 600s timeout\n
                 Diagnosis: Test command is running in watch mode (non-terminating)\n
                 Suggested fix: Add '--run' flag to vitest or update package.json test script",
       "timeout_diagnosis": {
           "is_watch_mode": true,
           "diagnosis": "...",
           "suggested_fix": "..."
       }
   }
   ```

3. **`suggest_package_json_fix(test_script)`** - Auto-generates fix:
   - `"vitest"` → `"vitest run"`
   - `"jest"` → `"jest --no-watch"`

---

## Example: Auto-Healing Flow

### Before Fix:
```
1. Run: npm run test
2. (Waits 600 seconds)
3. Error: "command exceeded 600s timeout"
4. LLM sees generic error, no context
5. LLM might retry same command → same timeout
```

### After Fix:
```
1. Run: npm run test
2. (Waits 600 seconds, captures output: "Watching for file changes...")
3. Enhanced error returned:
   {
       "error": "command exceeded 600s timeout

                 Diagnosis: Test command is running in watch mode (non-terminating)

                 Suggested fix: Add '--run' flag to vitest command or update
                 package.json test script to use 'vitest run' instead of 'vitest'",
       "stdout": "...Watching for file changes...",
       "timeout_diagnosis": {
           "is_watch_mode": true,
           "suggested_fix": "Add '--run' flag..."
       }
   }
4. LLM sees diagnosis and suggested fix
5. LLM can:
   - Update package.json: `"test": "vitest"` → `"test": "vitest run"`
   - Or use direct command: `npx vitest run tests/`
6. Problem auto-healed ✅
```

---

## Timeout Configuration

### Current Defaults:
- **`run_cmd`**: 300 seconds (5 minutes)
- **`run_tests`**: 600 seconds (10 minutes)

### Timeout Behavior:
```python
# In run_command_safe()
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()  # Get partial output
    # Return with enhanced diagnosis ✅
```

### Environment Variable:
- `REV_DISABLE_TIMEOUTS=1` - Disable all timeouts (use with caution)

---

## Test Coverage

### New Tests:

**`tests/test_timeout_returns_output.py`**:
- ✅ Verifies partial stdout/stderr is captured after timeout
- ✅ Tests watch mode detection from output
- ✅ Confirms timeout kills process but preserves diagnostics

**`tests/test_timeout_recovery.py`**:
- ✅ Detects Vitest watch mode from output
- ✅ Detects Jest watch mode from output
- ✅ Detects hanging servers
- ✅ Suggests correct fixes for each framework
- ✅ Tests package.json fix generation

All tests pass ✅

---

## Real-World Example from Log

### What User Saw (Before Fix):
```
Line 58: ✗ [FAILED] npm run test | Reason: run_tests: error: command exceeded 600s timeout
```

### What User Will See Now (After Fix):
```
✗ [FAILED] npm run test | Reason: run_tests: error: command exceeded 600s timeout

Diagnosis: Test command is running in watch mode and waiting for file changes (non-terminating)

Suggested fix: Add '--run' flag to vitest command or update package.json test script to use 'vitest run' instead of 'vitest'

Output captured before timeout:
...
Vitest v5.x.x
Watching for file changes...
Press h for help, q to quit
Test timed out in 5000ms...
```

**Next orchestrator action**: LLM reads the diagnosis and suggests:
```
[EDIT] package.json to change "test": "vitest" to "test": "vitest run" to prevent watch mode hangs
```

---

## Integration Points

### 1. Command Runner
- `run_cmd()` and `run_tests()` both use `run_command_safe()`
- Timeout exception now returns enhanced diagnostics
- Backward compatible - works with existing code

### 2. Orchestrator
- Already has `timeout_needs_fix_note` mechanism (line 3748-3760 in orchestrator.py)
- Can leverage `timeout_diagnosis` field in result
- Work summary will include diagnosis for planner LLM

### 3. Test Executor Agent
- Already has proactive watch-mode blocking (`_block_non_terminating_command`)
- Now has **reactive** recovery via timeout diagnosis
- Can suggest fixes when watch mode slips through

---

## Files Modified

1. **rev/tools/command_runner.py** - Add stdout/stderr to timeout return, integrate diagnosis
2. **rev/execution/timeout_recovery.py** (new) - Diagnostic and auto-heal logic
3. **tests/test_timeout_returns_output.py** (new) - Verify output capture
4. **tests/test_timeout_recovery.py** (new) - Verify diagnosis logic

---

## Benefits

### Before:
- ❌ Generic timeout errors
- ❌ No diagnostic information
- ❌ LLM retries same command
- ❌ Wastes 10+ minutes per retry
- ❌ User must manually intervene

### After:
- ✅ Specific diagnosis (watch mode, hanging server, etc.)
- ✅ Actionable fix suggestions
- ✅ LLM can auto-heal by fixing package.json
- ✅ Single timeout leads to fix
- ✅ Fully autonomous recovery

---

## Summary

Rev now has **complete auto-healing** for timeout scenarios:

1. **Capture**: Partial stdout/stderr preserved when timeout occurs
2. **Diagnose**: Intelligent analysis detects watch mode, hanging servers, etc.
3. **Suggest**: Framework-specific fixes provided
4. **Heal**: LLM can apply fix and retry successfully

This ensures rev can handle real-world issues like watch-mode test runners autonomously, without requiring user intervention.
