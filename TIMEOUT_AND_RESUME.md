# Timeout Management and Chain Resumption

This document describes the new timeout management and chain resumption features added to handle long-running operations and gracefully resume execution after interruptions.

## Features

### 1. Intelligent Timeout Management

**Location**: `rev/execution/timeout_manager.py`

The timeout manager provides configurable timeouts with automatic retry logic:

- **Initial timeout**: 300 seconds (5 minutes) by default
- **Maximum timeout**: 1800 seconds (30 minutes)
- **Retry logic**: Up to 3 attempts with exponential backoff
- **Timeout multiplier**: 2.0x (each retry doubles the timeout)

####Configuration via Environment Variables:

```bash
# Set initial timeout (seconds)
export REV_INITIAL_TIMEOUT=600

# Set maximum timeout (seconds)
export REV_MAX_TIMEOUT=3600

# Set maximum retry attempts
export REV_MAX_RETRIES=5

# Set timeout multiplier for exponential backoff
export REV_TIMEOUT_MULTIPLIER=1.5
```

#### Usage Example:

```python
from rev.execution.timeout_manager import TimeoutManager, TimeoutConfig

# Create timeout manager with custom config
config = TimeoutConfig(
    initial_timeout=600,  # 10 minutes
    max_timeout=3600,     # 1 hour
    max_retries=5,
    timeout_multiplier=2.0
)
timeout_mgr = TimeoutManager(config)

# Execute function with automatic retries
result = timeout_mgr.execute_with_retry(
    long_running_function,
    "operation_name",
    *args,
    **kwargs
)
```

### 2. Automatic State Persistence

**Location**: `rev/execution/state_manager.py`

The state manager automatically saves execution state after each task completion:

- **Auto-save**: Checkpoints created after each task
- **Interrupt handling**: Automatic save when Ctrl+C is pressed
- **Resume capability**: Continue from where you left off
- **Progress tracking**: Track completed, pending, and failed tasks

#### Features:

- Automatic checkpoint creation after each task
- Graceful interruption handling (Ctrl+C)
- Resume instructions displayed on interrupt
- Checkpoint cleanup (keeps last 10 by default)
- Session tracking with unique IDs

#### Checkpoint Structure:

```json
{
  "version": "1.0",
  "session_id": "20250101_123456",
  "checkpoint_number": 5,
  "timestamp": "2025-01-01T12:34:56.789012",
  "reason": "task_complete",
  "plan": {
    "tasks": [...],
    "current_index": 4,
    "summary": "4/10 completed"
  },
  "resume_info": {
    "tasks_completed": 4,
    "tasks_pending": 6,
    "tasks_stopped": 0,
    "tasks_failed": 0,
    "tasks_total": 10,
    "next_task": "Run integration tests",
    "progress_percent": 40.0
  }
}
```

### 3. Resume Command

Resume execution from a checkpoint after an interruption.

#### Usage:

```bash
# Resume from latest checkpoint (automatic)
rev --resume

# Resume from specific checkpoint
rev --resume .rev_checkpoints/checkpoint_20250101_123456_0005_20250101_123456_789.json

# List all available checkpoints
rev --list-checkpoints
```

#### Example Output:

```
rev - Available Checkpoints

1. checkpoint_20250101_123456_0005_20250101_123456_789.json
   Timestamp: 2025-01-01T12:34:56.789012
   Tasks: 10
   Status: 4/10 completed

2. checkpoint_20250101_120000_0003_20250101_120000_123.json
   Timestamp: 2025-01-01T12:00:00.123456
   Tasks: 8
   Status: 3/8 completed
```

### 4. Ctrl+C Interrupt Handling

**Location**: `rev/execution/executor.py`

Graceful handling of Ctrl+C interrupts:

- Signal handler installed at execution start
- Current task marked as "stopped"
- State automatically saved to checkpoint
- Resume instructions displayed
- Original signal handler restored on exit

#### Example Interrupt:

```
^C

⚠️  EXECUTION INTERRUPTED
==============================================================

✓ State saved to: .rev_checkpoints/checkpoint_20250101_123456_0005.json

To resume from where you left off, run:

  rev --resume .rev_checkpoints/checkpoint_20250101_123456_0005.json

Or to resume from the latest checkpoint:

  rev --resume

==============================================================
```

## Workflow Examples

### Example 1: Long-Running Task with Timeout

