# Loop-Guard Test Task TDD Handling Fix

**Date**: 2025-12-25
**Issue**: Circuit breaker triggered after loop-guard injected test task failed 3 times
**Log**: `rev_run_20251225_144649.log`

---

## Problem Summary

**Circuit Breaker Message**:
```
Repeated failure signature 'test::Tests failed (rc=1)' after 3 attempts.
Last verification: Tests failed (rc=1).
Last tool: run_tests. run_tests rc=1
```

**Root Cause**: Loop-guard injected test task doesn't set TDD state flags, so legitimate test failures are treated as verification failures.

---

## Origin Trace

### 1. Loop-Guard Detects Research Loop
**File**: `rev/execution/orchestrator.py:2694-2792`

```
[loop-guard] Repeated READ/ANALYZE detected; checking if goal is achieved.
[loop-guard] Blocked action signature: analyze::search for patterns...
[loop-guard] Injecting targeted fallback: Instead of re-reading files, validate the current state by running tests...
```

**Code** (line 2786):
```python
# No specific file - suggest running tests or verification
next_task.action_type = "test"
next_task.description = (
    "Instead of re-reading files, validate the current state by running tests: "
    "Use pytest for Python code, npm test for JavaScript, or appropriate linting/build commands. "
    "This will reveal actual blocking issues that need to be fixed."
)
```

### 2. Test Task Executes
**Log** (line 842):
```
[!] Correcting test command: pytest -> npm test
-> Executing: run_tests {'cmd': 'npm test'}
```

Tests run, return `rc=1` (failure) - **expected in TDD mode** when implementation doesn't exist yet.

### 3. Verification Fails
**File**: `rev/execution/quick_verify.py:2979-3015`

```python
if payload and isinstance(payload.get("rc"), int):
    rc = payload.get("rc", 1)
    if rc == 0:
        return VerificationResult(passed=True, message="Tests passed")
    # rc != 0
    return VerificationResult(
        passed=False,
        message=f"Tests failed (rc={rc})",
        details={"rc": rc, "output": output[:500]},
        should_replan=True  # <-- Triggers replan
    )
```

### 4. TDD Override Not Applied
**File**: `rev/execution/quick_verify.py:278-289`

```python
# TDD: allow "red" test failures before implementation.
if config.TDD_ENABLED and action_type == "test":
    if (
        not result.passed
        and context.agent_state.get("tdd_pending_green")  # <-- NOT SET
        and not context.agent_state.get("tdd_require_test")
    ):
        return _apply_tdd_red_override(...)
```

**Problem**: `tdd_pending_green` flag is **not set** when loop-guard injects the test task.

**Result**: TDD override doesn't apply, test failure is treated as verification failure.

### 5. Circuit Breaker Triggers
**File**: `rev/execution/orchestrator.py:~2900`

After 3 consecutive failures with same signature `'test::Tests failed (rc=1)'`, circuit breaker stops execution.

---

## Expected Behavior

**Two scenarios**:

### Scenario A: TDD Mode (Tests First, Then Implementation)
1. Loop-guard detects research loop
2. Loop-guard injects TEST task
3. Tests run and **legitimately fail** (rc=1) because implementation doesn't exist
4. **Expected**: Verification should PASS with message "TDD red: tests failed as expected"
5. **Actual**: Verification FAILS, triggers replan, eventually hits circuit breaker

### Scenario B: Non-TDD Mode (Implementation exists, tests should pass)
1. Loop-guard detects research loop
2. Loop-guard injects TEST task
3. Tests run and fail (rc=1) because there's a bug in implementation
4. **Expected**: Verification FAILS, provides useful error output to guide fixes
5. **Actual**: Works correctly (this is the current behavior)

---

## The Fix

### Option 1: Set TDD Flag When Injecting Test Task (RECOMMENDED)

**File**: `rev/execution/orchestrator.py:2786`

**Before**:
```python
# No specific file - suggest running tests or verification
next_task.action_type = "test"
next_task.description = (
    "Instead of re-reading files, validate the current state by running tests: "
    "Use pytest for Python code, npm test for JavaScript, or appropriate linting/build commands. "
    "This will reveal actual blocking issues that need to be fixed."
)
```

