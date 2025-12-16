# Per-Task Replanning Implementation Plan

## Problem

Current execution model uses **batch replanning**:
```
Create plan with all tasks upfront
  ↓
Execute Task 1, 2, 3, 4, ... (all in one batch)
  ↓
After batch completes, replan if needed
```

**Issue with batch approach:**
- If Task 1 modifies lib/analysts.py, Tasks 2-4 don't know that until after they execute
- Destructive operations break subsequent tasks because plan doesn't adapt
- System learns new information but doesn't use it until after batch completes
- Inefficient - might execute unnecessary tasks

## Solution: Per-Task Replanning

Execute one task at a time and replan after each completion:

```
Plan: [Task 1]
  ↓
Execute Task 1 → COMPLETED ✓
  ↓
Learn: lib/analysts.py was modified, BreakoutAnalyst extracted
  ↓
Replan: "Given what just happened, what's next?"
  Plan: [Task 2, Task 3, ...]
  ↓
Execute Task 2 → COMPLETED ✓
  ↓
Learn: new state
  ↓
Replan: "What's next?"
  ↓
Continue...
```

## Benefits

### 1. Prevents Destructive Operations Breaking Tasks
```
Task 1: Extract BreakoutAnalyst from lib/analysts.py
        ✓ COMPLETED - lib/analysts.py modified
        ↓
        Replan checks: "What's still in lib/analysts.py?"
        ↓
Task 2: Extract VolumeAnalyst (if still exists)
        or Skip (if already extracted)
```

### 2. Adapts to Unexpected Results
```
Task 1: Create authentication system
        ✓ COMPLETED - but simpler than planned
        ↓
        Replan: "Do we still need the separate token service?"
        ↓
Task 2: Skipped (no longer needed) OR Modified (different approach)
```

### 3. More Efficient
```
Without per-task replanning:
  - Execute all 5 tasks (~5-10 min)
  - Replan, find 3 still needed
  - Execute 3 more tasks

With per-task replanning:
  - Execute Task 1 (~1 min)
  - Replan: realize only Task 2 is needed
  - Execute Task 2 (~1 min)
  - Goal achieved - done!
```

## Implementation Approach

### Current Code Structure
**Location:** `rev/execution/orchestrator.py`

**Current method:** `_dispatch_to_sub_agents(context)` (lines 487-595)
- Loops through ALL tasks at once
- Executes them in sequence
- Returns overall success/failure

**Current replanning:** After `_dispatch_to_sub_agents()` completes (line 725)

### Changes Needed

#### 1. Modify `_dispatch_to_sub_agents()` for Per-Task Execution

Instead of:
```python
def _dispatch_to_sub_agents(context):
    for task in agent_tasks:  # ALL tasks at once
        result = agent.execute(task, context)
        task.status = COMPLETED/FAILED
    return overall_success
```

Change to:
```python
def _dispatch_to_sub_agents_one_task(context):
    """Execute ONE task and return task that was executed."""
    for task in agent_tasks:
        if task.status == PENDING:
            result = agent.execute(task, context)
            task.status = COMPLETED/FAILED
            return task, result  # Return after ONE task
    return None, None
```

#### 2. Modify Main Execution Loop to Replan After Each Task

Instead of:
```python
while iteration < max_iterations:
    # Execute ALL tasks in plan
    self._dispatch_to_sub_agents(self.context)

    # THEN check if replan needed
    if goals_not_met:
        followup_plan = self._regenerate_followup_plan(...)
```

Change to:
```python
while iteration < max_iterations:
    # Execute ONE task
    task, result = self._dispatch_to_sub_agents_one_task(self.context)

    if task is None:
        # No more pending tasks in current plan
        # Check if goal achieved
        if goal_achieved():
            return True

        # Replan for remaining work
        followup_plan = self._regenerate_followup_plan(...)
        if followup_plan and followup_plan.tasks:
            # Add new tasks to plan
            self.context.plan.tasks.extend(followup_plan.tasks)
        else:
            # No more tasks needed
            return True

    # After each task, can optionally check if early replan needed
    # (if destructive operation detected, replan immediately)
    if task.status == COMPLETED:
        if self._should_replan_after_task(task):
            followup_plan = self._regenerate_followup_plan(...)
            if followup_plan:
                self.context.plan.tasks.extend(followup_plan.tasks)
```

