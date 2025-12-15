# rev — Production-Grade Agentic Development System

A **robust, pattern-based autonomous development system** powered by [Ollama](https://ollama.ai) for local LLM inference. Built on **21 Agentic Design Patterns** for production-grade code generation, testing, and validation.

## 🌟 What Makes Rev Different

Rev isn't just another AI coding assistant — it's a **complete agentic development system** implementing industry-proven design patterns:

- **🧠 Agentic Design Patterns** — Built on 21 patterns from research (Goal Setting, Routing, RAG, Recovery, Resource Budgets, etc.)
- **🔍 Hybrid Search** — Combines symbolic (regex) + semantic (RAG/TF-IDF) code search for superior context gathering
- **📊 Resource-Aware** — Tracks steps, tokens, and time budgets to prevent runaway execution
- **🎯 Goal-Oriented** — Derives measurable goals from requests and validates they're met
- **🛡️ Production-Ready** — Multi-layer validation, security scanning, auto-recovery, and rollback planning
- **⚡ Intelligent** — Self-routing, priority scheduling, and adaptive agent configuration

## Key Features

### Agentic Design Patterns (NEW!)
- **🎯 Goal Setting & Monitoring** — Automatic goal derivation with measurable success metrics
- **🔀 Intelligent Routing** — Analyzes requests and configures optimal agent pipeline
- **🔍 RAG (Retrieval-Augmented Generation)** — Semantic code search using TF-IDF for better context
- **📊 Resource Budgets** — Tracks and enforces limits on steps, tokens, and execution time
- **🔄 Exception Recovery** — Automatic rollback plans and recovery strategies
- **📡 Inter-Agent Communication** — Message bus for coordinated multi-agent workflows
- **⚙️ Coding Workflows** — Multi-stage chains (analyze → design → plan → implement → test → refine)

### Core Capabilities
- **🤖 6-Agent System** — Planning, Research, Review, Execution, Validation, and Learning agents
- **🎭 Orchestrator Mode** — Meta-agent coordinates all agents with resource tracking
- **🔍 Research Agent** — Pre-planning codebase exploration (symbolic + semantic search)
- **📚 Learning Agent** — Project memory that learns from past executions
- **✅ Validation Agent** — Post-execution verification with goal evaluation
- **🛡️ Intelligent Review** — Automatic validation with security vulnerability detection
- **🔬 Advanced Analysis** (NEW!) — Test coverage, code context, symbol usage, dependencies, semantic diffs
- **📚 Complex Task Handling** — Recursive breakdown of large features
- **🔓 Smart Automation** — Autonomous execution with review-based approval
- **📋 Planning Mode** — Comprehensive task checklists with recursive decomposition
- **⚡ Execution Mode** — Iterative completion with optional action-level review
- **🚀 Parallel Execution** — Run 2+ tasks concurrently for 2-4x faster completion
- **🧪 Automatic Testing** — Runs tests after each change to validate correctness
- **🔧 Full Code Operations** — Review, edit, add, delete, rename files
- **🏠 Local LLM** — Uses Ollama (no API keys, fully private)
- **🎯 Advanced Planning** — Dependency analysis, impact assessment, risk evaluation
- **🛠️ Built-in Utilities** — File conversion, code refactoring, dependency management
- **⚡ Intelligent Caching** — File content, LLM responses, repo context, dependency trees

## Architecture

**Multi-Agent Orchestration System (v2.0)**

```
┌─────────────────────────────────────────────────────┐
│                   USER REQUEST                      │
└─────────────────┬───────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │  ORCHESTRATOR   │  (Optional - coordinates all agents)
         └────────┬────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           1. LEARNING AGENT (NEW!)                  │
│  • Recall similar past tasks                       │
│  • Provide success patterns                        │
│  • Estimate execution time                         │
│  • Warn about past failures                        │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           2. RESEARCH AGENT (NEW!)                  │
│  • Explore codebase before planning               │
│  • Find relevant files and patterns               │
│  • Identify similar implementations               │
│  • Suggest approach based on codebase style       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           3. PLANNING AGENT                         │
│  • Break down request into atomic tasks            │
│  • Recursive breakdown for complex features        │
│  • Generate ordered execution checklist            │
│  • Assess dependencies, risks, and impact          │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           4. REVIEW AGENT                           │
│  • Validate plan completeness                      │
│  • Identify security vulnerabilities               │
│  • Check for missing or unnecessary tasks          │
│  • Decision: Approved / Suggestions / Rejected     │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           5. EXECUTION AGENT                        │
│  • Execute tasks sequentially or in parallel       │
│  • [Optional] Review Agent validates each action   │
│  • Make changes, run tests, validate               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           6. VALIDATION AGENT (NEW!)                │
│  • Run test suite                                  │
│  • Check syntax errors                             │
│  • Run linter                                      │
│  • Semantic validation (did changes match request?)│
│  • Auto-fix minor issues (optional)               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           LEARNING AGENT (POST)                     │
│  • Store successful patterns                       │
│  • Update project context                          │
│  • Record for future reference                     │
└─────────────────────────────────────────────────────┘
```

## Agentic Design Patterns

Rev implements **21 Agentic Design Patterns** from cutting-edge AI agent research, making it a production-grade development system rather than a simple code assistant.

### Pattern Implementations

**Phase 1: Foundational Patterns** ✅
- **Goal Setting & Monitoring** — Automatic derivation of measurable goals from user requests
- **Prompt Chaining (Coding Workflows)** — Multi-stage workflows: analyze → design → plan → implement → test → refine
- **Routing** — Intelligent request analysis that selects optimal agent configuration
- **Inter-Agent Communication** — Message bus with pub/sub for coordinated workflows
- **RAG (Retrieval-Augmented Generation)** — Semantic code search using TF-IDF alongside symbolic search
- **Exception Handling & Recovery** — Automatic rollback plans and recovery strategies
- **Resource-Aware Optimization** — Budget tracking for steps, tokens, and execution time

**Phase 2: Core Integrations** ✅
- **TaskRouter Integration** — Routes every request to determine coding mode and agent configuration
- **Goal Integration** — Goals automatically derived and validated post-execution
- **Priority Scheduling** — Higher-priority tasks execute first for critical path optimization
- **Metrics Emission** — JSONL metrics for evaluation and monitoring (`.rev/metrics/`)

**Phase 3: Advanced Integration** ✅
- **RAG Integration** — Research Agent uses hybrid symbolic + semantic search (enabled by default)
- **Resource Budget Tracking** — Orchestrator tracks and enforces budgets across all phases
- **Goal Validation** — Validation Agent evaluates whether goals were met

### Pattern Benefits

**🎯 Superior Context Gathering**
```bash
# Research Agent uses both approaches:
# Symbolic: Finds exact matches for "authenticate", "login", "jwt"
# Semantic: Finds conceptually related code even without keywords
rev "Add OAuth2 authentication"
```

**📊 Controlled Execution**
```bash
# Resource budgets prevent runaway execution:
# - Max steps: 500 (configurable via REV_MAX_STEPS)
# - Max tokens: 2,000,000 (REV_MAX_TOKENS)
# - Max time: 3600s / 60min (REV_MAX_SECONDS)
rev "Refactor entire authentication system"
# Output: "📊 Resource Usage: Steps: 45/500 | Tokens: 12000/2000000 | Time: 120s/3600s"
```

**🤖 Agent-Directed Adaptation**
```bash
# Planner adapts steps dynamically and regenerates plans when needed:
rev "Migrate to Postgres with minimal downtime"
# → Planner creates a focused sequence of tasks, regroups if a step fails,
#   and continues until goals are met or budgets are reached.
```

**🎯 Goal-Oriented Validation**
```bash
# Goals automatically derived and validated:
rev "Fix all failing tests"
# Derives goal: "All tests must pass"
# Validation checks: Tests passed? ✅
# Goal met? ✅
```

**🔀 Adaptive Configuration**
```bash
# Router analyzes request and optimizes:
rev "Quick typo fix in README"
# → Route: quick_edit (skips research, minimal review)

rev "Implement payment processing system"
# → Route: full_feature (enables all agents, strict review)
```

### Pattern Usage

Most patterns are **enabled by default** with graceful degradation:

- **RAG Search**: Enabled (falls back to symbolic if unavailable)
- **Resource Budgets**: Always tracking (configurable limits)
- **Goal Validation**: Runs if goals exist (auto-derived for most tasks)
- **Routing**: Always active (optimizes agent pipeline)

**Configuration:**
```bash
# Disable RAG for faster execution
rev --research-depth shallow "Quick task"

# Adjust resource budgets
export REV_MAX_STEPS=500
export REV_MAX_TOKENS=200000
export REV_MAX_SECONDS=3600  # 1 hour

# Control routing behavior via strictness
rev --review-strictness strict "Critical production change"
```

**See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for complete pattern documentation and usage examples.**

## Installation

### Quick Install (Recommended)

```bash
# Install via pip (coming soon to PyPI)
pip install rev-agentic

# Or install from source
git clone https://github.com/redsand/rev
cd rev
pip install -e .
```

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows - Download from https://ollama.ai
```

### 2. Pull a Code Model

**⚠️ Important:** rev requires a model with **function/tool calling support** for full functionality.

**Recommended models with tool support:**
```bash
# Best for code tasks
ollama pull llama3.1:latest        # Best overall (tool support)
ollama pull qwen2.5:7b              # Good for code (tool support)
ollama pull mistral-nemo:latest     # Fast with tools

# Legacy (no tool support - limited functionality)
ollama pull gpt-oss:120b-cloud        # ⚠️ No tool support
ollama pull deepseek-coder:latest   # ⚠️ Check version for tool support
```

**🌐 Ollama Cloud Models (NEW!):**
```bash
# Ensure Ollama is running (cloud models proxy through local Ollama)
ollama serve

# Use powerful cloud-hosted models (requires authentication)
rev --model qwen3-coder:480b-cloud "Your task"
rev --model llama3.3:90b-cloud "Complex refactoring task"
```

**Important:** Cloud models require your local Ollama instance to be running. The local instance automatically proxies requests to Ollama's cloud service.

On first use, you'll be prompted to authenticate:
1. A browser URL will be displayed
2. Visit the URL and sign in with your Ollama account
3. Authorize your device
4. Press Enter to continue

**Verify tool support:**
```bash
# List models
ollama list

# Check model info
ollama show llama3.1:latest
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### One-Shot Mode

Execute a single task with **fully autonomous** operation:

```bash
rev "Add error handling to all API endpoints"
```

The agent will:
1. Analyze your repository
2. Generate an execution plan
3. **Execute autonomously** (no approval needed)
4. Prompt ONLY for destructive operations (delete, force push, etc.)
5. Show final summary

**New in v2: Autonomous by default!** No more repeated approval prompts. The agent only asks permission for potentially destructive operations.

### Interactive REPL

For iterative development with **session memory** and **real-time interaction**:

```bash
rev --repl
```

The REPL maintains context across multiple prompts and allows **real-time guidance** during task execution:

```
agent> Review all documentation files
  ℹ️  Running in autonomous mode - destructive operations will prompt
  ... reviews README.md, COVERAGE.md, etc ...

agent> Now create a project overview document based on what you reviewed
  ... uses knowledge from previous reviews to create comprehensive overview ...

agent> /status
Session Summary:
  - Tasks completed: 15
  - Files reviewed: 8
  - Files modified: 1
```

**New REPL Commands:**
- `/status` - Show what's been done in this session
- `/clear` - Clear session memory
- `/help` - Show all commands
- `/exit` - Exit with session summary
- **`/mode`** - Control execution depth and thinking level (NEW in v2.0!)

### Real-Time Interaction (NEW!)

**Type messages while tasks run** — just like Claude Code! When the agent is executing tasks, you can guide it in real-time:

```
agent> Add unit tests for the auth module

[Task 1/3] Create test file for auth module
============================================================

  🤖 I'll start by reading the auth module to understand...

focus on the login function specifically    <-- You type this while running!

  💬 Injected user guidance into conversation

  🤖 Understood, I'll focus specifically on the login function...
```

**How it works:**
- **Stream output** — See LLM responses as they generate in real-time
- **Type anytime** — Your input is captured in a background thread
- **Single message** — Only 1 pending message at a time (new replaces old)
- **Injected as guidance** — Your message becomes `[USER GUIDANCE]` in the conversation

**Commands during execution:**
| Input | Effect |
|-------|--------|
| Any text + Enter | Injects `[USER GUIDANCE] your message` |
| `/stop` or `/cancel` | Immediately stops the current task |
| `/priority <msg>` | Injects as `[IMPORTANT USER GUIDANCE]` |

This enables a collaborative workflow where you can steer the agent without restarting tasks!

### Execution Modes (NEW!)

Rev v2.0 introduces flexible execution modes that control the depth of analysis, research, and validation. Use `/mode` in REPL or configure via command-line:

```bash
# In REPL
rev> /mode thorough
Mode: thorough
  ✓ Orchestrator mode enabled
  Research:        Enabled (deep)
  Learning:        Enabled
  Review:          Enabled (strict)
  Validation:      Enabled + auto-fix
  Parallel Workers: 3

rev> Implement user authentication
# Executes with thorough mode settings...
```

**Available Modes:**

#### Mode Feature Matrix

| Feature | simple | standard | thorough | max |
|---------|--------|----------|----------|-----|
| **Orchestration** | ❌ | ✅ | ✅ | ✅ |
| **Research** | ❌ | Medium | Deep | Deep |
| **Learning** | ❌ | ❌ | ✅ | ✅ |
| **Review** | Lenient | Moderate | Strict | Strict |
| **Validation** | ❌ | ✅ | ✅ + auto-fix | ✅ + auto-fix |
| **Action Review** | ❌ | ❌ | ❌ | ✅ |
| **Parallel Workers** | 1 | 2 | 3 | 4 |
| **Best For** | Quick fixes | Daily development | Complex features | Critical changes |

**Mode Descriptions:**

- **`simple`** - Fast execution with minimal overhead. No research or learning. Sequential execution. Perfect for quick fixes and testing.

- **`standard`** - Balanced approach (DEFAULT). Medium research depth, moderate review, validation enabled, 2 parallel workers. Ideal for daily development.

- **`thorough`** - Comprehensive analysis. Deep research + learning, strict review, full validation with auto-fix, 3 parallel workers. Use for complex features and refactoring.

- **`max`** - Maximum capabilities. Full orchestration with all agents, deep research + learning, strict review with action-level validation, auto-fix, 4 parallel workers. For critical architectural changes.

**Command-Line Mode Control:**

```bash
# Standard mode (default)
rev "Add feature X"

# Simple mode for quick tasks
rev --no-orchestrate "Fix typo in README"

# Thorough mode for complex tasks
rev --orchestrate --research-depth deep --learn --auto-fix "Refactor auth system"
```

### Manual Approval Mode

If you want to manually approve the execution plan (old behavior):

```bash
rev --prompt "Run all tests and fix any failures"
```

With `--prompt`, the agent will ask for approval before starting execution.
**Default behavior: Runs autonomously without prompting** (except for scary operations).

### What Operations Require Confirmation?

Even in autonomous mode, the agent will **always prompt** for potentially destructive operations:

**Scary Operations (will prompt):**
- File deletion or removal
- Git operations: `reset --hard`, `clean -f`, `push --force`
- Commands containing: delete, remove, rm, clean, reset, force, destroy, drop, truncate
- Applying patches without dry-run first
- Tasks with "delete" action type

**Safe Operations (no prompt):**
- Reading files
- Searching code
- Running tests
- Creating/modifying files
- Git diff/log/status
- Running linters/formatters

## Configuration

### Environment Variables

```bash
# Ollama configuration
export OLLAMA_BASE_URL="http://localhost:11434"  # Default
export OLLAMA_MODEL="qwen3-coder:480b-cloud"           # Default

# LLM Generation Parameters (NEW - for improved tool calling accuracy)
export OLLAMA_TEMPERATURE=0.1                   # Lower = more accurate tool calls (0.0-2.0)
export OLLAMA_NUM_CTX=16384                     # Context window: 8K, 16K, or 32K tokens
export OLLAMA_TOP_P=0.9                         # Nucleus sampling (0.0-1.0)
export OLLAMA_TOP_K=40                          # Vocabulary limiting

# Reliability tuning (optional)
export OLLAMA_MAX_RETRIES=6                     # Retries for transient 5xx errors
export OLLAMA_RETRY_BACKOFF_SECONDS=2           # Base backoff between retries
export OLLAMA_RETRY_BACKOFF_MAX_SECONDS=30      # Cap for backoff delay
export OLLAMA_TIMEOUT_MAX_MULTIPLIER=3          # Cap timeout growth (10m -> 30m)

# Debug logging (see exact prompts sent to model)
export OLLAMA_DEBUG=1                           # Enable LLM debug logging

# Then run agent
rev "Your task here"
```

### LLM Tool Calling Optimization (NEW!)

**Rev now includes optimized settings for improved tool calling accuracy**, especially important for local models:

**Key Improvements:**
- ✅ **Lower temperature (0.1)** - Reduces randomness for more consistent tool calls
- ✅ **Larger context (16K)** - Allows for complex multi-step tool interactions
- ✅ **Enhanced prompts** - Step-by-step instructions guide local models more effectively
- ✅ **Debug logging** - View exact prompts and parameters with `OLLAMA_DEBUG=1`

**Quick Configuration:**

```bash
# Copy example configuration
cp .env.example .env

# Edit and customize
nano .env
```

**Configuration Profiles:**

```bash
# Profile 1: High Accuracy (default)
OLLAMA_TEMPERATURE=0.1
OLLAMA_NUM_CTX=16384

# Profile 2: Creative Tasks (docs, commit messages)
OLLAMA_TEMPERATURE=0.7
OLLAMA_NUM_CTX=8192

# Profile 3: Complex Tasks (large refactorings)
OLLAMA_TEMPERATURE=0.1
OLLAMA_NUM_CTX=32768

# Profile 4: Low Resource (limited RAM)
OLLAMA_TEMPERATURE=0.2
OLLAMA_NUM_CTX=8192
```

**Interactive REPL Configuration:**

```bash
# Start REPL and update settings interactively
rev --repl

# View all settings including LLM generation parameters
/set

# Update temperature for current session
/set temperature 0.1

# Update context window
/set num_ctx 32768

# Save settings for future sessions
/save
```

**📖 Full Guide:** See [LLM Tool Calling Optimization Guide](docs/LLM_TOOL_CALLING_OPTIMIZATION.md) for:
- Detailed parameter explanations
- Model recommendations
- Debugging failed tool calls
- Performance tuning
- Interactive `/set` command usage
- Advanced configuration

### Command-Line Options

```bash
rev [OPTIONS] "task description"

Options:
  --repl                       Interactive REPL mode
  --model MODEL                Ollama model to use (default: qwen3-coder:480b-cloud)
  --base-url URL               Ollama API URL (default: http://localhost:11434)
  --prompt                     Prompt for approval before execution (default: auto-approve)
  -j N, --parallel N           Number of concurrent tasks (default: 2, use 1 for sequential)

  # Agent Control
  --orchestrate                Enable orchestrator mode (full multi-agent coordination)
  --learn                      Enable learning agent for project memory
  --research                   Enable research agent for pre-planning exploration
  --research-depth LEVEL       Research depth: shallow, medium, deep (default: medium)
  --review / --no-review       Enable/disable review agent (default: enabled)
  --review-strictness LEVEL    Review strictness: lenient, moderate, strict (default: moderate)
  --action-review              Enable action-level review during execution
  --validate / --no-validate   Enable/disable validation agent (default: enabled)
  --auto-fix                   Enable auto-fix for minor validation issues

  # Resuming / Checkpoints
  --resume [CHECKPOINT]        Resume from a checkpoint (omit path to use latest)
  --list-checkpoints           List checkpoints saved in .rev/checkpoints/

  -h, --help                   Show help message
```

### Parallel Execution

**New in v2.0:** Concurrent task execution for faster completion!

By default, rev now runs **2 tasks in parallel** when they don't have dependencies on each other. This dramatically speeds up execution for complex tasks.

**Examples:**

```bash
# Use default (2 concurrent tasks)
rev "Review all API endpoints and add tests"

# Run 4 tasks in parallel for maximum speed
rev -j 4 "Refactor all components and update tests"

# Run sequentially (old behavior) for debugging
rev -j 1 "Complex refactoring that needs careful sequencing"

# Run 8 tasks in parallel for large codebases
rev -j 8 "Update all imports across the project"
```

**How it works:**
- The agent automatically tracks task dependencies
- Independent tasks (like reviewing different files) run in parallel
- Dependent tasks (like "run tests" after "fix bug") wait for prerequisites
- Thread-safe execution ensures no conflicts

**Performance benefits:**
- 2x-4x faster execution for typical tasks
- Scales well with more workers for large codebases
- No manual intervention needed - dependencies are automatic

## Examples

### Example 1: Add Feature

```bash
rev "Add rate limiting middleware to Express app"
```

**Generated Plan:**
1. [REVIEW] Analyze current Express middleware structure
2. [ADD] Create rate-limiting middleware module
3. [EDIT] Integrate rate limiter into main app
4. [ADD] Add tests for rate limiting
5. [TEST] Run test suite to validate

### Example 2: Fix Bugs

```bash
rev "Fix all ESLint errors in src/ directory"
```

**Generated Plan:**
1. [REVIEW] Run ESLint to identify all errors
2. [EDIT] Fix import order issues
3. [EDIT] Fix unused variable warnings
4. [EDIT] Fix indentation errors
5. [TEST] Run ESLint again to verify fixes

### Example 3: Refactoring

```bash
rev "Refactor authentication logic into separate service"
```

**Generated Plan:**
1. [REVIEW] Analyze current authentication code
2. [ADD] Create AuthService class
3. [EDIT] Extract auth logic to service
4. [EDIT] Update controllers to use AuthService
5. [EDIT] Update dependency injection
6. [TEST] Run integration tests

## How It Works

### Planning Phase

The agent uses Ollama to:
1. Analyze repository context (git status, file structure, recent commits)
2. Understand your request
3. Break it into atomic, ordered tasks
4. Classify each task by type (review, edit, add, delete, test)

### Execution Phase

For each task, the agent:
1. **Gathers context** using tools like `read_file`, `search_code`, `list_dir`
2. **Makes changes** using `write_file` or `apply_patch` (unified diffs)
3. **Validates changes** by running `run_tests`
4. **Reports completion** and moves to next task

### Available Tools

The agent has access to **41 powerful tools** across multiple categories:

**New in v2.0.1:** SSH remote execution! Connect to remote hosts, execute commands, and transfer files for managing your infrastructure.

**New in v2.0.1:** Cross-platform OS detection! The agent automatically detects your operating system (Windows, Linux, macOS) and adapts tool usage accordingly - choosing bash vs PowerShell, correct path separators, and platform-specific commands.

#### Core File Operations
| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Create or overwrite files |
| `delete_file` | Delete a file |
| `move_file` | Move or rename files |
| `copy_file` | Copy a file to a new location |
| `append_to_file` | Append content to a file |
| `replace_in_file` | Find and replace text within a file (supports regex) |
| `create_directory` | Create directories |
| `get_file_info` | Get file metadata (size, modified time, etc.) |
| `file_exists` | Check if a file or directory exists |
| `read_file_lines` | Read specific line range from a file |
| `tree_view` | Generate a tree view of directory structure |

#### Code Discovery & Search
| Tool | Description |
|------|-------------|
| `list_dir` | List files matching glob pattern |
| `search_code` | Search code with regex (symbolic search) |
| `rag_search` | Semantic code search using RAG/TF-IDF (NEW!) |

#### Git Operations
| Tool | Description |
|------|-------------|
| `git_diff` | View current uncommitted changes |
| `git_status` | Get detailed git status |
| `git_log` | Get git commit history |
| `git_commit` | Commit changes with a message |
| `git_branch` | Git branch operations (list, create, switch, current) |
| `apply_patch` | Apply unified diff patches |
| `get_repo_context` | Get git status and repo structure |

#### Command Execution
| Tool | Description |
|------|-------------|
| `run_cmd` | Execute shell commands |
| `run_tests` | Run test suite (pytest, npm test, etc.) |

#### Utility Tools
| Tool | Description |
|------|-------------|
| `install_package` | Install Python packages using pip |
| `web_fetch` | Fetch content from URLs |
| `execute_python` | Execute Python code snippets |
| `get_system_info` | Get system info (OS, version, architecture, shell type) |

#### SSH Remote Execution
| Tool | Description |
|------|-------------|
| `ssh_connect` | Connect to a remote host via SSH |
| `ssh_exec` | Execute commands on a remote host |
| `ssh_copy_to` | Copy a file to a remote host |
| `ssh_copy_from` | Copy a file from a remote host |
| `ssh_disconnect` | Disconnect from a remote host |
| `ssh_list_connections` | List all active SSH connections |

#### MCP (Model Context Protocol) Support
| Tool | Description |
|------|-------------|
| `mcp_add_server` | Add an MCP server for extended capabilities |
| `mcp_list_servers` | List configured MCP servers |
| `mcp_call_tool` | Call tools on MCP servers |

**New in v2.0.1:** MCP support allows the agent to connect to external tools and data sources through the Model Context Protocol, enabling integration with databases, APIs, and other development tools.

**New in v2.0.1:** Rev now includes **9 default MCP servers** for enhanced coding capabilities:
- 🧠 **Core**: memory, sequential-thinking, fetch
- 🚀 **Coding & CI/CD**: DeepWiki (GitHub search), Exa Search (code search), Semgrep (static analysis)
- 📚 **Docs**: Cloudflare Docs, Astro Docs
- 🤖 **AI/ML**: Hugging Face

**🔒 Private Mode:** Use `/private on` to disable all public MCP servers when working with secure/unsharable code. See [MCP_SERVERS.md](docs/MCP_SERVERS.md) for details.

#### Advanced Code Analysis Tools (NEW!)

**New in v2.0.1:** Five powerful analysis tools for improved development accuracy, review, and bug fixing:

| Tool | Description | Use Case |
|------|-------------|----------|
| `analyze_test_coverage` | Test coverage analysis using coverage.py/Istanbul | Check coverage before modifying code |
| `analyze_code_context` | Git history, bug fixes, code churn analysis | Understand why code exists before refactoring |
| `find_symbol_usages` | Find all references to functions/classes/variables | Assess impact before renaming/deleting |
| `analyze_dependencies` | Dependency graph with impact radius | Understand ripple effects before changes |
| `analyze_semantic_diff` | Detect breaking changes beyond line diffs | Verify backward compatibility |

**How Agents Use These Tools:**

```bash
# Before refactoring, agents automatically:
rev "Refactor UserService.authenticate method"

# 1. analyze_test_coverage() → Ensures 85% coverage exists
# 2. analyze_code_context() → Discovers recent bug fix for race condition
# 3. find_symbol_usages() → Finds 47 usages across 12 files
# 4. analyze_dependencies() → Calculates HIGH impact radius
# 5. Makes changes with full awareness
# 6. analyze_semantic_diff() → Verifies no breaking changes
```

**Benefits:**
- **🛡️ Prevents bugs:** Understands historical context to avoid re-introducing bugs
- **🎯 Impact awareness:** Knows exactly what will break before making changes
- **✅ Coverage validation:** Ensures adequate tests exist before modifications
- **🔍 Dependency tracking:** Maps full impact radius of changes
- **⚡ Breaking change detection:** Automatic backward compatibility checks

These tools transform Rev from "code modifier" to "intelligent code surgeon" with full awareness of consequences.

## Troubleshooting

### "Ollama API error: Connection refused"

Ensure Ollama is running:

```bash
ollama serve
```

### "Model not found"

Pull the model first:

```bash
ollama pull qwen3-coder:480b-cloud
```

### "401 Unauthorized" for Cloud Models

Cloud models (ending with `-cloud`) require authentication. The agent will:
1. Detect the 401 error automatically
2. Display a signin URL
3. Wait for you to authenticate

**Steps to authenticate:**
```bash
# When you see the authentication prompt:
# 1. Visit the displayed URL in your browser
# 2. Sign in with your Ollama account
# 3. Authorize the device
# 4. Press Enter to continue

# The authentication persists, so you only need to do this once per device
```

**Example:**
```bash
rev --model qwen3-coder:480b-cloud "Review code"

# Output:
# ============================================================
# OLLAMA CLOUD AUTHENTICATION REQUIRED
# ============================================================
# Model 'qwen3-coder:480b-cloud' requires authentication.
#
# To authenticate:
# 1. Visit this URL in your browser:
#    https://ollama.com/connect?name=YOUR-DEVICE&key=...
#
# 2. Sign in with your Ollama account
# 3. Authorize this device
# ============================================================
#
# Press Enter after completing authentication...
```

### "400 Bad Request" or "Model not using tools"

Some Ollama models don't support function/tool calling. This is normal for older or smaller models.

**Models with tool support (recommended):**
- `llama3.1` (8B, 70B, 405B)
- `mistral-nemo`
- `mistral-large`
- `qwen2.5` (7B and up)
- `phi3.5`

**How to fix:**
1. Use a model with tool support:
   ```bash
   ollama pull llama3.1:latest
   rev --model llama3.1:latest "Your task"
   ```

2. Or enable debug mode to see what's happening:
   ```bash
   OLLAMA_DEBUG=1 rev "Your task"
   ```

3. If you're using the OpenAI-hosted **gpt-oss** models (e.g., `gpt-oss-20b`) via the Chat Completions API, explicitly request **tools mode** in your payload and always include a `tools` array. An empty array is fine if you aren't defining any functions, but the field must be present so the model knows to stay in tools mode. Example request body:
   ```json
   {
   "model": "gpt-oss-20b",
   "mode": "tools",
   "messages": [{"role": "user", "content": "test"}],
   "tools": []
  }
  ```

If your request defines functions, replace the empty `tools` array with your tool definitions. Each subsequent request should keep `mode: "tools"` and include the `tools` array (empty or populated) to prevent tool-calling failures.

The agent will automatically retry without tools if it detects the model doesn't support them, but tool support is highly recommended for best results.

### "Path escapes repo"

rev only operates within the current repository for safety. Use relative paths.

### Tasks not completing

Try a more specific request or use a larger model:

```bash
rev --model deepseek-coder:33b "Your task"
```

## Testing & Coverage

**Test Coverage: 80%** - Production Ready ✅

- **136 tests passing** (100% pass rate)
- **800+ statements** in the rev package
- **Cross-platform tested** (Linux, macOS, Windows detection)
- **SSH remote execution tested** (connection management, file transfer)
- **99% test code coverage** (tests are well-tested themselves)

### What's Tested
- ✅ File operations (read, write, delete, move, copy, append, replace)
- ✅ Advanced file operations (file_exists, read_file_lines, tree_view)
- ✅ Git operations (diff, patch, commit, status, log, branch)
- ✅ Command execution and validation
- ✅ Utility tools (install_package, web_fetch, execute_python, get_system_info)
- ✅ System information detection (OS, version, shell type, caching)
- ✅ SSH remote execution (connect, execute, file transfer, disconnect)
- ✅ MCP (Model Context Protocol) integration
- ✅ Task management (Task, ExecutionPlan)
- ✅ Tool execution routing
- ✅ Ollama integration (mocked)
- ✅ Planning and execution modes
- ✅ Security validations
- ✅ REPL mode commands and session tracking
- ✅ CLI argument parsing
- ✅ Scary operation detection and prompting
- ✅ Edge cases and error handling

### Code Quality Initiatives
- ✅ Static code analysis with automated linting
- ✅ Type hinting for improved code clarity
- ✅ Comprehensive documentation coverage
- ✅ Security scanning and vulnerability assessment
- ✅ Performance benchmarking and optimization
- ✅ Cross-platform compatibility verification
- ✅ Dependency security scanning

### Running Tests

```bash
# Run all tests
python -m pytest tests -v

# Run with coverage report
python -m pytest tests --cov=rev --cov-report=term-missing

# Generate HTML coverage report
python -m pytest tests --cov=rev --cov-report=html
```

For detailed coverage information, see [COVERAGE.md](COVERAGE.md).

For future testing, quality, documentation, and security improvements, see [RECOMMENDATIONS.md](RECOMMENDATIONS.md).

## Advanced Planning

rev includes sophisticated planning capabilities that analyze your tasks before execution:

### Features

**🔍 Dependency Analysis**
- Automatically determines optimal task ordering
- Identifies parallelization opportunities
- Calculates critical path through task dependencies

**📊 Impact Assessment**
- Predicts scope of changes before making them
- Identifies affected files and modules
- Estimates change magnitude

**⚠️ Risk Evaluation**
- Evaluates risk level for each task (🟢 LOW, 🟡 MEDIUM, 🟠 HIGH, 🔴 CRITICAL)
- Identifies potentially breaking changes
- Flags dangerous operations (database, security, delete, etc.)

**🔄 Rollback Planning**
- Automatically generates recovery procedures
- Action-specific rollback steps
- Database and production rollback guidance

**Example Output:**
```
============================================================
EXECUTION PLAN
============================================================
1. [REVIEW] Analyze current authentication module
   Risk: 🟢 LOW

2. [EDIT] Refactor auth to use dependency injection
   Risk: 🟡 MEDIUM (Destructive/modifying action: edit)
   Depends on: #1

3. [DELETE] Remove deprecated auth helpers
   Risk: 🔴 CRITICAL (Destructive/modifying action: delete)
   Depends on: #2
   ⚠️  Warning: Potentially breaking change

============================================================
PLANNING ANALYSIS SUMMARY
============================================================
Total tasks: 5
Risk distribution:
  🟢 LOW: 2
  🟡 MEDIUM: 2
  🔴 CRITICAL: 1

⚡ Parallelization potential: 3 tasks can run concurrently
   Critical path length: 4 steps

🔴 CRITICAL: 1 high-risk task(s) require extra caution
   - Task #3: Remove deprecated auth helpers...
     Rollback plan available
============================================================
```

**Learn More:** See [ADVANCED_PLANNING.md](ADVANCED_PLANNING.md) for complete documentation.

## Multi-Agent Quorum System

**New in v2.0.1:** rev now uses a **3-agent quorum system** that provides intelligent review and validation at multiple stages for more accurate and secure code changes.

### The Three Agents

```
┌──────────────────────────────────────────────────────────┐
│  1. PLANNING AGENT                                       │
│  • Breaks down complex requests into atomic tasks       │
│  • Analyzes dependencies and risks                      │
│  • Performs recursive breakdown for complex features    │
│  • Creates comprehensive execution plans                │
└───────────────────┬──────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────────────┐
│  2. REVIEW AGENT (NEW!)                                  │
│  • Validates execution plans before execution           │
│  • Reviews individual actions during execution          │
│  • Identifies security vulnerabilities                  │
│  • Suggests improvements and alternatives               │
│  • Checks for missing tasks or unnecessary steps        │
└───────────────────┬──────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────────────┐
│  3. EXECUTION AGENT                                      │
│  • Executes approved tasks sequentially or in parallel  │
│  • Calls tools and makes code changes                   │
│  • Validates results                                    │
│  • Applies recommendations from Review Agent            │
└──────────────────────────────────────────────────────────┘
```

### How It Works

**1. Planning Phase** - The Planning Agent analyzes your request
```bash
rev "Add user authentication with JWT"
```

The Planning Agent will:
- Analyze your repository structure
- Break down the request into specific tasks
- Identify dependencies between tasks
- Assess risks for each task
- **Handle recursive breakdown** for complex features

**End-to-end flow (Planning ➜ Review ➜ Execution)**

1. `rev "<task>"` kicks off the **planning phase** to draft a full execution plan.
2. The **review phase** evaluates completeness, safety, and risk before any edits occur.
3. The **execution phase** applies the approved steps with validations and tests, stopping on failures and surfacing actionable errors.

This flow runs automatically for every request, ensuring the plan, review, and execution steps all complete instead of stopping after planning.

For example, a high-level task like "Implement authentication system" will be automatically broken down into:
- Design authentication architecture
- Create user model and database schema
- Implement JWT token generation
- Add authentication middleware
- Create login/register endpoints
- Write authentication tests

**2. Review Phase** - The Review Agent validates the plan
```
============================================================
REVIEW AGENT - PLAN REVIEW
============================================================
→ Analyzing plan with review agent...

============================================================
REVIEW RESULTS
============================================================

Decision: ✅ APPROVED WITH SUGGESTIONS
Confidence: 85%

Plan is generally sound but could be improved

💡 Suggestions (3):
  - Add rate limiting to prevent brute force attacks
  - Include password reset functionality
  - Add integration tests for authentication flow

🔒 Security Concerns (1):
  - Ensure JWT secrets are stored in environment variables
============================================================
```

The Review Agent examines:
- **Completeness**: Are all necessary tasks included?
- **Security**: Are there potential vulnerabilities?
- **Best Practices**: Does the plan follow industry standards?
- **Edge Cases**: Are error cases handled?
- **Dependencies**: Are task dependencies correct?

**3. Execution Phase** - The Execution Agent runs the tasks
- Each task is executed with full context
- **Optional**: Action-level review can validate each tool call
- Results are validated and tested

### Review Modes

**Plan Review** (Default: Enabled)
```bash
# Enable plan review (default)
rev "Add authentication"

# Disable plan review
rev --no-review "Add authentication"

# Adjust review strictness
rev --review-strictness strict "Delete old migrations"
rev --review-strictness lenient "Add logging"
```

Strictness levels:
- **Lenient**: Only flags critical issues
- **Moderate** (default): Flags medium+ severity issues
- **Strict**: Flags all potential issues

**Action Review** (Optional: Disabled by default)
```bash
# Enable action-level review (reviews each tool call)
rev --action-review "Implement payment processing"
```

Action review provides real-time validation:
- Detects command injection vulnerabilities
- Identifies hardcoded secrets
- Warns about SQL injection risks
- Suggests alternative approaches
- Validates file operations

### Review Decision Types

The Review Agent can make four types of decisions:

**✅ APPROVED** - Plan is safe and complete
```
✅ Plan approved by review agent.
```

**✅ APPROVED WITH SUGGESTIONS** - Plan is good but has recommendations
```
✅ Plan approved with suggestions. Review recommendations above.

💡 Suggestions:
  - Add error handling for edge cases
  - Consider adding validation tests
```

**⚠️ REQUIRES CHANGES** - Plan has issues that should be addressed
```
⚠️ Plan requires changes. Review the issues above.
Continue anyway? (y/N):
```

**❌ REJECTED** - Plan has critical issues
```
❌ Plan rejected by review agent. Please revise your request.

🔴 Issues:
  - CRITICAL: Hardcoded database credentials
  - HIGH: Missing input validation
```

### Benefits of Multi-Agent System

**🛡️ Enhanced Security**
- Automatic detection of security vulnerabilities
- Multiple layers of validation before code changes
- Quick security checks without LLM calls (command injection, secrets, etc.)

**🎯 Better Accuracy**
- Identifies missing tasks before execution
- Catches logical errors in plans
- Suggests improvements and alternative approaches

**📚 Complex Task Handling**
- Recursive breakdown for large features
- Automatic decomposition of high-complexity tasks
- Better handling of multi-step implementations

**⚡ Smart Defaults**
- Auto-approves low-risk plans (review only, read-only operations)
- Focuses review effort on high-risk changes
- Configurable strictness for different scenarios

### Example: Complex Feature with Review

```bash
rev "Implement a REST API for user management with authentication, validation, and tests"
```

**Planning Agent Output:**
```
→ Checking for complex tasks...
  ├─ Breaking down complex task: Implement REST API authentication...
     └─ Expanded into 8 subtasks

EXECUTION PLAN
1. [REVIEW] Analyze current project structure
2. [ADD] Create user model with validation
3. [ADD] Implement JWT authentication middleware
4. [ADD] Create user registration endpoint
5. [ADD] Create user login endpoint
6. [ADD] Add password hashing utilities
7. [ADD] Write unit tests for authentication
8. [ADD] Write integration tests for API endpoints
9. [TEST] Run full test suite
```

**Review Agent Output:**
```
REVIEW RESULTS

Decision: ✅ APPROVED WITH SUGGESTIONS
Confidence: 90%

Plan provides comprehensive REST API implementation

💡 Suggestions (3):
  - Add rate limiting to login endpoint
  - Include password reset functionality
  - Add API documentation (OpenAPI/Swagger)

🔒 Security Concerns (2):
  - Ensure JWT secrets use environment variables
  - Add HTTPS requirement for production
```

**The quorum ensures:**
- Planning Agent decomposes the complex request
- Review Agent validates completeness and security
- Execution Agent implements with confidence

### Configuration Options

```bash
# Full control over review behavior
rev \
  --review \                      # Enable plan review (default)
  --review-strictness moderate \  # Set strictness level
  --action-review \               # Enable action-level review
  "Your complex task"

# Minimal review for simple tasks
rev \
  --review-strictness lenient \
  "Update documentation"

# Maximum scrutiny for critical changes
rev \
  --review-strictness strict \
  --action-review \
  "Migrate database schema"
```

**Best Practices with Multi-Agent System:**

1. **Use default settings** for most tasks - they provide good balance
2. **Enable action review** for security-critical operations (auth, payments, database)
3. **Use strict mode** when working with production code or critical infrastructure
4. **Use lenient mode** for documentation updates or low-risk refactoring
5. **Review suggestions** even when approved - they often provide valuable insights

## Best Practices

1. **Be Specific** — Clearer requests generate better plans
   - ✗ "Fix the code"
   - ✓ "Add null checks to user input validation in api/users.js"

2. **Start Small** — Test with simple tasks first
   - ✗ "Rewrite entire authentication system"
   - ✓ "Add password strength validation"

3. **Use Appropriate Models**
   - Small tasks: `codellama:7b` (fast)
   - Complex refactoring: `codellama:34b` or `deepseek-coder:33b`

4. **Review Changes** — Use `git diff` before committing
   ```bash
   rev "Add feature X"
   git diff  # Review changes
   git commit -am "Add feature X"
   ```

5. **Iterative Development** — Use REPL for interactive work
   ```bash
   rev --repl
   ```

6. **Documentation First** — Review documentation before making changes
   - Use `rev "Review all documentation files"` to understand the codebase
   - Keep documentation updated alongside code changes
   - Add docstrings and inline comments for complex logic
   - See [RECOMMENDATIONS.md](RECOMMENDATIONS.md) for documentation improvement ideas

7. **Security Conscious Development** — Follow security best practices
   - Review security recommendations in [RECOMMENDATIONS.md](RECOMMENDATIONS.md)
   - Validate all inputs and sanitize file paths
   - Keep dependencies updated and scan for vulnerabilities
   - Implement least privilege principles for file operations
   - Use secure communication channels for remote execution


## Built-in Utilities

rev includes powerful utility functions for common development tasks:

### File Format Conversion

Convert between common file formats without external tools:

```python
# JSON ↔ YAML
rev "Convert config.json to YAML format"
rev "Convert docker-compose.yaml to JSON"

# CSV ↔ JSON
rev "Convert users.csv to JSON array"
rev "Convert data.json to CSV format"

# .env to JSON
rev "Convert .env to JSON configuration"
```

### Code Refactoring

Automated code analysis and improvement:

```python
# Remove unused imports
rev "Remove unused imports from src/app.py"

# Extract magic numbers to constants
rev "Find magic numbers in config.py that should be constants"

# Simplify complex conditionals
rev "Analyze validator.py for overly complex if statements"
```

### Dependency Management

Multi-language dependency analysis and updates:

```python
# Analyze dependencies (auto-detects Python/JavaScript/Rust/Go)
rev "Analyze project dependencies and check for issues"

# Check for outdated packages
rev "Check for outdated dependencies"
rev "Find outdated packages including major version updates"
```

### Security Scanning

Comprehensive security analysis:

```python
# Scan for vulnerabilities
rev "Scan dependencies for known security vulnerabilities"

# Static code security analysis
rev "Run security scan on src/ directory"

# Detect secrets
rev "Scan repository for accidentally committed secrets"

# Check license compliance
rev "Check dependency licenses for GPL and restrictive licenses"
```

**See [UTILITIES.md](UTILITIES.md) for complete documentation, API reference, and integration examples.**

## Intelligent Caching

rev includes a high-performance caching system that dramatically improves speed by caching frequently accessed data:

### Cache Types

**File Content Cache** (60s TTL)
- Caches file contents with automatic invalidation on file modification
- 10-100x faster for repeatedly accessed files

**LLM Response Cache** (1 hour TTL)
- Caches identical LLM queries to avoid redundant API calls
- Near-instant responses for repeated questions
- Significant cost savings for cloud models

**Repository Context Cache** (30s TTL)
- Caches git status, logs, and file trees
- Invalidates automatically on new commits
- 5-20x faster for repository queries

**Dependency Tree Cache** (10 min TTL)
- Caches dependency analysis results
- Invalidates when dependency files change
- 10-50x faster for dependency operations

### Usage

```bash
# View cache statistics
rev "Show cache statistics"

# Clear caches (useful after major changes)
rev "Clear all caches"
rev "Clear LLM response cache"

# Caches persist automatically to .rev/cache/
```

### Performance Impact

Real-world improvements:
- **File reads:** 10-40x faster (repeated access)
- **Repo context:** 20-100x faster
- **Dependency analysis:** 40-200x faster
- **Identical LLM queries:** 400-2000x faster

**Overall:** 30-50% faster development iteration cycles, 40-60% reduction in cloud API costs.

**See [CACHING.md](CACHING.md) for complete documentation, configuration options, and optimization tips.**

## Advanced Usage

### Custom Test Commands

The agent detects test frameworks automatically, but you can customize:

```bash
# For Python projects
rev "Fix failing tests" --model qwen3-coder:480b-cloud

# For Node.js projects
rev "Add tests for new API endpoints"
```

### Chain Multiple Tasks

```bash
rev "Add logging, then refactor error handling, then update tests"
```

The agent will create a plan that sequences these correctly.

### CI/CD Integration

```bash
# In your CI pipeline
rev --yes "Run tests and fix any linting errors"
if [ $? -eq 0 ]; then
  git commit -am "Auto-fix linting issues"
  git push
fi
```

### Packaging & Releases

Automate release builds with `build.ps1` (and the cross-platform `build.sh`) which stamps the git commit, builds packages, and optionally uploads to PyPI.

- Before building, `build.ps1` runs `Stamp-GitCommit` so the constant `REV_GIT_COMMIT` in `rev/_version.py` reflects the current HEAD. When `python -m rev --version` (or `rev --version`) runs later, `rev.versioning.build_version_output()` includes that commit hash even if the installed wheel lacks git metadata.
- `Build-Wheel` installs the `build` module if missing and then calls `python -m build`. `Publish-Package` ensures `twine` is available before uploading, so the script no longer fails with `No module named build` or `twine` errors.
- Run `.\build.ps1 -Publish` (or the equivalent `build.sh`) to stamp the commit, build wheels/sdists, and push packages via `twine`. Point `TWINE_USERNAME`/`TWINE_PASSWORD` at your PyPI credentials (or configure `~/.pypirc`) before publishing.
- If Git is unavailable (e.g., packaging from a source archive), stamping is skipped and `REV_GIT_COMMIT` stays at its previous value or the fallback `"unknown"`.

```
.\build.ps1 -Publish    # stamp commit, build wheel + sdist, upload via twine
python -m rev --version  # confirm version + commit hash baked into wheel
```

## Allowed Commands

For security, only these commands are permitted:

- **Python**: `python`, `pip`, `pytest`, `ruff`, `black`, `isort`, `mypy`
- **JavaScript**: `node`, `npm`, `npx`, `pnpm`, `prettier`, `eslint`
- **Version Control**: `git`
- **Build**: `make`

## File Structure

```
.
├── rev/             # Package (CLI entry: `rev`)
├── requirements.txt       # Minimal dependencies (just requests)
├── tests/                 # Comprehensive test suite (planning, review, execution)
│   ├── test_agent.py      # Core agent behavior
│   ├── test_advanced_planning.py  # Multi-agent planning and validation
│   └── ...                # Additional integration and tool tests
├── COVERAGE.md            # Detailed coverage report
├── RECOMMENDATIONS.md     # Future improvement suggestions
└── README.md              # This file
```

## License

MIT

## Contributing

Contributions are welcome! This is a production-grade agentic development system focused on autonomous workflows with comprehensive analysis capabilities.

For feature requests or bug reports, please open an issue on GitHub.
