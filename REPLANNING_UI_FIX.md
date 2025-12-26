# Replanning UI Improvements - Make It Look Normal

**Date**: 2025-12-25
**Issue**: Replanning looks scary and ugly, like an error or warning
**Goal**: Make replanning look like a normal, expected part of the workflow

---

## Problem

Replanning is a **normal, adaptive behavior** in REV - it's how the system learns and adjusts. But the UI made it look like something went wrong:

### Before (Scary and Ugly)

**1. Adaptive Replan Message**:
```
🔄 Adaptive Replan Triggered: Similar files exist
```
- 🔄 Emoji looks like a warning
- BRIGHT_YELLOW color (warning color)
- Word "Triggered" sounds like an alarm

**2. Verification Failure Message**:
```
======================================================================
NEXT ACTION: Re-planning with different approach...
======================================================================
```
- Equals bars look like an error box
- "Re-planning with different approach" sounds like failure
- Implies the previous approach was wrong

**3. Retry Message**:
```
[RETRY] Using decomposed task for next iteration
```
- Square brackets look like errors
- Word "RETRY" implies failure

**4. Orchestrator Message**:
```
🔄 Orchestrator retry 2/5
```
- Emoji looks like warning
- Word "retry" implies failure

---

## The Fix

Made replanning messages look like normal orchestrator steps using consistent formatting.

### After (Normal and Expected)

**1. Adaptive Replan** (line 3235):
```
◆ Refining strategy: Similar files exist
```
- ◆ symbol matches orchestrator style
- BRIGHT_CYAN color (same as other steps)
- "Refining strategy" sounds iterative, not broken

**2. Verification Feedback** (line 3299):
```
======================================================================
NEXT ACTION: Adjusting approach based on feedback...
======================================================================
```
- Still uses equals bars (for visibility)
- "Adjusting approach based on feedback" sounds adaptive
- Implies learning, not failure

**3. Decomposition** (line 3098):
```
◆ Breaking down into smaller steps
```
- ◆ symbol consistent
- BRIGHT_CYAN color
- Positive framing - sounds methodical, not failed

**4. Orchestrator Iteration** (line 1675):
```
◆ Orchestrator iteration 2/5
```
- ◆ symbol consistent
- "iteration" instead of "retry"
- Neutral, expected progression

---

## Changes Made

**File**: `rev/execution/orchestrator.py`

### Change 1: Adaptive Replan (lines 3233-3236)

**Before**:
```python
print(f"\n  🔄 {colorize('Adaptive Replan Triggered', Colors.BRIGHT_YELLOW)}: {replan_req['details'].get('reason')}")
```

**After**:
```python
# Make replanning look like a normal step, not an error
reason = replan_req['details'].get('reason', 'Refining approach')
print(f"\n  {colorize('◆', Colors.BRIGHT_CYAN)} {colorize('Refining strategy', Colors.WHITE)}: {reason}")
```

**Why better**:
- Uses orchestrator symbol ◆ instead of emoji 🔄
- BRIGHT_CYAN instead of BRIGHT_YELLOW (warning color)
- "Refining strategy" instead of "Triggered"

### Change 2: Verification Failure Message (line 3299)

**Before**:
```python
print("NEXT ACTION: Re-planning with different approach...")
```

**After**:
```python
print("NEXT ACTION: Adjusting approach based on feedback...")
```

**Why better**:
- "Adjusting" sounds iterative, not broken
- "based on feedback" implies learning
- Removes negative connotation of "different"

### Change 3: Task Decomposition (line 3098)

**Before**:
```python
print(f"  [RETRY] Using decomposed task for next iteration")
```

**After**:
```python
print(f"  {colorize('◆', Colors.BRIGHT_CYAN)} {colorize('Breaking down into smaller steps', Colors.WHITE)}")
```

**Why better**:
- Removes [RETRY] bracket notation (looks like error)
- Uses consistent ◆ symbol
- "Breaking down" sounds methodical, not failed

### Change 4: Orchestrator Iteration (line 1675)

