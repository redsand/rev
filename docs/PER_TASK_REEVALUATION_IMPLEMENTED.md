# Per-Task Reevaluation Implementation

## Problem

Even with cache invalidation fixes, the system was still executing tasks in **batches** rather than pausing to re-evaluate after each task:

```
Iteration 1:
  ├─ Generate plan with 60+ tasks
  └─ Execute ALL remaining tasks in batch:
      ├─ Task 1: Extract BreakoutAnalyst ✓
      ├─ Task 2: Extract CandlestickAnalyst ✓
      ├─ Task 3: Extract EmaAnalyst ✓
      ├─ ... (execute all 60 tasks without pausing)
      └─ Task 60: DELETE original lib/analysts.py ← DESTRUCTIVE!

  └─ Only AFTER all tasks: Check if goal achieved
      └─ Response: "Need to extract more classes" (they're already gone!)
```

**Root Issue**: Task batch execution never pauses to check if file state changes invalidate remaining tasks.

---

## Solution: Per-Task Reevaluation

After each task completes (not just at end of batch), immediately check:
1. **Was this a destructive operation?**
2. **Do any pending tasks reference the modified files?**
3. **If yes, pause and replan before continuing**

### Implementation Details

#### 1. New Method: `_should_pause_for_task_reevaluation()`

**Location**: `rev/execution/orchestrator.py` lines 617-668

```python
def _should_pause_for_task_reevaluation(self, completed_task: Task, context: RevContext) -> bool:
    """
    Determine if we should pause execution and re-evaluate the plan after this task.

    Returns True if:
    1. Task was destructive (extract, delete, modify, remove)
    2. AND there are pending tasks that reference affected files
    3. AND those pending tasks might need adjustment
    """
    # 1. Check if destructive operation
    is_destructive = any(keyword in task_desc for keyword in [
        "extract", "delete", "remove", "refactor", "modify", "split", "create"
    ])

    if not is_destructive:
        return False

    # 2. Check if pending tasks exist
    pending_tasks = [t for t in context.plan.tasks if t.status == TaskStatus.PENDING]
    if not pending_tasks:
        return False

    # 3. Extract files from completed task
    completed_task_files = set(re.findall(
        r'(?:lib/|src/|tests/)[a-zA-Z0-9_./\-]+\.py',
        completed_task.description
    ))

    # 4. Check if any pending task references these files
    for pending_task in pending_tasks:
        pending_task_files = set(re.findall(...))

        # Overlap = conflict = need to replan
        if completed_task_files & pending_task_files:
            return True

    return False
```

**Logic**:
- Extracts file paths using regex from task descriptions
- Checks for overlap between completed task files and pending task files
- If overlap exists, pausing is needed to replan

---

#### 2. Integration into Task Execution Loop

**Location**: `rev/execution/orchestrator.py` lines 571-589

After each task completes successfully:

```python
else:
    # Normal success
    task.status = TaskStatus.COMPLETED
    print(f"  ✓ Task {task.task_id} completed successfully")

    # CRITICAL: Per-task evaluation
    if self._should_pause_for_task_reevaluation(task, context):
        print(f"\n  ⚠️  Task {task.task_id} changed file state. Pausing for plan re-evaluation...")
        context.update_repo_context()
        clear_analysis_caches()

        # Signal caller to exit dispatch loop and replan
        context.agent_requests.append({
            "type": "replan_immediately",
            "reason": f"File state changed after task {task.task_id}",
            "completed_task": task.task_id
        })

        # Return early - stop executing remaining tasks
        print(f"  → Stopping task batch execution to replan based on new file state")
        return overall_success
```

**Effect**:
- After task completes, check if replan needed
- If yes, stop executing remaining tasks in batch
- Return control to orchestrator with replan signal
- Orchestrator handles replan request

---

#### 3. Orchestrator Handles Replan Signal

**Location**: `rev/execution/orchestrator.py` lines 799-809

```python
# CHECK 1: Per-task reevaluation request (task detected state change mid-execution)
should_replan_immediately = False
for request in self.context.agent_requests:
    if request.get("type") == "replan_immediately":
        should_replan_immediately = True
        print(f"\n  ⚠️  Per-task reevaluation triggered: {request.get('reason')}")
        break

# CHECK 2: Immediate replan after destructive operation
if should_replan_immediately or self._check_for_immediate_replan_after_destructive_task(...):
    print(f"  → Triggering immediate replan due to destructive operation...")
    # Regenerate follow-up plan based on new file state
    followup_plan = self._regenerate_followup_plan(...)
```

