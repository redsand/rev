# Rev Architecture

This document describes the modular architecture of the `rev` project — a **6-Agent Autonomous System** (v2.0.1).

## 6-Agent System Overview

```
┌─────────────────────────────────────────────────────┐
│                   USER REQUEST                      │
└─────────────────┬───────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │  ORCHESTRATOR   │  (Optional - coordinates all agents)
         └────────┬────────┘
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌─────────┐
│LEARNING│→ │ RESEARCH │→ │PLANNING │
└────────┘  └──────────┘  └─────────┘
                               │
                               ▼
                         ┌──────────┐
                         │  REVIEW  │
                         └────┬─────┘
                              │
                              ▼
                         ┌──────────┐
                         │EXECUTION │
                         └────┬─────┘
                              │
                              ▼
                        ┌───────────┐
                        │VALIDATION │
                        └───────────┘
```

### Agent Responsibilities

| Agent | Purpose | Module |
|-------|---------|--------|
| **Learning** | Project memory across sessions, pattern recognition | `execution/learner.py` |
| **Research** | Pre-planning codebase exploration | `execution/researcher.py` |
| **Planning** | Break down requests into atomic tasks | `execution/planner.py` |
| **Review** | Validate plans and actions, security checks | `execution/reviewer.py` |
| **Execution** | Execute tasks sequentially or in parallel | `execution/executor.py` |
| **Validation** | Post-execution verification (tests, linting) | `execution/validator.py` |
| **Orchestrator** | Coordinates all agents (optional) | `execution/orchestrator.py` |

## Directory Structure

```
rev/
├── __init__.py              # Main package exports
├── __main__.py              # Entry point for `python -m rev`
├── main.py                  # CLI entry point and main() function
├── config.py                # Configuration constants and settings
│
├── cache/                   # Intelligent caching system
│   ├── __init__.py
│   ├── base.py             # IntelligentCache base class
│   └── implementations.py   # FileContentCache, LLMResponseCache, etc.
│
├── models/                  # Data models
│   ├── __init__.py
│   └── task.py             # Task, ExecutionPlan, TaskStatus, RiskLevel
│
├── tools/                   # Tool functions (41 total)
│   ├── __init__.py
│   ├── file_ops.py         # File operations (14 functions)
│   ├── git_ops.py          # Git operations (9 functions)
│   ├── code_ops.py         # Code refactoring (3 functions)
│   ├── conversion.py       # Data format conversion (5 functions)
│   ├── dependencies.py     # Dependency management (3 functions)
│   ├── security.py         # Security scanning (3 functions)
│   ├── ssh_ops.py          # SSH operations (6 functions)
│   ├── cache_ops.py        # Cache management (4 functions)
│   ├── utils.py            # Utilities (4 functions)
│   └── registry.py         # Tool registration and execution
│
├── llm/                     # LLM integration
│   ├── __init__.py
│   └── client.py           # ollama_chat and LLM client
│
├── mcp/                     # Model Context Protocol
│   ├── __init__.py
│   └── client.py           # MCPClient and utilities
│
├── execution/               # 6-Agent System
│   ├── __init__.py
│   ├── planner.py          # Planning Agent - task breakdown
│   ├── executor.py         # Execution Agent - task execution
│   ├── reviewer.py         # Review Agent - plan/action validation
│   ├── validator.py        # Validation Agent - post-execution checks
│   ├── researcher.py       # Research Agent - codebase exploration
│   ├── learner.py          # Learning Agent - project memory
│   ├── orchestrator.py     # Orchestrator - agent coordination
│   └── safety.py           # Safety checks for destructive operations
│
└── terminal/                # Terminal I/O
    ├── __init__.py
    ├── input.py            # Cross-platform input handling
    └── repl.py             # Interactive REPL mode
```

## Module Responsibilities

### Core Modules

- **config.py**: Global configuration, environment variables, system info caching
- **main.py**: CLI argument parsing and main entry point
- **__main__.py**: Package entry point (`python -m rev`)

### Cache System (`cache/`)

Intelligent caching with TTL, LRU eviction, and disk persistence:
- **IntelligentCache**: Base cache class with stats tracking
- **FileContentCache**: Caches file contents with mtime tracking
- **LLMResponseCache**: Caches LLM responses (1 hour TTL)
- **RepoContextCache**: Caches git repository context (30s TTL)
- **DependencyTreeCache**: Caches dependency analysis (10 min TTL)

### Models (`models/`)

Data structures for task management:
- **Task**: Individual task with risk assessment and dependencies
- **ExecutionPlan**: Task collection with dependency tracking
- **TaskStatus**: Enum for task states (PENDING, IN_PROGRESS, COMPLETED, FAILED)
- **RiskLevel**: Enum for risk assessment (LOW, MEDIUM, HIGH, CRITICAL)

### Tools (`tools/`)

