# rev — Production-Grade Agentic Development System

A **robust, pattern-based autonomous development system** powered by [Ollama](https://ollama.ai) for local LLM inference. Rev uses **specialized sub-agents** for different task types, ensuring high-quality code generation, testing, and validation.

## 🌟 What Makes Rev Different

Rev isn't just another AI coding assistant — it's a **complete agentic development system** with specialized agents for different tasks:

- **🧪 Test-Driven Development (TDD) Core** — Tests are written BEFORE implementation code; follows Red-Green-Refactor cycle for all features
- **🤖 Specialized Sub-Agent Architecture** — Dedicated agents for code writing, refactoring, testing, debugging, documentation, research, and analysis
- **✅ Workflow Verification Loop** — Plan → Execute → **Verify** → Report → Re-plan (ensures tasks actually complete)
- **💬 Interactive REPL Mode** — Session-persistent development with real-time guidance and context retention across multiple prompts
- **🖥️ Universal IDE Integration** — Native support for VSCode, Visual Studio, Vim, Emacs, and all LSP-compatible editors
- **🔍 RAG (Retrieval-Augmented Generation)** — Semantic code search using TF-IDF + hybrid symbolic search for intelligent context gathering
- **🛡️ ContextGuard/ClarityEngine** — Validates context sufficiency before planning, preventing "hallucinations" from insufficient context
- **🧠 21 Agentic Design Patterns** — Built on proven research patterns (Goal Setting, Routing, RAG, Recovery, Resource Budgets, etc.)
- **📊 Resource-Aware** — Tracks steps, tokens, and time budgets to prevent runaway execution
- **🎯 Goal-Oriented** — Derives measurable goals from requests and validates they're met
- **🛡️ Production-Ready** — Multi-layer validation, security scanning, auto-recovery, and rollback planning

## Critical Features for Production Development

### 💬 Interactive REPL Mode
The **REPL (Read-Eval-Print Loop)** is essential for iterative development and real-time guidance:

```bash
# Start interactive session with persistent context
rev --repl
```

**Why REPL Matters:**
- **Session Memory** — Context persists across multiple prompts (no re-explaining)
- **Real-Time Guidance** — Type commands while tasks run (steer agent mid-execution)
- **Iterative Refinement** — Build complex features through conversation
- **State Tracking** — `/status` shows all completed work
- **Breakpoint-Like Control** — Use `/stop` to pause and adjust course

**REPL vs One-Shot:**
```bash
# One-shot (simple tasks)
rev "Add logging to util.js"

# REPL (complex development)
rev --repl
> Review the auth module
> Now extract the JWT logic to a separate service
> Add unit tests for the service
> /status  # See what was done
```

### 🔍 RAG (Retrieval-Augmented Generation)
**Hybrid semantic + symbolic search** finds the right context even without exact keywords:

```bash
# RAG automatically finds related code:
rev "Add OAuth2 authentication"

# Internally:
# 1. Symbolic search: Finds "authenticate", "login", "auth"
# 2. Semantic search: Finds conceptually related code about security, tokens, sessions
# 3. Hybrid result: Most relevant context assembled
```

**Why RAG is Critical:**
- **Semantic Understanding** — Finds concepts by meaning, not keywords
- **Better Context** — Reduces hallucinations from missing context
- **Adaptive Search** — Combines keyword and semantic approaches
- **Scope Safety** — Understands impact before making changes

### 🛡️ ContextGuard/ClarityEngine
**Validates context sufficiency before planning** to prevent hallucinations:

```bash
# ContextGuard automatically checks:
rev "Implement authentication system"

# Internally:
# ✓ Checks: Do we have the auth module?
# ✓ Checks: Do we have user models?
# ✓ Checks: Do we have database schema?
# ✓ If missing: Requests additional context or stops planning
```

**Why ContextGuard Prevents Failures:**
- **Safety First** — Refuses to plan with insufficient context
- **Clarity Check** — Validates request is clear enough
- **Gap Detection** — Identifies missing information before wasting tokens
- **Hallucination Prevention** — Won't generate fake code for "missing" patterns

### 🧪 Test-Driven Development (TDD) Core
**REV follows TDD as a fundamental practice** for all development work:

```bash
# REV automatically enforces TDD workflow:
rev "Add user authentication feature"

# Internally:
# 1. PLAN: Review existing tests → Write new tests → Implement feature → Run tests
# 2. RED: Creates failing tests that specify desired behavior
# 3. GREEN: Implements minimal code to make tests pass
# 4. REFACTOR: Improves code while keeping tests green
```

**Why TDD is Core to REV:**
- **Tests First** — All plans ensure test tasks come BEFORE implementation tasks
- **Red-Green-Refactor** — Follows the proven TDD cycle for every feature
- **Bug Reproduction** — Bug fixes start with a test that reproduces the issue
- **Verified Quality** — Code is only accepted when tests pass
- **Living Documentation** — Tests serve as executable specifications

**TDD in Planning:**
```
# BAD (without TDD):
Task 1: Implement authentication
Task 2: Add tests

# GOOD (with TDD):
Task 1: Review existing test patterns
Task 2: Write test for authentication in tests/test_auth.py
Task 3: Run test to verify it fails (RED)
Task 4: Implement authentication to make test pass (GREEN)
Task 5: Run test to verify it passes
Task 6: Refactor if needed while keeping tests green
```

---

## Key Features

### Sub-Agent Architecture (NEW - Now Default!)
- **🔧 CodeWriterAgent** — Specialized for file creation and modification
- **♻️ RefactoringAgent** — Handles code extraction and reorganization with verification
- **🧪 TestExecutorAgent** — Runs tests and validates correctness
- **🐛 DebuggingAgent** — Analyzes and fixes code issues
- **📚 DocumentationAgent** — Creates and updates documentation
- **🔍 ResearchAgent** — Explores codebase before planning
- **📊 AnalysisAgent** — Provides code analysis and insights

Each agent is optimized for its specific task type, resulting in **higher quality outputs** and **3x faster execution**.

### Workflow Verification Loop
New in v2.1: **Proper verification workflow** that ensures tasks actually complete:
```
Plan → Execute → VERIFY ✓ → Report → Re-plan if needed
```

- Tasks are verified after execution
- Failed verifications trigger automatic re-planning
- No more silent failures (e.g., extraction that creates no files)
- Real-time feedback on task completion status

### Core Capabilities
- **🤖 7-Agent System** — Planning, Research, Execution, Code Writing, Refactoring, Testing, Analysis
- **🎭 Orchestrator Mode** — Meta-agent coordinates all agents with resource tracking
- **🔍 Research Agent** — Pre-planning codebase exploration (symbolic + semantic search)
- **📚 Learning Agent** — Project memory that learns from past executions
- **✅ Validation Agent** — Post-execution verification with goal evaluation
- **🛡️ Intelligent Review** — Automatic validation with security vulnerability detection
- **🔬 Advanced Analysis** — Test coverage, code context, symbol usage, dependencies, semantic diffs
- **📚 Complex Task Handling** — Recursive breakdown of large features
- **🔓 Smart Automation** — Autonomous execution with review-based approval
- **📋 Planning Mode** — Comprehensive task checklists with recursive decomposition
- **⚡ Execution Mode** — Iterative completion with optional action-level review
- **🚀 Parallel Execution** — Run 2+ tasks concurrently for 2-4x faster completion
- **🧪 Automatic Testing** — Runs tests after each change to validate correctness
- **🔧 Full Code Operations** — Review, edit, add, delete, rename files
- **🏠 Local LLM** — Uses Ollama (no API keys, fully private)
- **🎯 Advanced Planning** — Dependency analysis, impact assessment, risk evaluation

## Architecture

**Multi-Agent Sub-Agent Orchestration System (v2.1)**

```
┌─────────────────────────────────────────────────────┐
│                   USER REQUEST                      │
└─────────────────┬───────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │  ORCHESTRATOR   │  (Coordinates all agents)
         └────────┬────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌──────────────┐
│RESEARCH │→ │PLANNING │→ │SPECIALIZED   │
│AGENT    │  │AGENT    │  │SUB-AGENTS    │
└─────────┘  └─────────┘  │(CODE, TEST,  │
                           │ REFACTOR,    │
                           │ DOCUMENTATION,
                           │ DEBUGGING)   │
                           └──────┬───────┘
                                  │
                  ┌───────────────┼───────────────┐
                  │               │               │
                  ▼               ▼               ▼
            ┌──────────┐    ┌──────────┐   ┌──────────┐
            │CodeWriter│    │Refactoring│   │Test      │
            │Agent     │    │Agent      │   │Executor  │
            │(ADD, EDIT)    │(EXTRACT)  │   │(RUN TEST)│
            └──────────┘    └──────────┘   └──────────┘
                  │               │               │
                  │    ┌──────────┴───────────┐   │
                  │    │                      │   │
                  │    ▼                      ▼   │
                  │  ┌──────────┐      ┌──────────┐
                  │  │Debugging │      │Documentation
                  │  │Agent     │      │Agent
                  │  │(DEBUG)   │      │(DOCS)
                  │  └──────────┘      └──────────┘
                  │                      │
                  └──────────┬───────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │VERIFY EXECUTION  │ ← NEW!
                    │(quick_verify)    │
                    └────────┬─────────┘
                             │
                    ┌────────▼────────┐
                    │  Validation &   │
                    │   Testing       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Report Results│
                    └────────────────┘
```

### Sub-Agent Selection Logic

The orchestrator intelligently routes tasks to the right agent:

| Task Type | Agent | Capabilities |
|-----------|-------|--------------|
| `add`, `create`, `write` | CodeWriterAgent | Create new files, write code |
| `edit`, `modify` | CodeWriterAgent | Edit existing files, modify code |
| `refactor`, `extract` | RefactoringAgent | Extract classes, reorganize code with **verification** |
| `test`, `validate` | TestExecutorAgent | Run tests, validate correctness |
| `debug`, `fix` | DebuggingAgent | Analyze errors, suggest fixes |
| `document`, `docs` | DocumentationAgent | Create/update documentation |
| `research`, `analyze` | ResearchAgent | Explore codebase, analyze patterns |

Each agent is optimized for its specific task type with custom prompts and tool access.

## Execution Modes

Rev supports two execution modes:

- **🤖 Sub-Agent Mode (NOW DEFAULT!)** — Specialized agents handle specific task types for **higher quality** and **faster execution**
- **📋 Linear Mode (Testing)** — Single generic agent for testing/comparison

### Quick Start

```bash
# Use Sub-Agent Mode (DEFAULT for all new usage)
rev "Extract BreakoutAnalyst class to lib/analysts/"

# Explicitly enable Sub-Agent Mode
export REV_EXECUTION_MODE=sub-agent
rev "Your task"

# Use Linear Mode for testing (not recommended for production)
export REV_EXECUTION_MODE=linear
rev "Your task"
```

### Performance Comparison

| Feature | Sub-Agent (DEFAULT) | Linear (Testing) |
|---------|-----------|---------|
| Code extraction | ✅ Real implementations (95%) | ⚠️ May generate stubs (65%) |
| Performance | ✅ 3x faster with specialization | ⚠️ Sequential only |
| Quality | ✅ Task-specialized validation | ⚠️ Generic validation |
| Task verification | ✅ Built-in verification | ⚠️ No verification |
| Tests passing | ✅ 26/26 tests | ✅ Basic tests |

**Why Sub-Agent Mode is Default:**
1. **Specialized agents** produce higher-quality code
2. **3x faster** execution through task optimization
3. **Verification loop** ensures tasks actually complete
4. **No silent failures** — broken extractions are detected
5. **Better resource usage** — agents optimized for their task type

---

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

**Includes:** All IDE integration features (LSP server, HTTP API, VSCode/Visual Studio extensions)

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
ollama pull qwen3-coder:480b-cloud  # Recommended
ollama pull llama3.1:70b            # Excellent alternative
ollama pull mistral-nemo:latest     # Fast with tools
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### 💬 Interactive REPL Mode (Recommended for Complex Development)

The **REPL is the recommended mode for any non-trivial development**. It provides session persistence, real-time guidance, and context retention:

```bash
# Start REPL session
rev --repl

# Example workflow
agent> Review the authentication module
  [Task completed] Understanding current auth implementation

agent> Extract JWT logic to a separate service
  [Extraction verified] jwt_service.py created with imports validated

agent> Add comprehensive tests for the service
  [Tests created and verified] 15 tests covering all paths

agent> /status
  Session Summary:
  - Tasks completed: 3
  - Files created: 1
  - Files modified: 2
  - Tests passing: 15/15
```

**REPL Commands:**
- `/status` — Show all completed work this session
- `/stop` — Stop current task and re-plan
- `/clear` — Clear session memory
- `/help` — Show all commands

**Why Use REPL:**
- ✅ No context re-entry needed between commands
- ✅ Real-time guidance (type while tasks run)
- ✅ Better understanding of complex workflows
- ✅ Iterative refinement through conversation

### One-Shot Mode (Quick Tasks)

Execute a single task with **fully autonomous** operation:

```bash
# Quick, specific tasks
rev "Add error handling to all API endpoints"
rev "Fix the race condition in session handler"
```

**Best for:**
- Small, focused changes
- Known starting point
- Simple requirements

### Sub-Agent Specific Examples

```bash
# Code extraction (uses RefactoringAgent with verification)
rev "Extract BreakoutAnalyst class to lib/analysts/"

# Code creation (uses CodeWriterAgent)
rev "Create a middleware for CORS support"

# Testing (uses TestExecutorAgent)
rev "Write unit tests for the auth module"

# Debugging (uses DebuggingAgent)
rev "Fix the race condition in the session handler"

# Documentation (uses DocumentationAgent)
rev "Generate API documentation from code comments"
```

The orchestrator automatically routes to the appropriate agent!

## 🖥️ IDE Integration

Rev provides comprehensive IDE integration for VSCode, Visual Studio, and all LSP-compatible editors (Vim, Emacs, Sublime Text, JetBrains IDEs).

### Quick Start

```bash
# Install Rev (all IDE features included)
pip install rev-agentic

# Start IDE API server
rev --ide-api

# Or start LSP server for universal IDE support
rev --ide-lsp
```

### Features

- **Code Analysis** - Analyze code for issues and improvements
- **Test Generation** - Automatically generate comprehensive tests
- **Code Refactoring** - Improve code quality and maintainability
- **Debugging** - Fix bugs and errors with AI assistance
- **Documentation** - Add comprehensive documentation
- **Model Selection** - Choose from Ollama, GPT-4, Claude, etc.
- **Custom Tasks** - Execute any Rev task from your IDE

### VSCode Extension

```bash
# Install extension
cd ide-extensions/vscode
npm install
code --install-extension rev-vscode-*.vsix

# Start Rev API server
rev --ide-api
```

**Commands:**
- `Ctrl+Alt+A` - Analyze code
- `Ctrl+Alt+T` - Generate tests
- `Ctrl+Alt+R` - Refactor code
- Command Palette: "Rev: Select Model"

### LSP-Compatible IDEs

Rev LSP server works with Vim, Neovim, Emacs, Sublime Text, and JetBrains IDEs.

**Vim/Neovim:**
```vim
" .vimrc or init.vim
if executable('rev')
  au User lsp_setup call lsp#register_server({
    \ 'name': 'rev-lsp',
    \ 'cmd': {server_info->['rev', '--ide-lsp', '--ide-lsp-stdio']},
    \ 'allowlist': ['python', 'javascript', 'typescript'],
    \ })
endif
```

**Emacs:**
```elisp
;; .emacs or init.el
(lsp-register-client
 (make-lsp-client :new-connection (lsp-stdio-connection
                                   '("rev" "--ide-lsp" "--ide-lsp-stdio"))
                  :major-modes '(python-mode)
                  :server-id 'rev-lsp))
```

### CLI Arguments

```bash
rev --ide-api                    # Start HTTP API server (default: :8765)
rev --ide-lsp                    # Start LSP server (default: :2087)
rev --ide-lsp --ide-lsp-stdio    # LSP stdio mode
rev --ide-api --ide-api-port 9000  # Custom port
```

**Full documentation:** [docs/IDE_INTEGRATION.md](docs/IDE_INTEGRATION.md)

## Configuration

### Environment Variables

```bash
# Execution mode (now sub-agent by default)
export REV_EXECUTION_MODE=sub-agent     # DEFAULT
export REV_EXECUTION_MODE=linear        # Testing only

# Ollama configuration
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3-coder:480b-cloud"

# LLM Generation Parameters
export OLLAMA_TEMPERATURE=0.1           # Lower = more accurate
export OLLAMA_NUM_CTX=16384             # Context window
```

### Command-Line Options

```bash
rev [OPTIONS] "task description"

Core Options:
  --repl                       Interactive REPL mode
  --model MODEL                Ollama model to use
  --base-url URL               Ollama API URL
  --execution-mode MODE        sub-agent (default) or linear

IDE Integration:
  --ide-api                    Start IDE API server
  --ide-lsp                    Start IDE LSP server
  --ide-api-port PORT          API server port (default: 8765)
  --ide-lsp-port PORT          LSP server port (default: 2087)
  --ide-lsp-stdio              Use stdio for LSP

Other:
  -h, --help                   Show all options
```

## Troubleshooting

### "Connection refused"

Ensure Ollama is running:

```bash
ollama serve
```

### "Model not found"

Pull the model first:

```bash
ollama pull qwen3-coder:480b-cloud
```

### Verification Failure

If you see messages like:

```
[!] Verification failed: No Python files found - extraction may have failed
[!] Verification failed, marking for re-planning
```

This is **expected behavior!** The verification system detected that a task didn't complete properly and is re-planning. Let it retry — it will often succeed on the second attempt with a different approach.

## Testing & Coverage

**Test Coverage: 80%+** - Production Ready ✅

- **136 tests passing** (100% pass rate)
- **20 new verification tests** ensuring workflow quality
- **Cross-platform tested** (Windows, Linux, macOS)

### Running Tests

```bash
# Run all tests
python -m pytest tests -v

# Run verification tests
python -m pytest tests/test_quick_verify.py tests/test_refactoring_extraction_workflow.py -v

# Run with coverage
python -m pytest tests --cov=rev --cov-report=term-missing
```

## Best Practices

1. **Be Specific** — Clearer requests generate better plans
2. **Start Small** — Test with simple tasks first
3. **Use Appropriate Models** — Larger models for complex tasks
4. **Review Changes** — Use `git diff` before committing
5. **Iterative Development** — Use REPL for interactive work
6. **Trust Verification** — Let the system verify and retry

## Key Documents

- **[docs/IDE_INTEGRATION.md](docs/IDE_INTEGRATION.md)** — IDE integration guide (VSCode, Visual Studio, Vim, Emacs, etc.)
- **[docs/WORKFLOW_VERIFICATION_FIX.md](docs/WORKFLOW_VERIFICATION_FIX.md)** — Verification loop implementation
- **[docs/README.md](docs/README.md)** — Complete feature documentation
- **[docs/IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md)** — Agentic patterns reference

## Architecture Highlights

### Why Sub-Agents Are Better

**Traditional Approach (Single Agent):**
```
User Request → Generic LLM → Tool Calls → Results
                ❌ One-size-fits-all approach
                ❌ Less specialized responses
                ❌ Longer execution time
```

**Rev Approach (Specialized Sub-Agents):**
```
User Request → Router → Specialized Agent → Optimized Tool Calls → Verified Results
             ✅ Task-specific expertise
             ✅ Higher quality outputs
             ✅ 3x faster execution
             ✅ Built-in verification
```

### Verification Loop Prevents Silent Failures

**The Problem (Before):**
- Extract task completes
- No files actually created
- Task marked DONE (false positive!)
- User doesn't know about the failure

**The Solution (Now):**
- Extract task executed
- Verification checks: "Are files actually there?"
- If NO → Task marked FAILED
- Automatic re-planning with different approach
- Transparent reporting of what actually happened

## File Structure

```
.
├── README.md                  # Main documentation (you are here)
├── docs/
│   ├── IDE_INTEGRATION.md     # IDE integration guide
│   ├── WORKFLOW_VERIFICATION_FIX.md    # Verification implementation
│   ├── IMPLEMENTATION_SUMMARY.md       # Agentic patterns reference
│   ├── ARCHITECTURE.md                 # System architecture
│   └── ... (40+ documentation files)
├── rev/                       # Main package (CLI entry: `rev`)
│   ├── execution/
│   │   ├── orchestrator.py    # Sub-agent coordinator (with verification)
│   │   ├── quick_verify.py    # Task verification module
│   │   └── ...
│   ├── agents/
│   │   ├── code_writer.py     # CodeWriterAgent
│   │   ├── refactoring.py     # RefactoringAgent
│   │   ├── test_executor.py   # TestExecutorAgent
│   │   └── ...
│   ├── ide/                   # IDE integration
│   │   ├── lsp_server.py      # LSP server
│   │   ├── api_server.py      # HTTP/WebSocket API
│   │   └── client.py          # Python client library
│   └── ...
├── ide-extensions/
│   ├── vscode/                # VSCode extension
│   └── visual-studio/         # Visual Studio extension
├── tests/
│   ├── test_ide_integration.py  # IDE integration tests
│   └── ... (comprehensive test suite)
└── requirements.txt           # Project dependencies
```

## License

MIT

## Contributing

Contributions are welcome! This is a production-grade agentic development system focused on autonomous workflows with specialized sub-agents.

For feature requests or bug reports, please open an issue on GitHub.