**Effect**:
- Orchestrator detects replan signal
- Triggers immediate replanning
- Gets fresh plan based on current file state
- Replaces old pending tasks with newly planned tasks

---

## Execution Flow with Per-Task Reevaluation

### Before (Batch Execution)
```
Iteration 1:
  ├─ Plan: [Extract Breakout, Extract Candlestick, ... Extract VolumeAnalyst, DELETE original lib/analysts.py]
  └─ Execute batch:
      ├─ Task 1: Extract Breakout ✓
      ├─ Task 2: Extract Candlestick ✓
      ├─ Task 3: Extract Ema ✓
      ├─ ... (keeps going without pause)
      └─ Task 60: DELETE lib/analysts.py ✓ (DESTRUCTIVE! File needed by pending tasks!)

  └─ Check goal: "Still need to extract VolumeAnalyst" (IT'S ALREADY DELETED!)
  └─ Regenerate same plan (loop!)
```

### After (Per-Task Reevaluation)
```
Iteration 1:
  ├─ Plan: [Extract Breakout, Extract Candlestick, ..., DELETE original lib/analysts.py]
  └─ Execute with evaluation:
      ├─ Task 1: Extract Breakout ✓
      ├─ PAUSE: Check file state
      │  ├─ Completed task touched: lib/analysts.py
      │  ├─ Pending tasks check: Do they reference lib/analysts.py?
      │  ├─ Result: Yes! "Extract VolumeAnalyst from lib/analysts.py"
      │  └─ ACTION: Stop batch, replan
      │
      ├─ Replan based on new state:
      │  ├─ BreakoutAnalyst successfully extracted
      │  ├─ lib/analysts.py still has other classes
      │  ├─ Generate: [Extract Candlestick, Extract Ema, ..., then DELETE]
      │  └─ New plan doesn't extract VolumeAnalyst yet
      │
      └─ Continue with new plan:
          ├─ Task: Extract Candlestick ✓
          ├─ PAUSE: Check file state
          │  └─ Do pending tasks need lib/analysts.py? Yes!
          │  └─ Replan...
          │
          └─ Continue iteratively...

Iteration N:
  └─ Final tasks: [Update imports, Run tests, DELETE lib/analysts.py (now safe!)]
```

---

## Key Differences

| Aspect | Before | After |
|--------|--------|-------|
| **Execution** | Batch execution, no pauses | Per-task with evaluation |
| **Destructive ops** | All executed, then replan | Paused before destructive |
| **Replanning trigger** | End of batch | After each task if file state changes |
| **File visibility** | Updated once per batch | Updated before each replan |
| **Cache clearing** | After batch completes | After task detects conflict |
| **Plan updates** | Wholesale replacement | Incremental with current progress |

---

## Files Modified

### rev/execution/orchestrator.py

**Addition 1**: New method `_should_pause_for_task_reevaluation()` (lines 617-668)
- Detects if task made changes affecting pending tasks
- Uses regex to extract file paths from task descriptions
- Returns True if replan needed

**Addition 2**: Per-task evaluation in dispatch loop (lines 576-589)
- After each task completes, call `_should_pause_for_task_reevaluation()`
- If True, add replan request to context
- Return early from dispatch to stop batch execution

**Addition 3**: Handle replan signal in main loop (lines 799-839)
- Check for `replan_immediately` requests
- Trigger immediate replanning
- Clear agent requests after handling

---

## Example Scenario: Splitting 10 Analyst Classes

### Plan Before
```
Task 1: Extract BreakoutAnalyst
Task 2: Extract CandlestickAnalyst
...
Task 15: Extract VolumeAnalyst
Task 16: Update lib/analysts/__init__.py with imports
Task 17: Remove analyst definitions from lib/analysts.py
Task 18: Run tests to verify split
...
Task 60+: Additional refinements
```

### Execution Before (Batch)
```
Iteration 1:
  Execute all 60 tasks at once
  → All classes extracted, but original file not removed (not reached yet)
  → Replanning sees original file still exists
  → Regenerates same plan
```