**After**:
```python
# No specific file - suggest running tests or verification
next_task.action_type = "test"
next_task.description = (
    "Instead of re-reading files, validate the current state by running tests: "
    "Use pytest for Python code, npm test for JavaScript, or appropriate linting/build commands. "
    "This will reveal actual blocking issues that need to be fixed."
)
# CRITICAL: Set TDD flag so test failures are allowed in TDD mode
# Loop-guard test tasks are diagnostic - don't fail on test failures in TDD
if config.TDD_ENABLED:
    context.agent_state["tdd_pending_green"] = True
```

**Why this works**:
- When TDD is enabled, loop-guard test tasks are diagnostic
- Test failures should be treated as information, not verification failures
- Allows the system to see test output and plan next steps based on actual errors

### Option 2: Add Diagnostic Test Mode

**File**: `rev/execution/quick_verify.py:2926`

Add check for loop-guard injected tests:

```python
def _verify_test_execution(task: Task, context: RevContext) -> VerificationResult:
    """Verify that tests actually passed."""

    # Check if this is a loop-guard diagnostic test
    is_diagnostic = context.agent_state.get("loop_guard_diagnostic_test", False)

    if payload and isinstance(payload.get("rc"), int):
        rc = payload.get("rc", 1)
        if rc == 0:
            return VerificationResult(passed=True, message="Tests passed")

        # For diagnostic tests in TDD mode, treat failures as informational
        if is_diagnostic and config.TDD_ENABLED:
            return VerificationResult(
                passed=True,  # Don't fail verification
                message=f"Diagnostic test run: tests failed (rc={rc}) - output captured for planning",
                details={"rc": rc, "output": output[:500], "diagnostic": True}
            )

        # Normal test failure
        return VerificationResult(
            passed=False,
            message=f"Tests failed (rc={rc})",
            details={"rc": rc, "output": output[:500]},
            should_replan=True
        )
```

**Why this is better**:
- More explicit about the purpose (diagnostic vs. verification)
- Allows test output to be captured without triggering failures
- Clearer separation of concerns

---

## Recommendation

**Use Option 1** (simpler, 3 lines of code):

```python
# In orchestrator.py line 2792, add:
if config.TDD_ENABLED:
    context.agent_state["tdd_pending_green"] = True
```

This is simpler and aligns with existing TDD infrastructure. It tells the verification system "we're in TDD mode, test failures are expected until implementation is complete."

---

## Expected Results After Fix

### Before Fix
1. Loop-guard injects TEST task
2. Tests fail (rc=1)
3. Verification fails
4. Replan triggered
5. Repeat 3 times → Circuit breaker

### After Fix
1. Loop-guard injects TEST task + sets `tdd_pending_green` flag
2. Tests fail (rc=1)
3. Verification passes with "TDD red: tests failed as expected"
4. System captures test output and uses it to plan implementation
5. No circuit breaker, forward progress continues

---

## Test Plan

1. **Test TDD mode with failing tests**:
   - Create test file that expects functionality
   - Run REV in TDD mode
   - Loop-guard should inject test task
   - Verify test failure is treated as "TDD red" not verification failure

2. **Test non-TDD mode**:
   - Disable TDD mode
   - Same scenario
   - Test failure should be treated as verification failure (existing behavior)

3. **Test with passing tests**:
   - Tests pass (rc=0)
   - Should work in both TDD and non-TDD mode

---

## Files to Modify

**Only one file**: `rev/execution/orchestrator.py`

**Only one location**: Line ~2792 (after setting action_type="test")

**Only 3 lines of code**:
```python
if config.TDD_ENABLED:
    context.agent_state["tdd_pending_green"] = True
```

---

## Summary

**Problem**: Loop-guard injected test tasks trigger circuit breaker when tests legitimately fail in TDD mode.

**Root Cause**: Loop-guard doesn't set TDD state flags, so test failures aren't recognized as expected "TDD red" state.

**Fix**: Set `tdd_pending_green` flag when injecting test tasks in TDD mode.

**Impact**: Loop-guard test tasks become diagnostic in TDD mode, allowing test output to inform planning without triggering circuit breaker.

**Philosophy**: "Simpler is better" - 3 lines of code, uses existing TDD infrastructure.
