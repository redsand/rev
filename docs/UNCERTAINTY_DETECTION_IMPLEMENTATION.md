# Uncertainty Detection Implementation

## Summary

Implemented a comprehensive uncertainty detection system that prompts users for guidance when Rev is uncertain, instead of retrying blindly.

**Status**: ✅ **COMPLETE** - Fully implemented and tested

---

## What Changed

### 1. Core Detection System (`rev/execution/uncertainty_detector.py`)

**New Module**: Detects uncertainty across multiple phases of execution

#### Detection Functions

**`_detect_planning_uncertainty()`**
- Detects hesitation markers in LLM responses: "could try", "might work", "not sure", "unclear"
- Detects multiple file references that could be ambiguous
- Returns `UncertaintySignal` objects with scores

**`_detect_execution_uncertainty()`**
- Detects repeated failures (3+ times with same error) → score: 5
- Detects no progress (identical errors across all attempts) → score: 4
- Detects no tool calls (agent just returning text) → score: 4

**`_detect_verification_uncertainty()`**
- Detects inconclusive verification results → score: 3
- Detects unclear timeouts (no diagnosis) → score: 2
- Detects conflicting signals (tests pass but validation fails) → score: 3

**`detect_uncertainty()`** - Comprehensive detection
- Combines all detection phases
- Returns total score and list of signals
- Threshold: 5 points triggers guidance request

#### Uncertainty Weights

```python
UNCERTAINTY_WEIGHTS = {
    "planner_hesitation": 2,
    "multiple_files": 3,
    "repeated_failure": 5,      # High priority
    "no_tool_calls": 4,
    "verification_inconclusive": 3,
    "missing_files": 2,
    "timeout_unclear": 2,
    "conflicting_signals": 3,
    "no_progress": 4,           # High priority
}
```

---

### 2. User Guidance Dialog (`rev/execution/user_guidance.py`)

**New Module**: Handles user interaction when uncertainty detected

#### Key Functions

**`request_user_guidance()`**
- Shows uncertainty reasons to user
- Provides 4 options:
  1. Provide specific guidance (retry with user instructions)
  2. Skip this task and continue
  3. Retry with current approach
  4. Abort execution
- Supports TUI and terminal fallback
- Returns `GuidanceResponse` with user's choice

#### Dialog Example

```
🤔 Rev is uncertain and needs guidance:
• Task failed 3 times with identical error: ModuleNotFoundError: No module named 'pytest'
• No progress - same error on every attempt

Task: run tests for auth module
Attempts: 3
Last Error: ModuleNotFoundError: No module named 'pytest'

[Options]
  [1] Provide specific guidance (describe what to do)
  [2] Skip this task and continue
  [3] Retry with current approach
  [4] Abort execution

Choice [1-4]: 1
What should Rev do? (be specific): Run pip install pytest first, then retry the tests

✓ Guidance received: Run pip install pytest first, then retry the tests
```

---

### 3. Configuration (`rev/config.py`)

**New Settings** (lines 461-464):

```python
# Uncertainty detection - prompts user for guidance when Rev is uncertain
UNCERTAINTY_DETECTION_ENABLED = os.getenv("REV_UNCERTAINTY_DETECTION_ENABLED", "true").strip().lower() == "true"
UNCERTAINTY_THRESHOLD = int(os.getenv("REV_UNCERTAINTY_THRESHOLD", "5"))  # Score to trigger guidance request
UNCERTAINTY_AUTO_SKIP_THRESHOLD = int(os.getenv("REV_UNCERTAINTY_AUTO_SKIP_THRESHOLD", "10"))  # Score to auto-skip
```

#### Environment Variables

- `REV_UNCERTAINTY_DETECTION_ENABLED=true|false` - Enable/disable feature (default: true)
- `REV_UNCERTAINTY_THRESHOLD=N` - Score threshold to trigger guidance (default: 5)
- `REV_UNCERTAINTY_AUTO_SKIP_THRESHOLD=N` - Score to auto-skip task (default: 10)

---

### 4. Orchestrator Integration (`rev/execution/orchestrator.py`)

#### Integration Point 1: After 2+ Failures (lines 5593-5655)

**Trigger**: When `failure_counts[failure_sig] >= 2`

**Behavior**:
1. Collect error history for better detection
2. Run `detect_uncertainty()` on the task
3. If score ≥ threshold (5), request user guidance
4. Handle response:
   - **Abort** → Stop execution, return False
   - **Skip** → Mark task completed, continue to next
   - **Retry with guidance** → Inject guidance into task description, reset failure count, retry

