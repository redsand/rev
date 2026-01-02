# Uncertainty Detection & User Guidance Proposal

## Problem Statement

**Rev never asks questions or seeks guidance**, even when:
- Tasks fail repeatedly (3+ times with same error)
- Multiple valid approaches exist (different frameworks, architectural choices)
- Critical information is missing (files don't exist, unclear requirements)
- Conflicting signals detected (error says A, but context suggests B)

This leads to:
- ❌ Wasted time on wrong approaches
- ❌ Unnecessary retries with low confidence
- ❌ Silent failures without user awareness
- ❌ Assumptions that may not match user intent

## Existing Mechanisms

### 1. Prompt Optimizer (DOES ask user)
**File**: `rev/execution/prompt_optimizer.py:290-414`

**When**: Initial user request is vague/unclear
**How**: Analyzes request, shows suggestions, asks user to choose:
```
[1] Use the suggested improvement
[2] Keep the original request
[3] Enter a custom request
```

**Status**: ✅ Already implemented and working

### 2. Adaptive Prompt Optimizer (does NOT ask user)
**File**: `rev/execution/adaptive_prompt_optimizer.py`

**When**: Agent fails repeatedly
**How**: Automatically improves agent prompts, NO user interaction

### 3. Circuit Breakers (does NOT ask user)
**When**: Tool execution failures (3+ times), excessive retries
**How**: Stops execution, prints error, exits

**Missing**: No user guidance request before giving up

---

## Proposed Solution: Uncertainty Detection System

### Core Concept

Add **confidence tracking** throughout execution and **prompt user for guidance** when confidence drops below threshold.

### Detection Points

#### 1. Task Planning Phase (orchestrator.py)
**Detect**:
- Planner LLM hesitates: "could", "might", "possibly", "not sure"
- Multiple valid action types (EDIT vs REFACTOR vs CREATE)
- Ambiguous file references (multiple matches)
- Missing context (required files don't exist)

**Example**:
```python
def _detect_planning_uncertainty(llm_response: str, task: Task) -> Optional[str]:
    """Detect if planner is uncertain about approach."""
    uncertainty_markers = [
        "could try", "might work", "possibly", "not sure",
        "unclear", "ambiguous", "multiple ways", "depends on"
    ]

    response_lower = llm_response.lower()
    if any(marker in response_lower for marker in uncertainty_markers):
        return "Planner expressed uncertainty about approach"

    # Check for multiple file matches
    if task.action_type == "EDIT":
        files = _extract_target_files_from_description(task.description)
        if len(files) > 1:
            return f"Multiple potential target files: {files}"

    return None
```

#### 2. Task Execution Phase (executor.py)
**Detect**:
- Same task fails 3+ times with same error
- Agent makes no progress (no tool calls, text-only responses)
- Conflicting tool results (file exists check fails, then succeeds)

**Example**:
```python
def _detect_execution_uncertainty(task: Task, retry_count: int, last_error: str) -> Optional[str]:
    """Detect if execution is stuck or uncertain."""

    # Repeated failures with identical error
    if retry_count >= 3:
        return f"Task failed {retry_count} times with same error: {last_error[:100]}"

    # No tool calls (LLM returning text instead)
    if task.tool_calls_made == 0 and retry_count > 0:
        return "Agent not executing tools, only returning text"

    return None
```

#### 3. Verification Phase (quick_verify.py)
**Detect**:
- Tests pass but linter shows unrelated errors
- Verification inconclusive (can't determine success/failure)
- Timeout with unclear cause

**Example**:
```python
def _detect_verification_uncertainty(result: VerificationResult) -> Optional[str]:
    """Detect if verification result is inconclusive."""

    if result.inconclusive:
        return "Verification inconclusive - cannot determine if task succeeded"

    # Tests pass but other validations fail
    if result.passed and result.details.get("warnings"):
        warnings = result.details["warnings"]
        if "unrelated" in str(warnings).lower():
            return "Tests pass but unrelated warnings detected"

    return None
```

---

## User Guidance Dialog

### When to Trigger

**Threshold**: Cumulative uncertainty score ≥ 5

| Uncertainty Type | Score |
|-----------------|-------|
| Planner hesitation | 2 |
| Multiple file matches | 3 |
| 3+ identical failures | 5 |
| No tool calls | 4 |
| Verification inconclusive | 3 |
| Missing files | 2 |
| Timeout unclear | 2 |

### Dialog Format

```python
def request_user_guidance(
    uncertainty_reason: str,
    task: Task,
    context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Request guidance from user when uncertain.

    Returns:
        {
            "action": "retry" | "skip" | "modify" | "abort",
            "guidance": str  # User's specific guidance
        }
    """
    print(f"\n{colorize('🤔 Rev is uncertain and needs guidance:', Colors.BRIGHT_YELLOW, bold=True)}")
    print(f"   {uncertainty_reason}\n")

    # Show context
    print(f"   Task: {task.description[:80]}")
    if task.error:
        print(f"   Last Error: {task.error[:100]}")

    # Provide options
    print(f"\n{colorize('[Options]', Colors.BRIGHT_CYAN)}")
    print("  [1] Provide specific guidance (describe what to do)")
    print("  [2] Skip this task and continue")
    print("  [3] Retry with current approach")
    print("  [4] Abort execution")

    # TUI support
    from rev.terminal.tui import get_active_tui
    tui = get_active_tui()

    if tui is not None:
        options = [
            "[1] Provide guidance",
            "[2] Skip task",
            "[3] Retry",
            "[4] Abort"
        ]
        selected = tui.show_menu("Rev needs guidance - Choose an option:", options)

        if selected == 0:  # Provide guidance
            # Get user input
            guidance = tui.get_text_input("What should Rev do? (be specific):")
            if guidance:
                return {"action": "retry", "guidance": guidance}
        elif selected == 1:  # Skip
            return {"action": "skip", "guidance": "User chose to skip"}
        elif selected == 2:  # Retry
            return {"action": "retry", "guidance": None}
        else:  # Abort
            return {"action": "abort", "guidance": "User aborted"}
    else:
        # Terminal fallback
        choice = input("\nChoice [1-4]: ").strip()

        if choice == "1":
            guidance = input("What should Rev do? (be specific): ").strip()
            if guidance:
                return {"action": "retry", "guidance": guidance}
        elif choice == "2":
            return {"action": "skip", "guidance": "User chose to skip"}
        elif choice == "3":
            return {"action": "retry", "guidance": None}
        elif choice == "4":
            return {"action": "abort", "guidance": "User aborted"}

    return None
```

---

## Integration Points

### 1. Orchestrator Integration

**File**: `rev/execution/orchestrator.py`

```python
def execute_task(self, task: Task) -> Tuple[Task, bool]:
    """Execute a task with uncertainty detection."""

    retry_count = 0
    max_retries = 5
    uncertainty_score = 0

    while retry_count < max_retries:
        # Execute task
        result = self._execute_single_attempt(task)

        # Detect uncertainty
        uncertainty_reasons = []

        # Check planning uncertainty
        if retry_count == 0:
            planning_uncertainty = _detect_planning_uncertainty(task.description, task)
            if planning_uncertainty:
                uncertainty_reasons.append(planning_uncertainty)
                uncertainty_score += 2

        # Check execution uncertainty
        exec_uncertainty = _detect_execution_uncertainty(task, retry_count, task.error or "")
        if exec_uncertainty:
            uncertainty_reasons.append(exec_uncertainty)
            if retry_count >= 3:
                uncertainty_score += 5
            else:
                uncertainty_score += 2

        # Request guidance if uncertain
        if uncertainty_score >= 5:
            guidance_response = request_user_guidance(
                "\n".join(uncertainty_reasons),
                task,
                {"retry_count": retry_count}
            )

            if guidance_response:
                if guidance_response["action"] == "abort":
                    return task, False
                elif guidance_response["action"] == "skip":
                    task.status = "skipped"
                    return task, True
                elif guidance_response["action"] == "modify":
                    # Inject user guidance into task
                    task.description += f"\n\nUser Guidance: {guidance_response['guidance']}"
                    uncertainty_score = 0  # Reset after guidance

        # Continue with retry or success
        if result.success:
            return task, True

        retry_count += 1

    return task, False
```

### 2. Circuit Breaker Enhancement

**Before abandoning**, ask user:

```python
def _handle_circuit_breaker(reason: str, task: Task):
    """Handle circuit breaker with user guidance option."""

    print(f"\n{colorize('🛑 CIRCUIT BREAKER: ' + reason, Colors.BRIGHT_RED, bold=True)}")

    # Ask if user wants to intervene
    guidance = request_user_guidance(
        f"Circuit breaker triggered: {reason}",
        task,
        {"circuit_breaker": True}
    )

    if guidance and guidance["action"] == "retry" and guidance["guidance"]:
        # User provided specific guidance - try once more with it
        task.description += f"\n\nUser Override: {guidance['guidance']}"
        return _attempt_with_guidance(task, guidance["guidance"])

    # Otherwise, abort as before
    raise CircuitBreakerException(reason)
```

---

## Real-World Examples

### Example 1: Framework Choice Ambiguity

**Scenario**: Task mentions testing but doesn't specify Vitest vs Jest

**Detection**:
```python
Task: "add tests for user authentication"
Planning: "Could use Vitest or Jest, both are valid..."
Uncertainty Score: 2 (hesitation marker)
```

**Guidance Request**:
```
🤔 Rev is uncertain and needs guidance:
   Planner expressed uncertainty about approach

   Task: add tests for user authentication

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 1
What should Rev do? Use Vitest - it's already configured in this project
```

**Result**: Task updated with "User Guidance: Use Vitest - it's already configured"

### Example 2: Repeated Test Failures

**Scenario**: Test command fails 3 times with same error

**Detection**:
```python
Task: "run tests for auth module"
Attempts:
  1. npm test → timeout
  2. npm test → timeout
  3. npm test → timeout
Uncertainty Score: 5 (3+ identical failures)
```

**Guidance Request**:
```
🤔 Rev is uncertain and needs guidance:
   Task failed 3 times with same error: command exceeded 600s timeout

   Task: run tests for auth module
   Last Error: command exceeded 600s timeout

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 1
What should Rev do? Run npx vitest run tests/auth.test.ts instead of npm test
```

**Result**: Task retries with specific command

### Example 3: File Not Found

**Scenario**: Task references file that doesn't exist

**Detection**:
```python
Task: "update src/utils/helper.ts to add function"
Planning: Extracted file: src/utils/helper.ts
File check: Does not exist
Uncertainty Score: 2 (missing file)

After 2 retries still failing...
Uncertainty Score: 5 (threshold reached)
```

**Guidance Request**:
```
🤔 Rev is uncertain and needs guidance:
   Multiple file matches or missing files

   Task: update src/utils/helper.ts to add function

[Options]
  [1] Provide specific guidance
  [2] Skip this task
  [3] Retry with current approach
  [4] Abort

Choice [1-4]: 1
What should Rev do? The file is actually at src/lib/helpers.ts, use that instead
```

**Result**: Task updated to use correct file path

---

## Configuration

### Settings

**File**: `rev/config.py` or `.revconfig`

```python
UNCERTAINTY_DETECTION = {
    "enabled": True,  # Enable/disable feature
    "threshold": 5,    # Score threshold to trigger guidance
    "auto_skip_threshold": 10,  # Auto-skip if score exceeds this
    "interactive": True,  # False = auto-skip uncertain tasks
}

UNCERTAINTY_WEIGHTS = {
    "planner_hesitation": 2,
    "multiple_files": 3,
    "repeated_failure": 5,
    "no_tool_calls": 4,
    "verification_inconclusive": 3,
    "missing_files": 2,
    "timeout_unclear": 2,
}
```

---

## Benefits

### Before (Current State):
- ❌ Rev retries blindly until circuit breaker
- ❌ User unaware of uncertainty
- ❌ Wasted time on low-confidence approaches
- ❌ Silent assumptions that may be wrong

### After (With Uncertainty Detection):
- ✅ Rev asks when uncertain, doesn't waste time
- ✅ User provides specific guidance
- ✅ Faster resolution with correct information
- ✅ Transparent about confidence level
- ✅ User stays in control

---

## Implementation Plan

### Phase 1: Detection Framework (1-2 days)
1. Create `rev/execution/uncertainty_detector.py`
2. Implement detection functions
3. Add scoring system
4. Unit tests for detection logic

### Phase 2: Guidance Dialog (1 day)
1. Create `request_user_guidance()` function
2. TUI integration
3. Terminal fallback
4. Test dialog flow

### Phase 3: Orchestrator Integration (2-3 days)
1. Add uncertainty tracking to task execution
2. Integrate guidance requests
3. Update circuit breaker to ask before aborting
4. Test with real scenarios

### Phase 4: Configuration & Docs (1 day)
1. Add settings to config
2. Document usage
3. Add examples

**Total Estimate**: 5-7 days

---

## Testing Strategy

### Unit Tests
- `test_uncertainty_detection.py` - Detection logic
- `test_guidance_dialog.py` - Dialog interactions

### Integration Tests
- `test_orchestrator_uncertainty.py` - End-to-end flow
- `test_circuit_breaker_guidance.py` - Circuit breaker enhancement

### Manual Testing Scenarios
1. Task with ambiguous file reference
2. Repeated test failures
3. Missing dependencies
4. Framework choice ambiguity

---

## Alternatives Considered

### 1. Always Ask for Confirmation
**Pros**: Maximum user control
**Cons**: Too intrusive, slows down workflow
**Decision**: ❌ Rejected - only ask when uncertain

### 2. Never Ask (Full Automation)
**Pros**: Fastest execution
**Cons**: Wastes time on wrong approaches
**Decision**: ❌ Rejected - current state, not working well

### 3. Ask After N Failures
**Pros**: Simple threshold
**Cons**: Doesn't detect uncertainty early
**Decision**: ✅ Partial - included as one detection point

### 4. Uncertainty Score System (Proposed)
**Pros**: Flexible, catches multiple signals, asks at right time
**Cons**: More complex to implement
**Decision**: ✅ **Selected** - best balance

---

## Summary

**Problem**: Rev never asks for guidance, even when uncertain
**Solution**: Uncertainty detection system with user guidance dialogs
**Key Features**:
- Multi-point detection (planning, execution, verification)
- Scoring system (threshold: 5)
- User-friendly dialogs with TUI support
- Configurable thresholds
- Graceful degradation

**Result**: Rev asks for help when needed, not blindly retrying ✅
