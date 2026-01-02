# Test Command Validation Fix - qwen3-coder Regression

**Date**: 2025-12-25
**Issue**: qwen3-coder model choosing `pytest` even when task explicitly says "npm test" on Node.js projects

## Problem Analysis

### Regression Discovered
In `rev_run_20251225_134222.log` (lines 593, 726, 1045), the qwen3-coder model was running `pytest` on a Node.js project despite:
1. Task description explicitly saying "Run npm test to validate changes to app.js"
2. Project having `package.json` file (Node.js marker)
3. Task mentioning `.js` file extension

**Example from log**:
```
Line 172: TestExecutorAgent executing task: Run npm test to validate the changes to C:\Users\champ\source\repos\test-app\app.js
Line 1045: -> Executing: run_tests {'cmd': 'pytest'}
Line 1050: tool_noop: run_tests found 0 tests to run
```

**Result**: Circuit breaker triggered after 3 failed attempts

### Root Cause
The issue was **NOT** with the fallback heuristic (which had project type detection). The problem was that:
1. qwen3-coder model successfully made a tool call (no recovery needed)
2. But it **chose the wrong command** (`pytest` instead of `npm test`)
3. The system prompt wasn't explicit enough about extracting commands from task description
4. There was no validation layer to catch bad LLM choices

## Solution Implemented

### Three-Layer Defense

#### Layer 1: Strengthened System Prompt
Enhanced `TEST_EXECUTOR_SYSTEM_PROMPT` with explicit command selection priority:

```python
CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format
2. COMMAND SELECTION PRIORITY (in order):
   a) If task description contains an explicit command (npm test, pytest, etc.), USE THAT EXACT COMMAND
   b) If task says to validate/test Node.js/JavaScript files, use npm test (NOT pytest)
   c) If task says to validate/test Python files, use pytest
   d) Check workspace context for package.json (npm test), go.mod (go test), etc.
3. NEVER use pytest for Node.js/JavaScript projects (files ending in .js, .ts, .jsx, .tsx)
```

Added explicit examples showing:
- Task says "npm test" → use npm test
- Task mentions `.js` file → use npm test
- Task mentions `.py` file → use pytest

**File**: `rev/agents/test_executor.py` (lines 13-68)

#### Layer 2: Command Validation Before Execution
Added `_validate_and_correct_test_command()` method that validates LLM choices:

**Priority 1**: Check task description for explicit commands
- If task says "npm test" but LLM chose "pytest", correct to "npm test"

**Priority 2**: Check file extensions in task
- `.js`, `.ts`, `.jsx`, `.tsx`, `app.js` → npm test
- `.py` → pytest
- `.go` → go test

**Priority 3**: Check workspace for project type markers
- `package.json` exists + no Python markers → npm test
- Mixed projects (both Node.js and Python files) → keep Python command

**File**: `rev/agents/test_executor.py` (lines 321-396)

**Applied in two paths**:
1. Normal LLM response path (lines 156-162)
2. Tool call recovery path (lines 126-132)

#### Layer 3: Debug Logging
When correction happens:
```
[!] Correcting test command: pytest -> npm test
```

This makes it visible when the LLM makes a bad choice.

## Test Coverage

**File**: `tests/test_test_command_validation.py` (13 tests, all passing)

### Test Classes

1. **TestCommandValidation** (3 tests)
   - Explicit "npm test" overrides pytest choice
   - Explicit "pytest" overrides npm choice
   - Yarn test explicit command

2. **TestFileExtensionDetection** (4 tests)
   - `.js` file triggers npm test
   - `.ts` file triggers npm test
   - `.py` file triggers pytest
   - `.go` file triggers go test

3. **TestWorkspaceDetection** (3 tests)
   - `package.json` triggers npm test
   - `yarn.lock` triggers yarn test
   - Mixed projects (Node.js + Python) prefer Python when markers exist

4. **TestIntegrationWithLLM** (2 tests)
   - LLM pytest choice gets corrected before execution
   - LLM correct choice is not modified

