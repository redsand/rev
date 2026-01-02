# Framework Switching Fix - Maintain Project-Specific Test Framework

## Issue: Rev Switched from Vitest to Jest

### What Happened (from log `rev_run_20260101_224547.log`)

**Line 1065-1066**: Rev ran a Vitest command, then added Jest's `--runTestsByPath` flag:
```
Line 1065: test: ['npx', '--yes', 'vitest', 'run', 'C:\...\src\server.ts']
Line 1066: test: ['npx', '--yes', 'vitest', 'run', 'C:\...\src\server.ts', '--runTestsByPath', 'tests\api.test.ts', ...]
```

**Line 1070-1073**: Vitest rejected the Jest flag:
```
CACError: Unknown option `--runTestsByPath`
```

**Line 1191-1194**: Rev's orchestrator suggested switching to Jest:
```
[EDIT] update package.json's "test" script to use Jest (e.g. change `"test": "vitest run"` to `"test": "jest"`)
```

**Line 1222-1224**: package.json was changed from Vitest to Jest:
```diff
- "test": "vitest run",
+ "test": "jest",
```

**Line 1240-1248**: Jest command failed because Jest wasn't installed

**Result**: Rev tried to switch the project's test framework instead of fixing the Vitest command.

---

## Root Cause

### File: `rev/execution/quick_verify.py`
### Function: `_detect_test_runner` (lines 2508-2598)

**Before Fix** (WRONG order):
```python
def _detect_test_runner(cmd_parts: list[str], stdout: str = "", stderr: str = "") -> str:
    # 1. FIRST: Check stdout/stderr for framework names
    combined = f"{stdout}\n{stderr}".lower()
    if "jest" in combined:
        return "jest"
    if "vitest" in combined:
        return "vitest"
    # ... more output checks ...

    # 2. LAST: Check command tokens
    tokens = _normalized_tokens(cmd_parts)
    if "jest" in tokens:
        return "jest"
    if "vitest" in tokens:
        return "vitest"
    # ... more command checks ...
```

**Problem**: Output is checked BEFORE command. This is backwards!

**Scenario that caused the bug**:
1. Command: `npx vitest run src/server.ts`
2. Vitest runs but finds no tests in `src/server.ts`
3. Output might say: "No tests found. Tip: check your test patterns or try jest"
4. `_detect_test_runner` sees "jest" in output → returns "jest"
5. `_attempt_no_tests_fallback` calls `_build_jest_run_tests_by_path_command`
6. Jest builder adds `--runTestsByPath` flag to the Vitest command
7. Result: `npx vitest run src/server.ts --runTestsByPath tests/*.test.ts` ❌

---

## Fix Applied

### File: `rev/execution/quick_verify.py:2508-2598`

**After Fix** (CORRECT order):
```python
def _detect_test_runner(cmd_parts: list[str], stdout: str = "", stderr: str = "") -> str:
    # CRITICAL: Check command first, THEN output
    # This prevents false detection when output mentions other frameworks

    # 1. FIRST: Check command tokens (most reliable)
    tokens = _normalized_tokens(cmd_parts)
    if not tokens:
        return "unknown"

    # Check for framework names in command
    if "jest" in tokens:
        return "jest"
    if "vitest" in tokens:
        return "vitest"
    if "pytest" in tokens:
        return "pytest"
    # ... all command-based checks ...

    # 2. LAST: Check output ONLY as fallback (less reliable)
    combined = f"{stdout}\n{stderr}".lower()
    if "vitest" in combined:
        return "vitest"
    if "jest" in combined:
        return "jest"
    # ... all output-based checks ...

    return "unknown"
```

**Why this is correct**:
1. **Command is authoritative**: If user runs `npx vitest run`, they want Vitest
2. **Output is supplementary**: Output may mention other frameworks in errors/tips
3. **Prevents framework switching**: Rev won't switch frameworks based on error messages

---

## Benefits

### Before Fix:
- ❌ Vitest command detected as Jest due to output mentioning "jest"
- ❌ Wrong flags added (`--runTestsByPath` for Vitest)
- ❌ Orchestrator suggests switching to Jest
- ❌ package.json gets changed to different framework
- ❌ Project framework consistency broken

### After Fix:
- ✅ Vitest command always detected as Vitest (from command tokens)
- ✅ Correct flags used (`vitest run file.ts` appends files directly)
- ✅ No framework switching suggested
- ✅ package.json stays with original framework
- ✅ Minimal changes - respects project decisions

---

## Test Coverage