### Execution After (Per-Task)
```
Iteration 1:
  Task 1: Extract BreakoutAnalyst ✓
  ├─ Check: Does pending task need BreakoutAnalyst or lib/analysts.py?
  ├─ Finds: Task 2 needs "Extract CandlestickAnalyst from lib/analysts.py"
  └─ Replan IMMEDIATELY

Iteration 1.5 (Replanning):
  New Plan:
    Task 2: Extract CandlestickAnalyst ✓
    Task 3: Extract EmaAnalyst ✓
    ... (Extract all remaining)
    Task 15: Update imports
    Task 16: Remove original file (now safe - all extracted!)
    Task 17: Run tests ✓

Iteration 2:
  All tasks complete, goal achieved
  (No looping or regeneration)
```

---

## Benefits

1. **✅ Prevents Destructive Operations on Source Files**
   - Won't delete original file before dependent extractions complete

2. **✅ Adapts Plan to Actual File State**
   - After each task, knows what's been completed
   - Generates tasks appropriate to current state

3. **✅ Eliminates Task Regeneration Loops**
   - Won't regenerate same plan repeatedly
   - Makes incremental progress

4. **✅ Catches Unexpected File Changes**
   - If task output differs from expected, replan catches it
   - System adapts to actual results

5. **✅ More Efficient Execution**
   - Doesn't execute unnecessary tasks
   - Stops when goal is achieved

---

## Edge Cases Handled

### Case 1: File Not Modified
```
Task: Add comment to file
  ├─ File modified (but not destructively)
  ├─ Check: Do pending tasks read this file?
  ├─ Conclusion: If yes, replan; if no, continue
  └─ Adaptive behavior
```

### Case 2: Multiple Files Modified
```
Task: Refactor X, Y, Z
  ├─ Modified files: {X, Y, Z}
  ├─ Check: Any pending task references {X, Y, Z}?
  ├─ Conclusion: Yes → Replan; No → Continue
  └─ Handles multi-file operations
```

### Case 3: No Pending Tasks
```
Task: Delete temporary file
  ├─ No pending tasks remain
  ├─ Conclusion: No replan needed
  └─ Allows safe cleanup at end
```

### Case 4: Pending Tasks Don't Reference Modified Files
```
Task: Update lib/utils.py
Pending Task: Add feature to lib/api.py
  ├─ Modified files: {lib/utils.py}
  ├─ Pending files: {lib/api.py}
  ├─ Overlap: None
  └─ Continue execution (no replan needed)
```

---

## Testing Verification

To verify per-task reevaluation works:

```
1. Create test task: "Extract 5 classes from lib/analysts.py"
2. Observe execution:
   ✓ Extract first class
   ✓ PAUSE for re-evaluation
   ✓ Detect remaining classes still need original file
   ✓ Replan
   ✓ Continue with updated plan
   ✓ NO task batch execution
   ✓ NO regeneration of same plan
   ✓ Iterative completion

3. Verify logs show:
   - "Pausing for plan re-evaluation..."
   - "Per-task reevaluation triggered"
   - "Plan updated with X new task(s)"
```

---

## Architecture Summary

```
Orchestrator Loop:
  ├─ Plan generation
  ├─ Task execution with per-task evaluation
  │  ├─ Execute task
  │  ├─ Check: Did file state change dangerously?
  │  ├─ If yes:
  │  │  ├─ Update repo context
  │  │  ├─ Clear analysis caches
  │  │  ├─ Signal replan
  │  │  └─ Stop batch execution
  │  └─ If no: Continue to next task
  │
  ├─ Handle replan signal
  │  ├─ Regenerate plan with fresh file state
  │  ├─ Replace pending tasks
  │  └─ Continue execution
  │
  └─ Repeat until goal achieved
```

---

## Summary

This implementation adds **true per-task reevaluation** by:

1. ✅ Detecting when tasks make changes (destructive operations)
2. ✅ Checking if pending tasks reference modified files
3. ✅ Pausing execution if conflict detected
4. ✅ Replanning based on actual file state
5. ✅ Continuing with updated plan

The system now **adapts after each task** rather than blindly executing batches, enabling proper incremental progress toward completion.
