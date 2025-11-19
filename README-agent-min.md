# agent.min — Autonomous CI/CD Agent

A minimal, autonomous CI/CD agent powered by [Ollama](https://ollama.ai) for local LLM inference. Designed for iterative code development with single-gate approval and comprehensive testing.

## Key Features

- **🔓 Single-Gate Approval** — One approval at start, then runs autonomously (no repeated prompts)
- **📋 Planning Mode** — Analyzes your request and generates comprehensive task checklist
- **⚡ Execution Mode** — Iteratively completes all tasks until done
- **🧪 Automatic Testing** — Runs tests after each change to validate correctness
- **🔧 Full Code Operations** — Review, edit, add, delete, rename files
- **🏠 Local LLM** — Uses Ollama (no API keys, fully private)
- **📦 Minimal Dependencies** — Just `requests` library

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

**⚠️ Important:** agent.min requires a model with **function/tool calling support** for full functionality.

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

**Verify tool support:**
```bash
# List models
ollama list

# Check model info
ollama show llama3.1:latest
```

### 3. Install Dependencies

```bash
pip install -r requirements-min.txt
```

## Usage

### One-Shot Mode

Execute a single task with **fully autonomous** operation:

```bash
python agent.min "Add error handling to all API endpoints"
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
python agent.min --repl
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
python agent.min --prompt "Run all tests and fix any failures"
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
python agent.min "Your task here"
```

### Command-Line Options

```bash
python agent.min [OPTIONS] "task description"

Options:
  --repl              Interactive REPL mode
  --model MODEL       Ollama model to use (default: codellama:latest)
  --base-url URL      Ollama API URL (default: http://localhost:11434)
  --yes               Auto-approve execution (no confirmation prompt)
  -h, --help          Show help message
```

## Examples

### Example 1: Add Feature

```bash
python agent.min "Add rate limiting middleware to Express app"
```

**Generated Plan:**
1. [REVIEW] Analyze current Express middleware structure
2. [ADD] Create rate-limiting middleware module
3. [EDIT] Integrate rate limiter into main app
4. [ADD] Add tests for rate limiting
5. [TEST] Run test suite to validate

### Example 2: Fix Bugs

```bash
python agent.min "Fix all ESLint errors in src/ directory"
```

**Generated Plan:**
1. [REVIEW] Run ESLint to identify all errors
2. [EDIT] Fix import order issues
3. [EDIT] Fix unused variable warnings
4. [EDIT] Fix indentation errors
5. [TEST] Run ESLint again to verify fixes

### Example 3: Refactoring

```bash
python agent.min "Refactor authentication logic into separate service"
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

The agent has access to:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Create or overwrite files |
| `list_dir` | List files matching glob pattern |
| `search_code` | Search code with regex |
| `git_diff` | View current uncommitted changes |
| `apply_patch` | Apply unified diff patches |
| `run_cmd` | Execute shell commands |
| `run_tests` | Run test suite (pytest, npm test, etc.) |
| `get_repo_context` | Get git status and repo structure |

## Comparison with agent.py

| Feature | agent.py | agent.min |
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
   python agent.min --model llama3.1:latest "Your task"
   ```

2. Or enable debug mode to see what's happening:
   ```bash
   OLLAMA_DEBUG=1 python agent.min "Your task"
   ```

The agent will automatically retry without tools if it detects the model doesn't support them, but tool support is highly recommended for best results.

### "Path escapes repo"

agent.min only operates within the current repository for safety. Use relative paths.

### Tasks not completing

Try a more specific request or use a larger model:

```bash
python agent.min --model deepseek-coder:33b "Your task"
```

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
   python agent.min "Add feature X"
   git diff  # Review changes
   git commit -am "Add feature X"
   ```

5. **Iterative Development** — Use REPL for interactive work
   ```bash
   python agent.min --repl
   ```

## Advanced Usage

### Custom Test Commands

The agent detects test frameworks automatically, but you can customize:

```bash
# For Python projects
python agent.min "Fix failing tests" --model codellama:latest

# For Node.js projects
python agent.min "Add tests for new API endpoints"
```

### Chain Multiple Tasks

```bash
python agent.min "Add logging, then refactor error handling, then update tests"
```

The agent will create a plan that sequences these correctly.

### CI/CD Integration

```bash
# In your CI pipeline
python agent.min --yes "Run tests and fix any linting errors"
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
├── agent.min              # Main agent script
├── requirements-min.txt   # Minimal dependencies
└── README-agent-min.md    # This file
```

## License

MIT

## Contributing

This is a minimal implementation focused on core CI/CD workflows. For advanced features (SSH, WinRM, HTTP client, secrets management), see the full `agent.py`.

## Credits

Based on the hawk-ops-ai framework, streamlined for autonomous CI/CD workflows with Ollama integration.