```bash
# Start execution with custom timeouts
export REV_INITIAL_TIMEOUT=900   # 15 minutes
export REV_MAX_TIMEOUT=5400      # 90 minutes
export REV_MAX_RETRIES=4

rev "Run full test suite and fix any failures"
```

If a tool or LLM call times out:
1. System retries with longer timeout (15m → 30m → 60m → 90m)
2. Progress is displayed for each retry
3. After 4 failed attempts, task is marked as failed
4. State is saved and you can resume later

### Example 2: Interrupted Execution

```bash
# Start long-running task
rev --orchestrate "Refactor entire authentication system"

# ... execution running ...
# Press Ctrl+C to interrupt

⚠️  Execution interrupted by Ctrl+C
==============================================================
✓ State saved to: .rev_checkpoints/checkpoint_20250101_143022_0012.json

To resume:
  rev --resume
==============================================================

# Resume later
rev --resume
```

### Example 3: Checkpoint Management

```bash
# List all checkpoints
rev --list-checkpoints

# Resume from specific checkpoint
rev --resume .rev_checkpoints/checkpoint_20250101_143022_0012.json

# Clean old checkpoints manually (keeps last 10 by default)
find .rev_checkpoints -type f -name "*.json" | sort -r | tail -n +11 | xargs rm
```

## Integration Points

### For Tool Developers

Wrap long-running tools with timeout management:

```python
from rev.execution.timeout_manager import with_retry_and_timeout, TimeoutConfig

@with_retry_and_timeout(
    config=TimeoutConfig(initial_timeout=600),
    operation_name="expensive_operation"
)
def my_long_running_tool(args):
    # Your tool implementation
    pass
```

### For Execution Engine

The state manager is automatically integrated in `execution_mode()`:

1. **Initialization**: State manager created with auto-save enabled
2. **Task lifecycle**: Hooks for task start, complete, and failure
3. **Interrupts**: Automatic checkpoint on Ctrl+C or ESC key
4. **Cleanup**: Signal handler restored on exit

## Technical Details

### Checkpoint Directory

- Default: `.rev_checkpoints/`
- Automatically created if it doesn't exist
- Files named: `checkpoint_{session_id}_{number}_{timestamp}.json`
- Cleaned automatically (keeps last 10)

### Task States

- `PENDING`: Not yet started
- `IN_PROGRESS`: Currently executing
- `COMPLETED`: Successfully finished
- `FAILED`: Execution failed with error
- `STOPPED`: Interrupted (can be resumed)

### State Transitions on Resume

When resuming from a checkpoint:

1. Load execution plan from checkpoint file
2. Reset `STOPPED` tasks to `PENDING` status
3. Continue execution from first pending task
4. Respect task dependencies
5. Create new checkpoints in same session

## Troubleshooting

### Issue: Checkpoint not found

```bash
✗ Checkpoint file not found: /path/to/checkpoint.json

Use --list-checkpoints to see available checkpoints.
```

**Solution**: Use `--list-checkpoints` to see available checkpoints or use `--resume` without arguments to use the latest.

### Issue: Timeout too short

```bash
⏱ ollama_chat timed out after 300s. Will retry with 600s timeout...
```

**Solution**: Increase the initial timeout:

```bash
export REV_INITIAL_TIMEOUT=1800  # 30 minutes
```

### Issue: Too many checkpoints

**Solution**: Clean old checkpoints:

```python
from rev.execution.state_manager import StateManager

state_mgr = StateManager(plan)
state_mgr.clean_old_checkpoints(keep_last=5)
```

## Future Enhancements

1. **Distributed timeout management**: Handle timeouts across multiple workers
2. **Cloud checkpoint storage**: Save checkpoints to S3/GCS for team collaboration
3. **Checkpoint compression**: Reduce checkpoint file sizes
4. **Timeout analytics**: Track which operations timeout most frequently
5. **Adaptive timeouts**: Learn optimal timeouts based on historical data
6. **Resume with modifications**: Modify plan before resuming
7. **Partial rollback**: Roll back to specific checkpoint and continue differently

## See Also

- `rev/execution/timeout_manager.py` - Timeout management implementation
- `rev/execution/state_manager.py` - State persistence implementation
- `rev/execution/executor.py` - Execution engine with state management
- `rev/models/task.py` - Task and ExecutionPlan models