#### 3. Add Destructive Operation Detection

```python
def _should_replan_after_task(task: Task) -> bool:
    """
    Determine if we should replan immediately after task completion.

    Return True if:
    - Task was destructive (extract, refactor, delete)
    - AND there are subsequent pending tasks
    - AND they might be affected by this task
    """
    if task.status != TaskStatus.COMPLETED:
        return False

    # Check if task was destructive
    if not any(word in task.description.lower()
               for word in ["extract", "refactor", "delete", "modify"]):
        return False

    # Check if there are pending tasks that might be affected
    remaining_tasks = [t for t in context.plan.tasks
                      if t.status == TaskStatus.PENDING]

    if not remaining_tasks:
        return False

    # Check if any remaining task mentions same files
    modified_files = extract_files_from_description(task.description)
    for remaining_task in remaining_tasks:
        remaining_files = extract_files_from_description(remaining_task.description)
        if any(f in remaining_files for f in modified_files):
            return True  # Potential conflict

    return False
```

## Implementation Steps

### Step 1: Refactor Task Execution
Modify `_dispatch_to_sub_agents()` to execute one task at a time:
- Location: `rev/execution/orchestrator.py` lines 487-595
- Change loop to return after first PENDING task
- Return task and result for caller to handle

### Step 2: Add Replan Decision Logic
Add `_should_replan_after_task()` method:
- Detect destructive operations
- Check for pending dependent tasks
- Trigger immediate replan if needed

### Step 3: Update Main Loop
Modify lines 651-749 to:
- Execute one task per iteration (not all)
- Check for immediate replan needs
- Update plan with follow-up tasks
- Continue until goal achieved

### Step 4: Test
Create comprehensive tests:
- Per-task execution order
- Replanning after destructive ops
- Plan updates during execution
- Goal detection still works

## Pseudo-Code Example

```python
def execute_with_per_task_replanning(user_request):
    # Initial planning
    plan = create_initial_plan(user_request)

    while True:
        # Find next pending task
        task = find_pending_task(plan)

        if task is None:
            # All tasks in current plan completed
            if goal_achieved():
                return True  # Done!

            # Need more tasks, replan
            new_tasks = replan(plan, user_request)
            if not new_tasks:
                return True  # No more tasks needed

            plan.tasks.extend(new_tasks)
            continue

        # Execute ONE task
        result = agent.execute(task)
        task.status = COMPLETED

        # Check if we should replan immediately
        if is_destructive_operation(task):
            new_tasks = replan(plan, user_request)
            if new_tasks:
                # Replace remaining tasks with new plan
                plan.tasks = get_completed(plan) + new_tasks
```

## Benefits Summary

✅ **Prevents Destructive Operations Breaking Tasks**
- Replan after each task knows actual file state
- Can skip or modify subsequent tasks based on actual results

✅ **More Intelligent Execution**
- Adapts to unexpected results
- Uses real information, not predictions

✅ **More Efficient**
- Stop early if goal achieved
- Skip unnecessary tasks

✅ **Better User Experience**
- Can interrupt/modify after each task
- Real-time feedback on progress
- Clear visibility into what's happening

✅ **Solves Original Problem**
- After Task 1 extracts BreakoutAnalyst, replanning sees lib/analysts.py state
- Task 2 will only execute if VolumeAnalyst still exists
- No truncation breaking subsequent tasks

## Status

This is an **architectural improvement** that should be implemented.

It's not a small fix - it requires refactoring the main execution loop - but it's the RIGHT way to do adaptive execution.

Without this: System creates a fragile static plan upfront
With this: System creates adaptive plan that learns and adjusts