41 tool functions organized by category:
1. **File Operations** (file_ops.py): read, write, search, delete, move, copy, etc.
2. **Git Operations** (git_ops.py): diff, commit, status, log, branch management
3. **Code Operations** (code_ops.py): Remove imports, extract constants, simplify conditionals
4. **Conversion** (conversion.py): JSON/YAML/CSV/ENV format conversion
5. **Dependencies** (dependencies.py): Analyze, update, scan vulnerabilities
6. **Security** (security.py): Code security scanning, secret detection, license compliance
7. **SSH Operations** (ssh_ops.py): Remote command execution, file transfer
8. **Cache Operations** (cache_ops.py): Cache stats, clearing, persistence
9. **Utilities** (utils.py): Package install, web fetch, Python execution, system info

### LLM Integration (`llm/`)

- **ollama_chat()**: Communicates with Ollama API with retry logic and caching

### MCP Integration (`mcp/`)

- **MCPClient**: Model Context Protocol client for external tools

### Execution (`execution/`) — 6-Agent System

The execution module implements a multi-agent architecture:

**Core Agents:**
- **planner.py**: Planning Agent - generates execution plans with recursive breakdown
- **executor.py**: Execution Agent - executes plans sequentially or concurrently
- **reviewer.py**: Review Agent - validates plans, detects security vulnerabilities
- **validator.py**: Validation Agent - post-execution verification (tests, linting, syntax)
- **researcher.py**: Research Agent - pre-planning codebase exploration
- **learner.py**: Learning Agent - project memory across sessions

**Coordination:**
- **orchestrator.py**: Orchestrator Agent - coordinates all agents for full autonomy
- **safety.py**: Safety checks for destructive operations

**Agent Data Structures:**
```python
# Review Agent
class ReviewDecision(Enum):
    APPROVED, APPROVED_WITH_SUGGESTIONS, REQUIRES_CHANGES, REJECTED

# Validation Agent
class ValidationStatus(Enum):
    PASSED, PASSED_WITH_WARNINGS, FAILED, SKIPPED

# Learning Agent
class TaskPattern:  # Learned patterns from past executions
class ProjectContext:  # Project-specific knowledge

# Research Agent
class ResearchFindings:  # Codebase exploration results

# Orchestrator
class AgentPhase(Enum):
    LEARNING, RESEARCH, PLANNING, REVIEW, EXECUTION, VALIDATION, COMPLETE, FAILED
```

### Terminal (`terminal/`)

- **input.py**: Cross-platform terminal input with escape key support
- **repl.py**: Interactive REPL mode with session management

## Usage

### Installation

```bash
# From source directory
pip install -e .

# Or use directly
python -m rev --help
```

### Running

```bash
# Basic usage
rev "Add error handling to API endpoints"

# Full orchestration mode (all 6 agents coordinated)
rev --orchestrate --learn --research "Implement user authentication"

# Enable specific agents
rev --research "Find files related to payments"
rev --learn "Add rate limiting"
rev --research-depth deep "Analyze authentication flow"

# Control review and validation
rev --review-strictness strict "Database migration"
rev --no-validate "Quick documentation update"
rev --auto-fix "Add linting to codebase"

# Action-level review (reviews each tool call)
rev --action-review "Sensitive security changes"

# Parallel execution
python -m rev -j 4 "Refactor authentication module"

# Interactive REPL mode
python -m rev --repl
```

### Importing

```python
# Import key classes and functions
from rev import Task, ExecutionPlan, read_file, git_status

# Import from specific modules
from rev.models import TaskStatus, RiskLevel
from rev.tools import search_code, analyze_dependencies
from rev.execution import planning_mode, execution_mode
from rev.terminal import repl_mode

# Import agent modules
from rev.execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from rev.execution.validator import validate_execution, ValidationStatus
from rev.execution.researcher import research_codebase, ResearchFindings
from rev.execution.learner import LearningAgent
from rev.execution.orchestrator import run_orchestrated, Orchestrator
```

## Benefits of Modular Architecture

1. **Easier Testing**: Each module has focused unit tests
2. **Better Maintainability**: Find and understand code faster (~200-400 lines per file vs 4,870)
3. **Clearer Dependencies**: See what imports what
4. **Easier Collaboration**: Multiple developers can work on different modules
5. **Reduced Cognitive Load**: Smaller, focused files
6. **Better IDE Support**: Faster autocomplete and navigation
7. **Reusability**: Import only what you need

## Memory Isolation

Memory and caching remain **project-specific**:

**Cache System** (`.rev_cache/`):
- File content cache with mtime tracking
- LLM response cache (1 hour TTL)
- Repository context cache (30s TTL)
- Dependency tree cache (10 min TTL)

**Learning Agent Memory** (`.rev_memory/`):
- `patterns.json` — Learned task patterns from successful executions
- `context.json` — Project-specific knowledge (framework, language, style)
- `history.json` — Last 100 execution memories

Both directories are:
- Project-specific (no overlap between projects)
- Configured via `ROOT = pathlib.Path(os.getcwd()).resolve()`
- Git-ignored by default

## Migration from Monolithic `rev.py`

The original `rev.py` (4,870 lines) has been refactored into:
- **30 module files** organized in 8 directories
- **~3,500 lines** of modular code (excluding original rev.py)
- **100% backwards compatible** - all functionality preserved
- **Same CLI interface** - `rev` command works identically

All original functions, classes, and behaviors have been preserved exactly.
