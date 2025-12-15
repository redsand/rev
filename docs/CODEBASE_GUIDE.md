# rev - Codebase Architecture Guide

## Overview

**rev** is an autonomous CI/CD agent powered by Ollama that uses a multi-agent system to plan, review, execute, and validate code changes. This document provides a comprehensive guide to the codebase architecture for developers looking to fix bugs and build tests.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Entry Points](#entry-points)
- [Agent System](#agent-system)
- [Tool System](#tool-system)
- [Testing Infrastructure](#testing-infrastructure)
- [Common Bug Patterns](#common-bug-patterns)
- [Development Workflow](#development-workflow)

## Architecture Overview

```
rev/
├── __init__.py          # Package exports and API surface
├── __main__.py          # Entry point for `python -m rev`
├── main.py              # CLI argument parsing and orchestration
├── config.py            # Configuration and global settings
│
├── models/              # Data models
│   └── task.py          # Task, TaskStatus, RiskLevel, ExecutionPlan
│
├── execution/           # Agent implementations
│   ├── planner.py       # Planning agent - creates execution plans
│   ├── executor.py      # Execution agent - runs tasks
│   ├── reviewer.py      # Review agent - validates plans and actions
│   ├── validator.py     # Validation agent - post-execution checks
│   ├── learner.py       # Learning agent - project memory
│   ├── researcher.py    # Research agent - pre-planning exploration
│   ├── orchestrator.py  # Orchestrator - coordinates all agents
│   └── safety.py        # Safety checks for destructive operations
│
├── llm/                 # LLM integration
│   └── client.py        # Ollama API client with caching
│
├── tools/               # Tool implementations
│   ├── registry.py      # Tool registration and execution
│   ├── file_ops.py      # File operations (read, write, delete, etc.)
│   ├── git_ops.py       # Git operations (diff, commit, status, etc.)
│   ├── code_ops.py      # Code analysis and refactoring
│   ├── cache_ops.py     # Cache management
│   └── __init__.py      # Tool exports
│
├── cache/               # Caching system
│   ├── base.py          # Base cache interface
│   └── implementations.py # Concrete cache implementations
│
├── terminal.py          # Terminal utilities (REPL, input handling)
└── mcp.py               # Model Context Protocol integration

tests/
├── test_agent.py        # Core agent behaviors
├── test_advanced_planning.py  # Planning/review/execution coverage
└── ...                  # Additional integration and tool tests
```

## Core Components

### 1. Models (`rev/models/`)

**Key Classes:**

- **Task**: Represents a single task in an execution plan
  - Properties: `description`, `action_type`, `status`, `dependencies`, `risk_level`
  - Methods: `to_dict()`, `from_dict()`
  - Location: `rev/models/task.py:27-91`

- **TaskStatus** (Enum): Task lifecycle states
  - Values: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `STOPPED`
  - Location: `rev/models/task.py:11-16`

- **RiskLevel** (Enum): Task risk assessment
  - Values: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
  - Location: `rev/models/task.py:19-24`

- **ExecutionPlan**: Manages task collection and execution state
  - Properties: `tasks`, `current_index`, `lock` (thread-safe)
  - Methods: `add_task()`, `get_current_task()`, `mark_task_complete()`, `save_checkpoint()`, `load_checkpoint()`
  - Thread-safe with `threading.Lock`
  - Location: `rev/models/task.py:93-200+`

### 2. LLM Client (`rev/llm/client.py`)

**Purpose**: Communicates with Ollama API for language model inference

**Key Functions:**

- `ollama_chat(messages, tools)`: Send chat request to Ollama
  - Supports tool/function calling (OpenAI format)
  - Handles cloud model authentication (models ending in `-cloud`)
  - Implements LLM response caching
  - Interrupt-safe on Windows (Ctrl+C support)
  - Location: `rev/llm/client.py:75-200+`

**Features:**
- Automatic retry for cloud model authentication (401 errors)
- Graceful fallback when models don't support tools
- Caching layer for identical requests
- Signal handling for interrupts

### 3. Configuration (`rev/config.py`)

**Global Settings:**

```python
ROOT = pathlib.Path(os.getcwd()).resolve()  # Repository root
OLLAMA_BASE_URL = "http://localhost:11434"   # Ollama API endpoint
OLLAMA_MODEL = "qwen3-coder:480b-cloud"        # Default model
MAX_FILE_BYTES = 5 MB                        # File size limit
READ_RETURN_LIMIT = 80,000                   # Max characters returned
SEARCH_MATCH_LIMIT = 2000                    # Max search results
LIST_LIMIT = 2000                            # Max file listings
```

**Excluded Directories**: `.git`, `node_modules`, `__pycache__`, `dist`, etc.

**Allowed Commands**: `python`, `git`, `npm`, `pytest`, `make`, etc.

**System Info Caching**: OS, platform, architecture, shell type cached globally

## Entry Points

### 1. Main Entry Point (`rev/main.py`)

The `main()` function is the CLI entry point:

1. **Initialize caches** - Sets up file, LLM, repo, and dependency caches
2. **Parse arguments** - Processes CLI flags and options
3. **Handle special commands** - List checkpoints, resume execution
4. **Choose execution mode**:
   - **Orchestrator mode** (`--orchestrate`): Full multi-agent coordination
   - **REPL mode** (`--repl`): Interactive development
   - **One-shot mode**: Single task execution

**Flow:**
```
main()
  → initialize_caches()
  → argparse setup
  → orchestrator_mode() OR repl_mode() OR one-shot mode:
    → planning_mode()           # Generate plan
    → review_execution_plan()   # Review plan (optional)
    → execution_mode()          # Execute tasks
    → validate_execution()      # Post-execution validation
```

### 2. Package Entry Point (`rev/__main__.py`)

Simple wrapper for `python -m rev` execution:
```python
from .main import main
if __name__ == "__main__":
    main()
```

## Agent System

### Planning Agent (`rev/execution/planner.py`)

**Purpose**: Analyzes user requests and generates execution plans

**Key Function**: `planning_mode(user_request, enable_advanced_analysis, enable_recursive_breakdown)`

**Process:**
1. Gather repository context (git status, file structure)
2. Get system information (OS, platform, shell)
3. Send request to LLM with context
4. Parse JSON array of tasks
5. Perform recursive breakdown for complex tasks
6. Assess dependencies, risks, and impact
7. Return ExecutionPlan object

**Complex Task Handling:**
- Tasks marked with `"complexity": "high"` trigger recursive breakdown
- `_recursive_breakdown()` uses LLM to split high-level tasks into subtasks
- Max recursion depth: 2 levels
- Location: `rev/execution/planner.py:147-300+`

**System Prompt**: `PLANNING_SYSTEM` - Instructs LLM to create ordered task checklists

### Execution Agent (`rev/execution/executor.py`)

**Purpose**: Executes tasks sequentially or concurrently

**Key Functions:**

1. **`execution_mode(plan, auto_approve, tools, enable_action_review)`**
   - Sequential execution of all tasks
   - Maintains conversation with LLM for context
   - Handles tool calling
   - Safety checks for scary operations
   - Checkpoint saving on interrupts
   - Location: `rev/execution/executor.py:55-300+`

2. **`concurrent_execution_mode(plan, max_workers, auto_approve)`**
   - Parallel task execution using ThreadPoolExecutor
   - Respects task dependencies
   - Thread-safe plan updates
   - Interrupt handling across threads
   - Location: `rev/execution/executor.py:400-600+`

3. **`execute_single_task(task, context_messages, enable_action_review)`**
   - Executes one task with LLM and tools
   - Returns updated messages and task result
   - Used by both sequential and concurrent modes

**Execution Flow:**
```
execution_mode()
  → while not plan.is_complete():
    → Get current task
    → Send task to LLM
    → LLM responds with tool calls
    → execute_tool() for each tool call
      → Safety check (is_scary_operation?)
      → Action review (if enabled)
      → Execute tool function
    → Mark task complete
    → Move to next task
```

### Review Agent (`rev/execution/reviewer.py`)

**Purpose**: Validates execution plans and individual actions

**Key Functions:**

1. **`review_execution_plan(plan, strictness)`**
   - Reviews entire execution plan before execution
   - Checks completeness, security, dependencies
   - Returns: APPROVED, APPROVED_WITH_SUGGESTIONS, REQUIRES_CHANGES, REJECTED
   - Location: `rev/execution/reviewer.py:100-200+`

2. **`review_action(action_name, action_args, context, strictness)`**
   - Reviews individual tool calls during execution
   - Fast security checks (command injection, secrets, SQL injection)
   - Optional LLM-based deep review
   - Location: `rev/execution/reviewer.py:250-350+`

**Review Decision Types:**
- `APPROVED`: Plan is safe and complete
- `APPROVED_WITH_SUGGESTIONS`: Plan is good but has recommendations
- `REQUIRES_CHANGES`: Plan has issues that should be addressed
- `REJECTED`: Plan has critical issues

**Strictness Levels:**
- `LENIENT`: Only flags critical issues
- `MODERATE` (default): Flags medium+ severity issues
- `STRICT`: Flags all potential issues

### Validation Agent (`rev/execution/validator.py`)

**Purpose**: Post-execution verification

**Key Function**: `validate_execution(plan, user_request, run_tests, run_linter, check_syntax, enable_auto_fix)`

**Checks:**
1. **Execution check**: Did tasks complete successfully?
2. **Syntax check**: Python syntax validation
3. **Test suite**: Run pytest/npm test
4. **Linter**: Check code quality
5. **Git diff**: Verify changes were made
6. **Semantic validation**: Do changes match the request?

**Auto-fix**: Can automatically fix linting and formatting issues if enabled

**Returns**: `ValidationReport` with status for each check

### Learning Agent (`rev/execution/learner.py`)

**Purpose**: Project memory across sessions

**Features:**
- Stores successful patterns
- Recalls similar past tasks
- Estimates execution time
- Warns about past failures
- Persists to `.rev/cache/learning/`

### Research Agent (`rev/execution/researcher.py`)

**Purpose**: Pre-planning codebase exploration

**Depth Levels:**
- `SHALLOW`: Quick file scan
- `MEDIUM`: Moderate exploration with key file reads
- `DEEP`: Comprehensive analysis

### Orchestrator (`rev/execution/orchestrator.py`)

**Purpose**: Coordinates all agents for maximum autonomy

**Flow:**
1. Learning Agent (recall similar tasks)
2. Research Agent (explore codebase)
3. Planning Agent (generate plan)
4. Review Agent (validate plan)
5. Execution Agent (run tasks)
6. Validation Agent (verify results)
7. Learning Agent (store patterns)

## Tool System

### Tool Registry (`rev/tools/registry.py`)

**Purpose**: Central registry for all available tools

**Key Functions:**

- `execute_tool(tool_name, args)`: Execute a tool by name
  - Looks up tool in registry
  - Validates arguments
  - Executes tool function
  - Returns result or error
  - Location: `rev/tools/registry.py:50-100+`

- `get_available_tools()`: Returns list of all registered tools with metadata

**Tool Categories:**

1. **File Operations** (`rev/tools/file_ops.py`):
   - `read_file`, `write_file`, `delete_file`, `move_file`, `copy_file`
   - `append_to_file`, `replace_in_file`, `create_directory`
   - `get_file_info`, `file_exists`, `read_file_lines`, `tree_view`
   - `list_dir`, `search_code`

2. **Git Operations** (`rev/tools/git_ops.py`):
   - `git_diff`, `git_status`, `git_log`, `git_branch`, `git_commit`
   - `apply_patch`, `get_repo_context`

3. **Code Operations** (`rev/tools/code_ops.py`):
   - `remove_unused_imports`, `extract_constants`, `simplify_conditionals`
   - `analyze_dependencies`, `update_dependencies`, `scan_dependencies_vulnerabilities`
   - `scan_code_security`, `detect_secrets`, `check_license_compliance`
   - Data conversion: `convert_json_to_yaml`, `convert_csv_to_json`, etc.

4. **Command Execution**:
   - `run_cmd`, `run_tests`

5. **Utilities**:
   - `install_package`, `web_fetch`, `execute_python`, `get_system_info`

6. **SSH Operations**:
   - `ssh_connect`, `ssh_exec`, `ssh_copy_to`, `ssh_copy_from`, `ssh_disconnect`

7. **Cache Operations** (`rev/tools/cache_ops.py`):
   - `get_cache_stats`, `clear_caches`, `persist_caches`

### Safety System (`rev/execution/safety.py`)

**Purpose**: Prevents destructive operations without confirmation

**Key Functions:**

- `is_scary_operation(action_name, action_args)`: Checks if operation is potentially destructive
- `prompt_scary_operation(action_name, action_args)`: Prompts user for confirmation

**Scary Operations:**
- File deletion (`delete_file`, `rm`, `remove`)
- Git destructive ops (`reset --hard`, `clean -f`, `push --force`)
- Commands containing: delete, remove, clean, reset, force, destroy, drop, truncate
- Database operations
- Tasks with "delete" action type

## Caching System

### Cache Types (`rev/cache/`)

1. **FileContentCache**: Caches file contents (60s TTL)
   - Invalidates on file modification
   - 10-100x faster for repeated reads

2. **LLMResponseCache**: Caches LLM responses (1 hour TTL)
   - Caches identical queries
   - Near-instant responses for repeated questions
   - Significant cost savings

3. **RepoContextCache**: Caches git status/logs (30s TTL)
   - Invalidates on new commits
   - 5-20x faster for repo queries

4. **DependencyTreeCache**: Caches dependency analysis (10 min TTL)
   - Invalidates when dependency files change
   - 10-50x faster for dependency operations

### Cache Implementation

**Base Interface**: `IntelligentCache` (`rev/cache/base.py`)
- `get(key)`, `set(key, value, ttl)`, `invalidate(key)`, `clear()`
- `get_stats()`: Returns hit rate, total requests, cache size

**Persistence**: Caches persist to `.rev/cache/` directory

## Data Flow

### One-Shot Execution Flow

```
User Input
    ↓
main() - Parse CLI args
    ↓
planning_mode(user_request)
    ├→ get_repo_context() - Git status, file tree
    ├→ get_system_info() - OS, platform
    ├→ ollama_chat() - Generate tasks
    ├→ _recursive_breakdown() - Expand complex tasks
    └→ Return ExecutionPlan
    ↓
review_execution_plan(plan) [Optional]
    ├→ ollama_chat() - Review plan
    ├→ Parse review decision
    └→ Return decision + suggestions
    ↓
execution_mode(plan) OR concurrent_execution_mode(plan)
    ├→ For each task:
    │   ├→ ollama_chat() - Get tool calls
    │   ├→ execute_tool() - Run tool
    │   │   ├→ is_scary_operation() - Safety check
    │   │   └→ Tool function (file_ops, git_ops, etc.)
    │   └→ mark_task_complete()
    └→ Return success/failure
    ↓
validate_execution(plan) [Optional]
    ├→ Run tests
    ├→ Check syntax
    ├→ Run linter
    ├→ Verify git diff
    └→ Return ValidationReport
    ↓
Results displayed to user
```

### REPL Mode Flow

```
repl_mode()
    ↓
Loop:
    ├→ Get user input
    ├→ Execute same as one-shot:
    │   → planning_mode()
    │   → review (optional)
    │   → execution_mode()
    │   → validation (optional)
    ├→ Update session context
    └→ Repeat
```

### Concurrent Execution Flow

```
concurrent_execution_mode(plan, max_workers)
    ↓
Build dependency graph
    ↓
ThreadPoolExecutor(max_workers)
    ↓
For each task:
    ├→ Wait for dependencies to complete
    ├→ Execute task in thread:
    │   └→ execute_single_task()
    │       ├→ ollama_chat()
    │       ├→ execute_tool()
    │       └→ Return result
    ├→ Update plan (thread-safe with lock)
    └→ Mark task complete
    ↓
Wait for all tasks
    ↓
Return success/failure
```

## Testing Infrastructure

### Test Suite (`tests/`)

**Stats:**
- **Hundreds of tests** spanning unit, integration, and workflow coverage
- **Cross-cutting coverage** of planning, review, and execution paths

**Test Categories:**

1. **File Operations** (25 tests)
   - read_file, write_file, delete_file
   - move_file, copy_file, append_to_file
   - replace_in_file, create_directory
   - file_exists, get_file_info
   - Edge cases: missing files, permission errors

2. **Git Operations** (18 tests)
   - git_diff, git_status, git_log
   - git_branch, git_commit, apply_patch
   - Mocking git commands

3. **Code Operations** (12 tests)
   - remove_unused_imports, extract_constants
   - simplify_conditionals
   - Dependency analysis, security scanning

4. **Task Management** (15 tests)
   - Task creation, status transitions
   - ExecutionPlan operations
   - Checkpoint save/load
   - Thread safety

5. **Execution Modes** (10 tests)
   - Sequential execution
   - Concurrent execution
   - Error handling, interrupts

6. **Caching** (20 tests)
   - FileContentCache, LLMResponseCache
   - Cache invalidation, TTL
   - Persistence, statistics

7. **CLI and REPL** (10 tests)
   - Argument parsing
   - REPL commands
   - Session management

8. **Safety and Security** (8 tests)
   - Scary operation detection
   - Security scanning
   - Path validation

9. **Utilities** (18 tests)
   - System info
   - Web fetch
   - SSH operations
   - MCP integration

### Test Fixtures

Common fixtures in the test suite:

- `@pytest.fixture tmp_path`: Temporary directory for file operations
- Mock objects for Ollama API, git commands, SSH connections
- Sample data: file contents, git logs, dependency trees

### Running Tests

```bash
# Run all tests
pytest tests -v

# Run with coverage
pytest tests --cov=rev --cov-report=term-missing

# Run specific test category
pytest tests -k "test_file_operations" -v

# Generate HTML coverage report
pytest tests --cov=rev --cov-report=html
```

## Common Bug Patterns

### 1. Tool Execution Errors

**Symptom**: "Model does not support tool calling"

**Cause**: Ollama model doesn't support function calling (older models like codellama:7b)

**Location**: `rev/llm/client.py:75-200`

**Fix**: Use models with tool support (llama3.1, qwen2.5, mistral-nemo)

### 2. Path Traversal Issues

**Symptom**: "Path escapes repo" errors

**Cause**: File operations trying to access paths outside repository root

**Location**: `rev/tools/file_ops.py` - `_safe_path()` function

**Fix**: Ensure all paths are relative to `config.ROOT`

### 3. Thread Safety Issues

**Symptom**: Race conditions in concurrent execution

**Cause**: Shared state without proper locking

**Location**: `rev/models/task.py` - ExecutionPlan uses `threading.Lock`

**Fix**: Ensure all plan modifications use `with plan.lock:`

### 4. Cache Invalidation

**Symptom**: Stale data returned from caches

**Cause**: Cache not invalidated when file changes

**Location**: `rev/cache/implementations.py`

**Fix**: Check TTL and invalidation logic in cache classes

### 5. Interrupt Handling

**Symptom**: Ctrl+C doesn't stop execution on Windows

**Cause**: Signal handling differences on Windows

**Location**: `rev/llm/client.py:40-73` - Interruptible requests

**Fix**: Use `_make_request_interruptible()` for all LLM calls

### 6. Checkpoint Resume

**Symptom**: Resume fails or re-executes completed tasks

**Cause**: Task status not properly saved/loaded

**Location**: `rev/models/task.py` - `save_checkpoint()`, `load_checkpoint()`

**Fix**: Ensure stopped tasks are reset to pending on resume

## Development Workflow

### Setting Up Development Environment

```bash
# Clone repository
git clone <repo-url>
cd rev

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For testing

# Install Ollama
# See README.md for platform-specific instructions

# Pull a model with tool support
ollama pull llama3.1:latest
```

### Making Changes

1. **Create a branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make changes**:
   - Edit code in `rev/` directory
   - Follow existing code style
   - Add docstrings to new functions

3. **Write tests**:
   - Add tests under `tests/`
   - Ensure tests cover new functionality
   - Run tests: `pytest tests/ -v`

4. **Update documentation**:
   - Update README.md if adding features
   - Add docstrings to new functions
   - Update this guide if changing architecture

5. **Run quality checks**:
   ```bash
   # Run tests with coverage
   pytest tests/ --cov=rev --cov-report=term-missing

   # Run linter
   ruff check .

   # Run formatter
   black rev/
   ```

6. **Commit and push**:
   ```bash
   git add .
   git commit -m "feat: Add new feature"
   git push origin feature/my-feature
   ```

### Debugging Tips

1. **Enable debug mode**:
   ```bash
   OLLAMA_DEBUG=1 python -m rev "task description"
   ```

2. **Use REPL for interactive debugging**:
   ```bash
   python -m rev --repl
   ```

3. **Check logs**:
   - Ollama logs: Check Ollama service output
   - Cache stats: Use `get_cache_stats()` tool
   - Git operations: Use `git_status()` and `git_diff()`

4. **Test in isolation**:
   ```bash
   pytest tests/test_agent.py::test_specific_function -v -s
   ```

5. **Add print debugging**:
   - Add `print()` statements in code
   - Check `OLLAMA_DEBUG` output for API calls

### Code Style Guidelines

- **Formatting**: Use Black formatter
- **Linting**: Use Ruff
- **Docstrings**: Use Google-style docstrings
- **Type hints**: Add type hints to function signatures
- **Comments**: Explain complex logic, not obvious code
- **Naming**:
  - Classes: PascalCase
  - Functions: snake_case
  - Constants: UPPER_SNAKE_CASE
  - Private: _leading_underscore

## Next Steps

For more detailed information, see:

- **README.md**: User-facing documentation and features
- **ARCHITECTURE.md**: High-level system architecture
- **COVERAGE.md**: Test coverage details
- **RECOMMENDATIONS.md**: Future improvement ideas
- **ADVANCED_PLANNING.md**: Planning system details
- **CACHING.md**: Caching system documentation
- **TEST_PLAN.md**: Testing strategy and plans

---

**Last Updated**: 2025-11-22
**Version**: rev 2.0.1