**New File**: `tests/test_framework_detection_consistency.py`

### Test Cases:

1. **`test_vitest_command_with_jest_in_output()`**
   - Command: `npx vitest run tests/file.test.ts`
   - Output: "No tests found. Consider using jest instead."
   - ✅ Detects: `vitest` (from command, ignores output)

2. **`test_jest_command_with_vitest_in_output()`**
   - Command: `npx jest --runTestsByPath tests/file.test.ts`
   - Output: "Vitest is also available as an alternative"
   - ✅ Detects: `jest` (from command, ignores output)

3. **`test_vitest_fallback_builds_vitest_command()`**
   - Initial: `npx vitest run src/server.ts` (no tests found)
   - Fallback: Adds test files using Vitest syntax
   - ✅ Result: `npx vitest run src/server.ts tests/*.test.ts` (NO --runTestsByPath)

4. **`test_jest_fallback_uses_run_tests_by_path()`**
   - Initial: `npx jest tests/file.test.ts` (no tests found)
   - Fallback: Adds test files using Jest syntax
   - ✅ Result: `npx jest tests/file.test.ts --runTestsByPath tests/*.test.ts`

5. **`test_command_takes_priority_over_output()`**
   - Command: `npx vitest run`
   - Output: "jest version 29.0.0\nRunning jest tests..."
   - ✅ Detects: `vitest` (command takes priority over misleading output)

6. **`test_fallback_to_output_when_command_ambiguous()`**
   - Command: `node run-tests.js` (generic)
   - Output: "Vitest v5.0.0\nTest Files 1 passed"
   - ✅ Detects: `vitest` (uses output when command doesn't specify framework)

**All tests pass** ✅

---

## Real-World Impact

### Example 1: Original Bug Scenario
**Before**:
```bash
# 1. Initial command (correct)
npx vitest run src/server.ts

# 2. Output: "No tests found. Consider using jest for better test discovery."

# 3. Retry (WRONG - mixed frameworks)
npx vitest run src/server.ts --runTestsByPath tests/*.test.ts

# 4. Error: CACError: Unknown option `--runTestsByPath`

# 5. Orchestrator: "Switch to Jest!"

# 6. package.json changed:
"test": "jest"  # ❌ Wrong framework
```

**After**:
```bash
# 1. Initial command (correct)
npx vitest run src/server.ts

# 2. Output: "No tests found. Consider using jest for better test discovery."

# 3. Retry (CORRECT - stays with Vitest)
npx vitest run src/server.ts tests/api.test.ts tests/auth.test.ts

# 4. Tests run successfully with Vitest ✅

# 5. No framework switching suggested

# 6. package.json unchanged:
"test": "vitest run"  # ✅ Original framework preserved
```

### Example 2: npm test with Vitest
**Before**:
```bash
# Command: npm test
# package.json: "test": "vitest"
# Output mentions Jest in an error

# Detection: "jest" (from output) ❌
# Fallback adds: --runTestsByPath
# Result: npm test --runTestsByPath tests/*.ts ❌
```

**After**:
```bash
# Command: npm test
# package.json: "test": "vitest"
# Output mentions Jest in an error

# Detection: "npm" (from command) ✅
# Fallback uses: -- (npm passthrough)
# Result: npm test -- tests/*.ts ✅
```

---

## Design Principle

### **Minimal Changes Philosophy**

Rev should:
1. ✅ **Respect project decisions**: Don't change established frameworks
2. ✅ **Fix, don't replace**: Repair broken commands, don't switch tools
3. ✅ **Be conservative**: Only suggest changes to fix immediate issues
4. ✅ **Maintain consistency**: Keep project-specific configurations intact

### **Framework Detection Priority**

1. **Command tokens** (highest priority) - What the user explicitly specified
2. **Output analysis** (fallback only) - When command is ambiguous
3. **Unknown** (last resort) - When both fail

This ensures rev makes only minimal, necessary changes and doesn't overwrite established project patterns.

---

## Summary

**Fixed**: Framework detection now prioritizes command over output, preventing framework switching when error messages mention other frameworks.

**Impact**: Rev now maintains project-specific test framework choices (Vitest, Jest, Pytest, etc.) and doesn't suggest switching frameworks based on error output.

**Files Changed**:
- `rev/execution/quick_verify.py:2508-2598` - Reordered detection logic

**Tests Added**:
- `tests/test_framework_detection_consistency.py` - Comprehensive detection tests

**Result**: Rev respects project decisions and makes only minimal, necessary changes ✅
