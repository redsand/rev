# Execution Mode Demonstration

## Overview

Rev now supports two execution modes:
- **linear** (default): Traditional sequential execution
- **sub-agent**: Dispatch tasks to specialized agents based on action type

## Usage

### Method 1: CLI Flag

```bash
# Use sub-agent mode
rev --execution-mode sub-agent "your task here"

# Use linear mode (default)
rev --execution-mode linear "your task here"

# Using 'inline' alias (becomes 'linear')
rev --execution-mode inline "your task here"
```

### Method 2: Environment Variable

```bash
# Set for the session
export REV_EXECUTION_MODE=sub-agent
rev "your task"

# Or inline
REV_EXECUTION_MODE=sub-agent rev "your task"
```

### Method 3: Programmatically

```python
from rev import config

# Set execution mode
config.set_execution_mode("sub-agent")

# Get current mode
current_mode = config.get_execution_mode()
print(f"Mode: {current_mode}")
```

## How to Verify It's Working

When you run rev with sub-agent mode, you'll see:

```
============================================================
ORCHESTRATOR - MULTI-AGENT COORDINATION
============================================================
Task: your task...
Execution Mode: SUB-AGENT    <-- This shows which mode is active
```

During execution, you'll see:

```
Entering phase: execution
  → Executing with Sub-Agent architecture...    <-- Confirms sub-agent mode
  → Registered action types: add, edit, refactor, test, debug, fix, document, docs, research, investigate, analyze, review, create_tool, tool
  → Found X task(s) for sub-agent execution

  🤖 Dispatching task 0 (add): ...
  ✓ Task 0 completed successfully
```

## Available Sub-Agents

| Agent | Action Types | Purpose |
|-------|-------------|---------|
| CodeWriterAgent | `add`, `edit` | Create/modify code files |
| RefactoringAgent | `refactor` | Restructure code for quality |
| TestExecutorAgent | `test` | Run pytest commands |
| DebuggingAgent | `debug`, `fix` | Find and fix bugs |
| DocumentationAgent | `document`, `docs` | Create/update documentation |
| ResearchAgent | `research`, `investigate` | Code investigation |
| AnalysisAgent | `analyze`, `review` | Security and quality analysis |
| ToolCreationAgent | `create_tool`, `tool` | Generate new tools |

## Examples

### Example 1: Simple Task with Sub-Agent Mode

```bash
rev --execution-mode sub-agent "create a hello world function in hello.py"
```

You'll see it dispatches to `CodeWriterAgent` with action type `add`.

### Example 2: Refactoring with Sub-Agent Mode

```bash
rev --execution-mode sub-agent "refactor the calculate_total function for better readability"
```

The planner will assign action type `refactor`, which dispatches to `RefactoringAgent`.

### Example 3: Multiple Tasks

```bash
rev --execution-mode sub-agent "add authentication, write tests, and document the API"
```

The planner creates multiple tasks with different action types:
- `add` → CodeWriterAgent
- `test` → TestExecutorAgent
- `document` → DocumentationAgent

Each is dispatched to the appropriate specialized agent!

## Troubleshooting

**Issue**: Mode doesn't seem to be active
**Solution**: Ensure you're providing a task or using `--repl` mode:
```bash
# ❌ Won't work
rev --execution-mode sub-agent

# ✓ Correct
rev --execution-mode sub-agent "add a feature"

# ✓ Or use REPL
rev --execution-mode sub-agent --repl
```

**Issue**: "Invalid execution mode" error
**Solution**: Check spelling. Valid modes are: `linear`, `sub-agent`, `inline`

## Default Behavior

- Default mode is **linear** (traditional execution)
- Environment variable `REV_EXECUTION_MODE` overrides the default
- CLI flag `--execution-mode` overrides both the default and environment variable
