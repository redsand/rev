# Adaptive Prompt Optimization - Architecture & Implementation

## The Problem You Identified

You were absolutely right: **The prompt optimizer should handle this automatically, not require manual intervention.**

### Current Broken Flow
```
User: "Extract analyst classes to lib/analysts/"
  ↓
Initial prompt optimization (once)
  ↓
RefactoringAgent executes
  → Calls: read_file (multiple times)
  → Never calls: write_file
  ↓
Verification detects: "No files created"
  ↓
Same exact prompt is used again
  ↓
Same failure occurs
  ↓
INFINITE LOOP - keeps trying exact same failing approach
```

### The Core Issue

The system has a static prompt optimization that improves the **user's request once** at the start, but no **runtime feedback loop** to improve **agent prompts when they fail**.

Specifically:
- RefactoringAgent has a system prompt that says "You MUST use write_file"
- But the LLM ignores this instruction
- The system retries with the exact same prompt instead of improving it
- No detection of "tool call pattern" (only reads, no writes)

## The Solution: Adaptive Prompt Optimization

### New Architecture

**File**: `rev/execution/adaptive_prompt_optimizer.py`

Creates a feedback loop:
```
Task Execution
  ↓
Verification Fails
  ↓
[NEW] Analyze tool call pattern
  ├─ Detect: "Agent called read_file 5x, write_file 0x"
  ├─ Classify: "INCOMPLETE_EXTRACTION failure type"
  └─ Extract key insights
  ↓
[NEW] LLM improves the system prompt
  ├─ Analyzes why previous prompt failed
  ├─ Makes write_file requirement MORE explicit
  ├─ Adds specific examples
  ├─ Removes ambiguity
  └─ Returns improved prompt
  ↓
[NEW] Retry task with improved prompt
  ├─ Pass improved prompt to agent
  ├─ Agent uses more explicit instructions
  ├─ Better chance of success
  └─ If still fails, improve again (up to 3 times)
```

### Key Components

#### 1. Tool Call Analysis
```python
def analyze_tool_call_pattern(tool_calls: list) -> Dict[str, Any]:
    """Detect failure patterns in agent's tool usage"""
    # Detects:
    # - Only read_file calls (missing writes)
    # - No modifications made
    # - Incomplete task execution patterns
```

**Example Analysis Result:**
```python
{
    "tool_calls_count": 5,
    "tools_used": ["read_file"],
    "pattern": "read_file → read_file → read_file → ...",
    "issue": "Agent reads files but never writes new files",
    "failure_type": "INCOMPLETE_EXTRACTION"
}
```

#### 2. Adaptive Prompt Improvement
```python
def get_agent_prompt_improvement(
    agent_type: str,  # "refactoring", "codewriter", etc.
    task_description: str,  # What agent tried to do
    failure_reason: str,  # Why it failed
    tool_analysis: Dict,  # Tool pattern analysis
    original_prompt: str,  # Original system prompt
    retry_attempt: int  # 1st, 2nd, 3rd retry
) -> str:
    # LLM analyzes the failure and improves the prompt
    # Gets progressively more explicit on retries
```

**Example: From Original to Improved**

Original prompt:
```
"You MUST use the write_file tool for each extracted file.
Do not just read files - you must CREATE new files."
```

Improved prompt (after failure analysis):
```
"CRITICAL: Your task will FAIL if you do not use write_file.

Step-by-step:
1. Read source file (use read_file)
2. Parse and identify each class
3. FOR EACH CLASS (do not skip):
   - CALL write_file with new filename
   - CALL write_file with complete class code
4. CALL write_file for __init__.py
5. CALL replace_in_file for imports

SUCCESS CRITERIA:
- Write_file called at least 3 times
- Each extracted class in its own file
- Imports updated
- No read-only inspection

FAILURE CRITERIA:
- Only calling read_file (FAIL!)
- Not calling write_file (FAIL!)
- Partial extraction (FAIL!)"
```

#### 3. Retry Integration
Modified `RefactoringAgent.execute()`:
```python
def execute(self, task: Task, context: RevContext) -> str:
    # Check for improved system prompt
    system_prompt = getattr(task, '_override_system_prompt', None) or REFACTORING_SYSTEM_PROMPT

    # Pass to execution
    result = self._execute_simple_refactoring_task(task, context, system_prompt)
    return result
```

Modified `_execute_simple_refactoring_task()`:
```python
def _execute_simple_refactoring_task(self, task, context, system_prompt=None):
    # Use provided system_prompt instead of hardcoded one
    if system_prompt is None:
        system_prompt = REFACTORING_SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": system_prompt},  # ← Uses improved prompt if provided
        {"role": "user", "content": f"Task: {task.description}..."}
    ]
```

### New Workflow

#### Before (Broken)
```
Verification Fails: "No files created"
  ↓
Decomposition suggests: "[CREATE] Create individual files"
  ↓
CodeWriterAgent executes
  ↓
Still fails (reads file, doesn't understand how to extract)
  ↓
Loop repeats
```

#### After (Self-Healing)
```
Verification Fails: "No files created"
  ↓
[NEW] Analyze tool calls: "Only read_file, no write_file"
  ↓
[NEW] Improve RefactoringAgent prompt with explicit write requirements
  ↓
Retry RefactoringAgent with improved prompt
  ├─ Prompt now explicitly states: "write_file MUST be called"
  ├─ Prompt includes examples
  ├─ Prompt has success/failure criteria
  └─ Agent has better chance of success
  ↓
If still fails: Improve prompt further (retry 2)
If still fails: Improve prompt further (retry 3)
If still fails: Fall back to decomposition/different agent
```

