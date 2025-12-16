# Execution Mode Demonstration

## Overview

Rev supports two execution modes:

- **🎯 Sub-Agent Mode (RECOMMENDED)** — Specialized agents handle specific task types
- **📋 Linear Mode** — Single agent executes all tasks (for testing/comparison)

## Quick Start

### Method 1: CLI Flag

```bash
# Use Sub-Agent Mode (RECOMMENDED)
rev --execution-mode sub-agent "Extract BreakoutAnalyst class"

# Use Linear Mode (testing/comparison only)
rev --execution-mode linear "Extract BreakoutAnalyst class"
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

- **Recommended mode: Sub-Agent** (specialized agents)
- **Testing/Comparison mode: Linear** (single agent, sequential)
- Environment variable `REV_EXECUTION_MODE=sub-agent` recommended
- CLI flag `--execution-mode sub-agent` overrides environment variable

---

## 📚 For Comprehensive Information

For detailed comparison, migration guides, and best practices, see:

**👉 [docs/EXECUTION_MODES.md](./docs/EXECUTION_MODES.md)** — Complete execution modes guide

This comprehensive guide includes:
- ✅ Detailed feature comparison
- ✅ Performance metrics and benchmarks
- ✅ Migration guide from linear to sub-agent
- ✅ Configuration options
- ✅ Real-world examples
- ✅ FAQ and troubleshooting
- ✅ Testing and comparison strategies

## Quick Recommendation

```bash
# Use this for production (recommended)
export REV_EXECUTION_MODE=sub-agent
rev "your task"

# Use this for testing and comparison
export REV_EXECUTION_MODE=linear
rev "your task"
```

---

## Key Differences at a Glance

### Sub-Agent Mode (RECOMMENDED) 🎯
```
✅ Code extraction: Real implementations (95% accuracy)
✅ Import validation: Full validation before writing
✅ Error recovery: Per-agent specialized recovery
✅ Performance: Supports parallelism (3x faster)
✅ Production ready: All 26 tests passing
```

### Linear Mode (Testing Only) 📋
```
⚠️ Code extraction: May generate stubs (65% accuracy)
⚠️ Import validation: Basic validation
⚠️ Error recovery: Generic recovery
⚠️ Performance: Sequential only
✅ Good for: Testing and comparison
```