**Code Added**:
```python
# Uncertainty detection: Check if we should request user guidance
if config.UNCERTAINTY_DETECTION_ENABLED and failure_counts[failure_sig] >= 2:
    from rev.execution.uncertainty_detector import detect_uncertainty
    from rev.execution.user_guidance import request_user_guidance, format_guidance_for_task

    # Detect uncertainty
    uncertainty_score, uncertainty_signals = detect_uncertainty(
        task=next_task,
        retry_count=failure_counts[failure_sig],
        verification_result=verification_result,
        previous_errors=previous_errors
    )

    # Request guidance if threshold reached
    if uncertainty_score >= config.UNCERTAINTY_THRESHOLD:
        guidance_response = request_user_guidance(
            uncertainty_signals=uncertainty_signals,
            task=next_task,
            context={"retry_count": failure_counts[failure_sig]}
        )
        # ... handle response ...
```

#### Integration Point 2: Circuit Breaker Override (lines 5735-5784)

**Trigger**: When `total_recovery_attempts >= 10` (about to abort)

**Behavior**:
1. Show circuit breaker warning
2. Create high-severity uncertainty signal (score: 10)
3. Request user guidance as last resort
4. If user provides guidance:
   - Reset recovery counters
   - Inject guidance
   - Give it one more try
5. Otherwise, trigger circuit breaker as normal

**Code Added**:
```python
# Last resort: Request user guidance before circuit breaker
if config.UNCERTAINTY_DETECTION_ENABLED:
    print(f"\n[{colorize('🛑 CIRCUIT BREAKER: RECOVERY LIMIT EXCEEDED', Colors.BRIGHT_RED, bold=True)}]")

    # Create a high-severity uncertainty signal
    circuit_breaker_signal = UncertaintySignal(
        signal_type="circuit_breaker",
        reason=f"Circuit breaker triggered after {total_recovery_attempts} recovery attempts",
        score=10  # Maximum score
    )

    guidance_response = request_user_guidance(
        uncertainty_signals=[circuit_breaker_signal],
        task=next_task,
        context={"circuit_breaker": True}
    )

    if guidance_response and guidance_response.action == "retry" and guidance_response.guidance:
        # User override - reset and retry with guidance
        self.context.set_agent_state("total_recovery_attempts", 0)
        # ... inject guidance and continue ...
```

---

## Files Created

1. **rev/execution/uncertainty_detector.py** (379 lines)
   - Core detection logic
   - Signal types and scoring
   - Comprehensive detection functions

2. **rev/execution/user_guidance.py** (271 lines)
   - User dialog system
   - TUI and terminal support
   - Response handling

3. **tests/test_uncertainty_detection.py** (332 lines)
   - Comprehensive test suite
   - 11 test cases covering all detection scenarios
   - All tests passing ✅

4. **docs/UNCERTAINTY_DETECTION_IMPLEMENTATION.md** (this file)
   - Implementation documentation

---

## Files Modified

1. **rev/config.py**
   - Added 3 configuration variables (lines 461-464)

2. **rev/execution/orchestrator.py**
   - Added uncertainty detection after 2+ failures (lines 5593-5655)
   - Added circuit breaker override with guidance (lines 5735-5784)

3. **rev/tools/git_ops.py**
   - Fixed indentation error (line 1339)
   - Added missing import (line 24)

---

## Test Results

All 11 unit tests pass:

```
[OK] Detected planner hesitation
[OK] Detected multiple files
[OK] Detected repeated failure
[OK] Detected no progress
[OK] Detected inconclusive verification
[OK] Detected unclear timeout
[OK] Comprehensive detection (score: 10, signals: 3)
[OK] Formatted reasons
[OK] Threshold logic works correctly
[OK] No execution uncertainty on first attempt
[OK] Uncertainty increases with retries (retry_1=4, retry_3=13)

[OK] All uncertainty detection tests passed!
```

---

## Usage Examples

### Example 1: Repeated Test Failure

**Scenario**: Test command fails 3 times with "Module not found"

```
  [circuit-breaker] Same error detected 3x: modulenotfounderror

🤔 Rev is uncertain and needs guidance:
• Task failed 3 times with identical error: ModuleNotFoundError: No module named 'pytest'
• No progress - same error on every attempt

Task: run tests for auth module
Attempts: 3
Last Error: ModuleNotFoundError: No module named 'pytest'

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 1
What should Rev do? Install pytest first: pip install pytest

✓ Guidance received: Install pytest first: pip install pytest

  [USER GUIDANCE] Install pytest first: pip install pytest
```

**Result**: Task description updated with user guidance, failure count reset, retries with guidance

### Example 2: Circuit Breaker Override

**Scenario**: 10 recovery attempts exhausted