## Implementation Status

### Completed ✓
- [x] Created `adaptive_prompt_optimizer.py` module
- [x] Implemented `analyze_tool_call_pattern()` function
- [x] Implemented `get_agent_prompt_improvement()` function
- [x] Updated RefactoringAgent to accept override system prompt
- [x] Added prompt override mechanism to task execution

### Next: Integration Points (To be completed)

These need to be added to orchestrator.py to complete the system:

#### 1. Capture tool calls
When an agent executes, capture its tool calls:
```python
# In _dispatch_to_sub_agents() or agent execution
tool_calls = extract_tool_calls_from_llm_response(response)
# Store in context or task for later analysis
```

#### 2. Trigger adaptive optimization on verification failure
```python
if not verification_result.passed:
    # Try to improve the agent's prompt
    improved, new_prompt = improve_prompt_for_retry(
        agent_type=next_task.action_type,
        task=next_task,
        verification_failure=verification_result.message,
        tool_calls=agent_tool_calls,  # ← captured above
        original_prompt=agent.get_system_prompt(),
        retry_attempt=retry_count
    )

    if improved:
        # Attach improved prompt to task
        next_task._override_system_prompt = new_prompt

        # Retry instead of moving to next action
        iteration -= 1  # Don't count as a new iteration
        retry_count += 1
        continue  # Retry same task with improved prompt
```

#### 3. Add retry tracking
```python
# Track retries per task
next_task._retry_count = getattr(next_task, '_retry_count', 0) + 1
next_task._original_system_prompt = agent.get_system_prompt()
```

## Benefits

### For Users
- ✓ No manual prompt engineering required
- ✓ System self-improves when agents fail
- ✓ Better chance of task success
- ✓ Automatic failure analysis

### For System
- ✓ Learns what prompts work/fail
- ✓ Can track improvement history
- ✓ Less iteration with decomposition
- ✓ More efficient recovery from failures

### For Development
- ✓ Better debugging (sees improved prompts)
- ✓ Can analyze failure patterns by agent type
- ✓ Data for training better system prompts
- ✓ Metrics on adaptive improvement effectiveness

## Example: Extraction Task Recovery

### Scenario
User: "Extract analyst classes to lib/analysts/"

### Execution Trace

**Attempt 1:**
```
RefactoringAgent: task.description = "Extract analyst classes..."
  Tool calls: [read_file]
Verification: FAIL - "No files created"
Tool analysis: "Only read_file, no write_file"
```

**Prompt Improvement:**
```
Original:
"You MUST use write_file for each file. Do not just read files."

Improved (by LLM):
"CRITICAL: You will FAIL if you don't use write_file.
1. Read analysts.py (use read_file once)
2. For EACH analyst class:
   → Call write_file('lib/analysts/analyst_name.py', code)
   → NOT optional, REQUIRED
3. Call write_file for __init__.py
4. Call replace_in_file for imports

SUCCESS: write_file called ≥3 times
FAILURE: write_file called 0 times"
```

**Attempt 2 (with improved prompt):**
```
RefactoringAgent: task._override_system_prompt = improved_prompt
  Tool calls: [read_file, write_file, write_file, write_file, write_file]
Verification: PASS - "3 files created with valid imports"
Status: [COMPLETED]
```

## Testing

### Test Coverage Needed
- [ ] Tool analysis correctly detects failure patterns
- [ ] Prompt improvement generates valid prompts
- [ ] Override mechanism works in agents
- [ ] Retries use improved prompts
- [ ] Max retry limit prevents infinite loops
- [ ] Successful retry increments correctly

## Files Changed

| File | Change |
|------|--------|
| `rev/execution/adaptive_prompt_optimizer.py` | NEW - Adaptive optimization module |
| `rev/agents/refactoring.py` | Updated to accept override system prompt |
| `rev/execution/orchestrator.py` | (To be updated) Integrate optimization on failure |

## Configuration

Recommended orchestrator settings:
```python
config = OrchestratorConfig(
    enable_prompt_optimization=True,      # Enable adaptive optimization
    auto_optimize_prompt=True,            # Auto-improve prompts
    adaptive_max_retries=3,               # Try up to 3 times
)
```

## Future Enhancements

1. **Prompt History Tracking**
   - Store evolution of prompts for each agent type
   - Build library of effective prompts

2. **Failure Pattern Learning**
   - Detect which agents commonly fail
   - Pre-emptively improve their prompts

3. **Cross-Agent Learning**
   - When one agent improves, share learning with similar agents
   - Build agent-specific optimization profiles

4. **Metrics Collection**
   - Track: original success rate vs. improved success rate
   - Measure: average iterations to success
   - Identify: which improvement patterns work best

5. **User Feedback**
   - Allow users to provide feedback on prompts
   - Improve prompts based on user guidance

## Conclusion

This adaptive system transforms the Rev REPL from:
- **Broken:** Infinite retry loops with same failing prompt
- **Fixed:** Self-improving system that learns from failures

The key insight: **The system should improve itself, not require users to manually engineer better prompts.**

By analyzing tool usage patterns and asking the LLM to improve its own instructions, the system achieves genuine self-healing capabilities.