**Before**:
```python
print(f"\n\n🔄 Orchestrator retry {attempt}/{self.config.orchestrator_retries}")
```

**After**:
```python
print(f"\n\n{colorize('◆', Colors.BRIGHT_CYAN)} {colorize(f'Orchestrator iteration {attempt}/{self.config.orchestrator_retries}', Colors.WHITE)}")
```

**Why better**:
- Removes emoji
- "iteration" instead of "retry"
- Consistent with other orchestrator messages

---

## Visual Comparison

### Before (Looks Like Errors)
```
✓ [COMPLETED] Read package.json
✗ [FAILED] Create tests/user_auth.test.js

======================================================================
NEXT ACTION: Re-planning with different approach...
======================================================================

🔄 Adaptive Replan Triggered: Similar files exist

[RETRY] Using decomposed task for next iteration
```

### After (Looks Like Normal Flow)
```
✓ [COMPLETED] Read package.json
✗ [FAILED] Create tests/user_auth.test.js

======================================================================
NEXT ACTION: Adjusting approach based on feedback...
======================================================================

  ◆ Refining strategy: Similar files exist

  ◆ Breaking down into smaller steps
```

---

## Philosophy

**Replanning is not failure - it's adaptation.**

In TDD and agile development:
- Red → Green → Refactor is **normal**
- Adjusting based on feedback is **expected**
- Iterative refinement is **the process**

The UI should reflect this. Replanning should look like:
- ✅ A natural part of the workflow
- ✅ Adaptive intelligence at work
- ✅ The system learning and improving

Not like:
- ❌ Something went wrong
- ❌ An error occurred
- ❌ A failure happened

---

## User Experience

### Before
User sees warnings and errors:
- 🔄 emoji (looks like something's spinning/broken)
- YELLOW text (warnings)
- Words like "RETRY", "Re-planning", "Triggered"
- **Reaction**: "Is something broken? Should I be worried?"

### After
User sees normal progression:
- ◆ symbol (matches other orchestrator steps)
- CYAN text (same as other steps)
- Words like "Refining", "Adjusting", "Breaking down"
- **Reaction**: "The system is thinking and adapting. Good."

---

## Edge Cases

### Case 1: Multiple Replans

**Before**: Looks increasingly scary
```
🔄 Adaptive Replan Triggered: Similar files exist
🔄 Adaptive Replan Triggered: File not found
🔄 Adaptive Replan Triggered: Tests failed
```

**After**: Looks like iterative refinement
```
◆ Refining strategy: Similar files exist
◆ Refining strategy: File not found
◆ Refining strategy: Tests failed
```

### Case 2: Circuit Breaker

Circuit breaker messages stay **intentionally bold and red** because they represent actual stopping conditions:
```
✗ Circuit Breaker: repeated failure 3x. Stopping loop.
```

This is correct - circuit breaker is a true error condition, not normal flow.

---

## Testing

Run REV and observe replanning scenarios:

### Test 1: Duplicate File Detection
```bash
# Create similar file
rev "create tests/user_auth.test.js"

# Expected output (should look normal, not scary):
◆ Refining strategy: Similar files exist
```

### Test 2: Task Decomposition
```bash
# Complex task that gets decomposed
rev "add complete authentication system"

# Expected output:
◆ Breaking down into smaller steps
```

### Test 3: Orchestrator Iteration
```bash
# Task that requires multiple attempts
rev "fix all linting errors"

# Expected output:
◆ Orchestrator iteration 2/5
```

---

## Summary

**Changed**: 4 replan-related messages in `orchestrator.py`

**Result**: Replanning looks like normal, expected adaptive behavior instead of errors

**User benefit**: Less anxiety, clearer understanding that the system is working correctly

**Philosophy**: "Replanning is adaptation, not failure"

---

## Rollback

If this causes confusion, revert by:
```bash
git checkout rev/execution/orchestrator.py
```

Original scary messages used:
- 🔄 emoji
- BRIGHT_YELLOW color
- Words: "Triggered", "RETRY", "retry", "Re-planning"
