# rev.py — Autonomous CI/CD Agent

A minimal, autonomous CI/CD agent powered by [Ollama](https://ollama.ai) for local LLM inference. Designed for iterative code development with single-gate approval and comprehensive testing.

## Key Features

- **🔓 Single-Gate Approval** — One approval at start, then runs autonomously (no repeated prompts)
- **📋 Planning Mode** — Analyzes your request and generates comprehensive task checklist
- **⚡ Execution Mode** — Iteratively completes all tasks until done
- **🚀 Parallel Execution** — Run 2+ tasks concurrently for 2-4x faster completion
- **🧪 Automatic Testing** — Runs tests after each change to validate correctness
- **🔧 Full Code Operations** — Review, edit, add, delete, rename files
- **🏠 Local LLM** — Uses Ollama (no API keys, fully private)
- **📦 Minimal Dependencies** — Just `requests` library
- **🎯 Advanced Planning** — Dependency analysis, impact assessment, risk evaluation, rollback planning (NEW!)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   USER REQUEST                      │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│              PLANNING MODE                          │
│  • Analyze repository context                      │
│  • Break down request into atomic tasks            │
│  • Generate ordered execution checklist            │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│           SINGLE APPROVAL GATE                      │
│  Press [y] to approve autonomous execution          │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│             EXECUTION MODE (Iterative)              │
│  For each task:                                     │
│    1. Analyze current task                          │
│    2. Gather information (read/search files)        │
│    3. Make changes (edit/add/delete)                │
│    4. Run tests to validate                         │
│    5. Mark complete and move to next                │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│               FINAL SUMMARY                         │
│  ✓ Tasks completed  ✗ Tasks failed                 │
└─────────────────────────────────────────────────────┘
```

## Installation

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows - Download from https://ollama.ai
```

### 2. Pull a Code Model

**⚠️ Important:** rev.py requires a model with **function/tool calling support** for full functionality.

**Recommended models with tool support:**
```bash
# Best for code tasks
ollama pull llama3.1:latest        # Best overall (tool support)
ollama pull qwen2.5:7b              # Good for code (tool support)
ollama pull mistral-nemo:latest     # Fast with tools

# Legacy (no tool support - limited functionality)
ollama pull codellama:latest        # ⚠️ No tool support
ollama pull deepseek-coder:latest   # ⚠️ Check version for tool support
```

**🌐 Ollama Cloud Models (NEW!):**
```bash
# Use powerful cloud-hosted models (requires authentication)
python rev.py --model qwen3-coder:480b-cloud "Your task"
python rev.py --model llama3.3:90b-cloud "Complex refactoring task"
```

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
python rev.py "Add error handling to all API endpoints"
```

The agent will:
1. Analyze your repository
2. Generate an execution plan
3. **Execute autonomously** (no approval needed)
4. Prompt ONLY for destructive operations (delete, force push, etc.)
5. Show final summary

**New in v2: Autonomous by default!** No more repeated approval prompts. The agent only asks permission for potentially destructive operations.

### Interactive REPL

For iterative development with **session memory**:

```bash
python rev.py --repl
```

The REPL now maintains context across multiple prompts:

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

### Manual Approval Mode

If you want to manually approve the execution plan (old behavior):

```bash
python rev.py --prompt "Run all tests and fix any failures"
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
export OLLAMA_MODEL="codellama:latest"           # Default

# Then run agent
python rev.py "Your task here"
```

### Command-Line Options

```bash
python rev.py [OPTIONS] "task description"

Options:
  --repl              Interactive REPL mode
  --model MODEL       Ollama model to use (default: codellama:latest)
  --base-url URL      Ollama API URL (default: http://localhost:11434)
  --prompt            Prompt for approval before execution (default: auto-approve)
  -j N, --parallel N  Number of concurrent tasks (default: 2, use 1 for sequential)
  -h, --help          Show help message
```

### Parallel Execution

**New in v3.0:** Concurrent task execution for faster completion!

By default, rev.py now runs **2 tasks in parallel** when they don't have dependencies on each other. This dramatically speeds up execution for complex tasks.

**Examples:**

```bash
# Use default (2 concurrent tasks)
python rev.py "Review all API endpoints and add tests"

# Run 4 tasks in parallel for maximum speed
python rev.py -j 4 "Refactor all components and update tests"

# Run sequentially (old behavior) for debugging
python rev.py -j 1 "Complex refactoring that needs careful sequencing"

# Run 8 tasks in parallel for large codebases
python rev.py -j 8 "Update all imports across the project"
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
python rev.py "Add rate limiting middleware to Express app"
```

**Generated Plan:**
1. [REVIEW] Analyze current Express middleware structure
2. [ADD] Create rate-limiting middleware module
3. [EDIT] Integrate rate limiter into main app
4. [ADD] Add tests for rate limiting
5. [TEST] Run test suite to validate

### Example 2: Fix Bugs

```bash
python rev.py "Fix all ESLint errors in src/ directory"
```

**Generated Plan:**
1. [REVIEW] Run ESLint to identify all errors
2. [EDIT] Fix import order issues
3. [EDIT] Fix unused variable warnings
4. [EDIT] Fix indentation errors
5. [TEST] Run ESLint again to verify fixes

### Example 3: Refactoring

```bash
python rev.py "Refactor authentication logic into separate service"
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

The agent has access to **36 powerful tools** across multiple categories:

**New in v2.7:** SSH remote execution! Connect to remote hosts, execute commands, and transfer files for managing your infrastructure.

**New in v2.6:** Cross-platform OS detection! The agent automatically detects your operating system (Windows, Linux, macOS) and adapts tool usage accordingly - choosing bash vs PowerShell, correct path separators, and platform-specific commands.

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
| `search_code` | Search code with regex |

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

**New in v2.5:** MCP support allows the agent to connect to external tools and data sources through the Model Context Protocol, enabling integration with databases, APIs, and other development tools.

## Comparison with agent.py

| Feature | agent.py | rev.py |
|---------|----------|-----------|
| **LLM** | OpenAI API | Ollama (local) |
| **Approval** | Multiple prompts | Single approval |
| **Planning** | None | Comprehensive |
| **Execution** | Manual steps | Autonomous iteration |
| **Testing** | Manual | Automatic |
| **Privacy** | API calls | Fully local |
| **Cost** | Pay per token | Free |

## Troubleshooting

### "Ollama API error: Connection refused"

Ensure Ollama is running:

```bash
ollama serve
```

### "Model not found"

Pull the model first:

```bash
ollama pull codellama:latest
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
python rev.py --model qwen3-coder:480b-cloud "Review code"

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
   python rev.py --model llama3.1:latest "Your task"
   ```

2. Or enable debug mode to see what's happening:
   ```bash
   OLLAMA_DEBUG=1 python rev.py "Your task"
   ```

The agent will automatically retry without tools if it detects the model doesn't support them, but tool support is highly recommended for best results.

### "Path escapes repo"

rev.py only operates within the current repository for safety. Use relative paths.

### Tasks not completing

Try a more specific request or use a larger model:

```bash
python rev.py --model deepseek-coder:33b "Your task"
```

## Testing & Coverage

**Test Coverage: 80%** - Production Ready ✅

- **136 tests passing** (100% pass rate)
- **800+ statements** in rev.py
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

### Running Tests

```bash
# Run all tests
python -m pytest tests/test_agent_min.py -v

# Run with coverage report
python -m pytest tests/test_agent_min.py --cov=agent_min --cov-report=term-missing

# Generate HTML coverage report
python -m pytest tests/test_agent_min.py --cov=agent_min --cov-report=html
```

For detailed coverage information, see [COVERAGE.md](COVERAGE.md).

For future testing and quality improvements, see [RECOMMENDATIONS.md](RECOMMENDATIONS.md).

## Advanced Planning

rev.py includes sophisticated planning capabilities that analyze your tasks before execution:

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
   python rev.py "Add feature X"
   git diff  # Review changes
   git commit -am "Add feature X"
   ```

5. **Iterative Development** — Use REPL for interactive work
   ```bash
   python rev.py --repl
   ```

6. **Check Risk Warnings** — Pay attention to high-risk task warnings
   - Review rollback plans before proceeding
   - Test high-risk operations in safe environment first
   - Ensure backups are current for critical operations

## Advanced Usage

### Custom Test Commands

The agent detects test frameworks automatically, but you can customize:

```bash
# For Python projects
python rev.py "Fix failing tests" --model codellama:latest

# For Node.js projects
python rev.py "Add tests for new API endpoints"
```

### Chain Multiple Tasks

```bash
python rev.py "Add logging, then refactor error handling, then update tests"
```

The agent will create a plan that sequences these correctly.

### CI/CD Integration

```bash
# In your CI pipeline
python rev.py --yes "Run tests and fix any linting errors"
if [ $? -eq 0 ]; then
  git commit -am "Auto-fix linting issues"
  git push
fi
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
├── rev.py           # Main agent script
├── requirements.txt       # Minimal dependencies (just requests)
├── tests/                 # Comprehensive test suite
│   └── test_agent_min.py  # 99% coverage tests
├── COVERAGE.md            # Detailed coverage report
├── RECOMMENDATIONS.md     # Future improvement suggestions
└── README.md              # This file
```

## License

MIT

## Contributing

This is a minimal implementation focused on core CI/CD workflows. For advanced features (SSH, WinRM, HTTP client, secrets management), see the full `agent.py`.

## Credits

Based on the hawk-ops-ai framework, streamlined for autonomous CI/CD workflows with Ollama integration.