```
🛑 CIRCUIT BREAKER: RECOVERY LIMIT EXCEEDED
Made 10 recovery attempts across all errors.
This indicates a fundamental issue that cannot be auto-fixed.

🤔 Rev is uncertain and needs guidance:
• Circuit breaker triggered after 10 recovery attempts

Task: fix authentication system
Attempts: 11

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 1
What should Rev do? The auth.ts file is actually at src/lib/auth.ts, not src/auth.ts

✓ Guidance received: The auth.ts file is actually at src/lib/auth.ts

  [USER OVERRIDE] The auth.ts file is actually at src/lib/auth.ts
```

**Result**: Recovery counters reset, guidance injected, execution continues

### Example 3: Skip Task

**Scenario**: User decides to skip uncertain task

```
🤔 Rev is uncertain and needs guidance:
• Task failed 2 times with identical error
• Missing files: tests/integration.test.ts

Task: run integration tests
Attempts: 2

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 2

→ Skipping task

  [USER GUIDANCE] Skipping task
```

**Result**: Task marked as completed, execution continues to next task

---

## Benefits

### Before (Without Uncertainty Detection)
- ❌ Rev retries blindly until circuit breaker
- ❌ User unaware of uncertainty or struggling
- ❌ Wasted time on wrong approaches
- ❌ Silent assumptions that may be incorrect

### After (With Uncertainty Detection)
- ✅ Rev asks when uncertain (after 2+ failures)
- ✅ User provides specific guidance
- ✅ Faster resolution with correct information
- ✅ Transparent about confidence level
- ✅ User stays in control
- ✅ Circuit breaker becomes last resort, not only resort

---

## Configuration Options

### Disable Uncertainty Detection
```bash
export REV_UNCERTAINTY_DETECTION_ENABLED=false
```

### Adjust Threshold (More Sensitive)
```bash
export REV_UNCERTAINTY_THRESHOLD=3  # Ask earlier (default: 5)
```

### Adjust Auto-Skip Threshold
```bash
export REV_UNCERTAINTY_AUTO_SKIP_THRESHOLD=15  # Higher bar for auto-skip (default: 10)
```

---

## Architecture

### Detection Flow

```
Task Execution
     ↓
Failure Detected
     ↓
Retry Count ≥ 2?
     ↓ Yes
Detect Uncertainty
     ↓
Calculate Score
     ↓
Score ≥ Threshold (5)?
     ↓ Yes
Request User Guidance
     ↓
User Chooses:
     ├─ Provide Guidance → Inject into task, reset count, retry
     ├─ Skip Task → Mark completed, continue
     ├─ Retry → Continue with current approach
     └─ Abort → Stop execution
```

### Signal Types & Scores

| Signal Type | Score | When Detected |
|------------|-------|---------------|
| Repeated Failure | 5 | 3+ identical errors |
| No Progress | 4 | Same error every attempt |
| No Tool Calls | 4 | Agent returning text only |
| Conflicting Signals | 3 | Tests pass but validation fails |
| Multiple Files | 3 | Ambiguous file references |
| Verification Inconclusive | 3 | Cannot determine success/failure |
| Planner Hesitation | 2 | "could try", "not sure" |
| Missing Files | 2 | Referenced files don't exist |
| Timeout Unclear | 2 | Timeout with no diagnosis |
| Circuit Breaker | 10 | Recovery limit exceeded |

---

## Future Enhancements

### Potential Improvements (Not Implemented)

1. **LLM-based uncertainty detection**: Analyze task descriptions with LLM to detect vague requirements
2. **Historical learning**: Track which guidance was successful, suggest similar solutions
3. **Confidence scoring**: Add confidence levels to agent responses
4. **TUI text input**: Enhanced TUI for multi-line guidance entry
5. **Guidance templates**: Pre-built guidance templates for common scenarios

---

## Related Work

This implementation complements existing features:

- **Prompt Optimizer** (already asks user during initial request analysis)
- **Circuit Breakers** (now enhanced with guidance request before abort)
- **Watch Mode Auto-Fix** (automatic fix without asking, works alongside uncertainty detection)
- **Build Optimization** (skips unnecessary builds for test fixes)

---

## Implementation Statistics

- **Lines of Code**: ~650 (detector: 379, guidance: 271)
- **Test Cases**: 11 (all passing)
- **Detection Points**: 9 signal types
- **Integration Points**: 2 (failure retry, circuit breaker)
- **Configuration Options**: 3 environment variables
- **Implementation Time**: ~4 hours

---

## Conclusion

The uncertainty detection system is now fully operational. Rev will ask for user guidance when:

1. **After 2+ failures** with same error (score ≥ 5)
2. **Before circuit breaker** triggers (last resort)

Users can:
- Provide specific guidance (injected into task)
- Skip uncertain tasks
- Retry with current approach
- Abort execution

**Result**: Faster, more transparent, user-controlled execution with fewer wasted retry cycles.

✅ **Implementation Complete**