5. **TestRecoveryPathValidation** (1 test)
   - Recovery path also corrects bad commands

### Combined Test Suite Status
```
============================= 49 passed in 8.14s ==============================
```

- 15 tests: Performance fixes
- 12 tests: TestExecutor fixes
- 9 tests: Edit optimizations
- 13 tests: Test command validation (NEW)

## Impact

### Before Fix
- qwen3-coder chooses `pytest` on Node.js projects
- Task fails with "found 0 tests to run"
- Circuit breaker triggers after 3 failures
- No forward progress

### After Fix
1. **Prompt guidance**: LLM receives clear instructions about command priority
2. **Validation layer**: Bad LLM choices are corrected automatically
3. **Works for all models**: Not just qwen3-coder, but any model that might make bad choices
4. **Debug visibility**: Corrections are logged for monitoring

### Expected Results
- Task: "Run npm test to validate app.js"
- LLM chooses: "pytest"
- System corrects: "pytest" → "npm test"
- Log shows: `[!] Correcting test command: pytest -> npm test`
- Execution succeeds on first try

## How It Works

### Example Flow

**Task**: "Run npm test to validate the changes to app.js"

**Without fix**:
```
1. qwen3-coder receives task
2. qwen3-coder responds: {"tool_name": "run_tests", "arguments": {"cmd": "pytest"}}
3. System executes: pytest
4. Result: found 0 tests to run
5. Circuit breaker after 3 failures
```

**With fix**:
```
1. qwen3-coder receives improved prompt with examples
2. qwen3-coder responds: {"tool_name": "run_tests", "arguments": {"cmd": "pytest"}} (if still wrong)
3. System validates: _validate_and_correct_test_command("pytest", task, context)
4. Priority 1 check: task contains "npm test" → return "npm test"
5. Log: [!] Correcting test command: pytest -> npm test
6. System executes: npm test
7. Result: tests run successfully
```

## Files Modified

1. **`rev/agents/test_executor.py`**
   - Lines 13-68: Enhanced system prompt with command priority
   - Lines 126-132: Command validation in recovery path
   - Lines 156-162: Command validation in normal path
   - Lines 321-396: `_validate_and_correct_test_command()` method

2. **`tests/test_test_command_validation.py`** (NEW)
   - 13 comprehensive tests
   - All passing

## Integration with Existing Fixes

This fix works together with:
- **TestExecutor project type detection** (fallback heuristic)
- **Tool call recovery** (handles malformed responses)
- **Test skip logic** (prevents redundant test runs)
- **Performance fixes** (research budget, redundant read blocking)
- **Edit optimizations** (mandatory file reading, escalation)

## Validation

To verify this fix works as expected:

### Test Case 1: Explicit npm test in task
**Before**: qwen3-coder chooses pytest, task fails
**After**: Command corrected to npm test, task succeeds

### Test Case 2: Task mentions .js file
**Before**: qwen3-coder chooses pytest, finds 0 tests
**After**: Command corrected to npm test based on file extension

### Test Case 3: Generic task on Node.js project
**Before**: qwen3-coder chooses pytest, fails
**After**: Command corrected based on workspace having package.json

### Test Case 4: Correct LLM choice
**Before**: N/A
**After**: No correction applied, executes as-is

## Next Steps

### Completed
- Enhanced system prompt with command priority
- Implemented validation layer for both normal and recovery paths
- Created comprehensive test coverage (13 tests)
- Verified integration with existing 36 tests (49 total passing)

### Recommended
- Monitor correction logs in production runs to track LLM choice quality
- Consider adding telemetry to track which models make correct vs incorrect choices
- Potentially tune system prompt further if specific models consistently make bad choices

## Summary

The qwen3-coder regression has been fixed with a three-layer defense:
1. Better prompt guidance
2. Automatic command validation
3. Debug logging for visibility

This ensures that **no LLM model** can choose the wrong test command for a project type, preventing the circuit breaker failure that was observed in the log.

**Test Status**: 49/49 passing (13 new tests for this fix)
**Production Ready**: Yes
**Breaking Changes**: None
