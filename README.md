# rev — Production-Grade Agentic Development System

A **robust, pattern-based autonomous development system** powered by **7 LLM providers** including Ollama, OpenAI, Anthropic, Gemini, LocalAI, vLLM, and LMStudio. Rev uses **specialized sub-agents** for different task types, ensuring high-quality code generation, testing, and validation.

## 🌟 What Makes Rev Different

Rev isn't just another AI coding assistant — it's a **complete agentic development system** with specialized agents for different tasks:

- **🤖 Specialized Sub-Agent Architecture** — Dedicated agents for code writing, refactoring, testing, debugging, documentation, research, and analysis
- **✅ Workflow Verification Loop** — Plan → Execute → **Verify** → Report → Re-plan (ensures tasks actually complete)
- **🧠 Uncertainty Detection** — Detects when uncertain and requests user guidance instead of retrying blindly
- **💬 Interactive REPL Mode** — Session-persistent development with real-time guidance and context retention across multiple prompts
- **🖥️ Universal IDE Integration** — Native support for VSCode, Visual Studio, Vim, Emacs, and all LSP-compatible editors
- **🌐 7 LLM Provider Support** — Ollama (local), OpenAI (GPT-4), Anthropic (Claude), Google Gemini, LocalAI, vLLM, and LMStudio (OpenAI-compatible)
- **🔍 RAG (Retrieval-Augmented Generation)** — Semantic code search using TF-IDF + hybrid symbolic search for intelligent context gathering
- **🛡️ ContextGuard/ClarityEngine** — Validates context sufficiency before planning, preventing "hallucinations" from insufficient context
- **🧠 21 Agentic Design Patterns** — Built on proven research patterns (Goal Setting, Routing, RAG, Recovery, Resource Budgets, etc.)
- **📊 Resource-Aware** — Tracks steps, tokens, and time budgets to prevent runaway execution
- **🎯 Goal-Oriented** — Derives measurable goals from requests and validates they're met
- **🛡️ Production-Ready** — Multi-layer validation, security scanning, auto-recovery, and rollback planning
- **🧪 Optional TDD Mode** — Test-Driven Development workflow (tests before implementation)

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

### 🧠 Uncertainty Detection (NEW!)
**Detects when Rev is uncertain and requests user guidance** instead of retrying blindly:

```bash
# When uncertain, Rev will ask:
🤔 Rev is uncertain and needs guidance:
• Task failed 3 times with identical error: ModuleNotFoundError: No module named 'pytest'
• No progress - same error on every attempt

Task: run tests for auth module
Attempts: 3

[Options]
  [1] Provide specific guidance (describe what to do)
  [2] Skip this task and continue
  [3] Retry with current approach
  [4] Abort execution

Choice [1-4]:
```

**Why Uncertainty Detection is Critical:**
- **No Blind Retries** — Asks for help after 2+ failures with same error
- **Circuit Breaker Override** — Last chance before aborting (10 recovery attempts)
- **User Control** — Choose to provide guidance, skip, retry, or abort
- **Faster Resolution** — Get correct information instead of wasting time

**Configure:**
```bash
# Enable/disable (default: enabled)
export REV_UNCERTAINTY_DETECTION_ENABLED=true

# Set threshold for triggering guidance (default: 5)
export REV_UNCERTAINTY_THRESHOLD=5

# Auto-skip threshold (default: 10)
export REV_UNCERTAINTY_AUTO_SKIP_THRESHOLD=10
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

---

## Key Features

### Specialized Sub-Agent Architecture
- **🔧 CodeWriterAgent** — Specialized for file creation and modification (add, edit, delete, move)
- **♻️ RefactoringAgent** — Handles code extraction and reorganization with verification
- **🧪 TestExecutorAgent** — Runs tests, executes commands, and validates correctness
- **🐛 DebuggingAgent** — Analyzes and fixes code issues
- **📚 DocumentationAgent** — Creates and updates documentation
- **🔍 ResearchAgent** — Explores codebase before planning
- **📊 AnalysisAgent** — Provides code analysis and insights
- **🛠️ ToolCreationAgent** — Creates specialized tools for unique workflows
- **⚙️ ToolExecutorAgent** — Executes specialized tools

Each agent is optimized for its specific task type, resulting in **higher quality outputs** and **3x faster execution**.

### Workflow Verification Loop
**Proper verification workflow** that ensures tasks actually complete:
```
Plan → Execute → VERIFY ✓ → Report → Re-plan if needed
```

- Tasks are verified after execution
- Failed verifications trigger automatic re-planning
- No more silent failures (e.g., extraction that creates no files)
- Real-time feedback on task completion status

### Core Capabilities
- **🤖 9-Agent System** — Planning, Research, Execution, Code Writing, Refactoring, Testing, Analysis, Tool Creation, Tool Execution
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
- **🏠 Local LLM Support** — Ollama, LocalAI, vLLM, LMStudio (no API keys, fully private)
- **☁️ Cloud LLM Support** — OpenAI (GPT-4), Anthropic (Claude), Google Gemini
- **🎯 Advanced Planning** — Dependency analysis, impact assessment, risk evaluation

## Architecture

**Multi-Agent Sub-Agent Orchestration System**

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
                           │ DEBUGGING,   │
                           │ TOOLS)       │
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
                  │  │Agent     │      │Agent     │
                  │  │(DEBUG)   │      │(DOCS)    │
                  │  └──────────┘      └──────────┘
                  │                      │
                  └──────────┬───────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │VERIFY EXECUTION  │
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
| `delete`, `move` | CodeWriterAgent | Remove or relocate files |
| `refactor`, `extract` | RefactoringAgent | Extract classes, reorganize code with **verification** |
| `test`, `validate`, `run` | TestExecutorAgent | Run tests, execute commands, validate correctness |
| `debug`, `fix` | DebuggingAgent | Analyze errors, suggest fixes |
| `document`, `docs` | DocumentationAgent | Create/update documentation |
| `research`, `analyze`, `read` | ResearchAgent | Explore codebase, analyze patterns |
| `create_tool` | ToolCreationAgent | Create specialized tools |
| `execute_tool`, `tool` | ToolExecutorAgent | Execute custom tools |

Each agent is optimized for its specific task type with custom prompts and tool access.

---

## Installation

### Quick Install (Recommended)

```bash
# Install via pip
pip install rev-agentic

# Or install from source
git clone https://github.com/yourusername/rev
cd rev
pip install -e .
```

**Includes:** All IDE integration features (LSP server, HTTP API, VSCode/Visual Studio extensions)

### 1. Choose Your LLM Provider

Rev supports multiple LLM providers:

#### Option A: Local LLM (Ollama) - Private & Free
```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows - Download from https://ollama.ai

# Pull a code model
ollama pull qwen3-coder:480b-cloud  # Recommended
ollama pull llama3.1:70b            # Excellent alternative
ollama pull mistral-nemo:latest     # Fast with tools
```

#### Option B: Cloud LLMs - Powerful & Convenient
```bash
# OpenAI (GPT-4)
export OPENAI_API_KEY="your-key-here"
pip install rev-agentic[openai]

# Anthropic (Claude)
export ANTHROPIC_API_KEY="your-key-here"
pip install rev-agentic[anthropic]

# Google Gemini
export GEMINI_API_KEY="your-key-here"
pip install rev-agentic[gemini]
```

#### Option C: OpenAI-Compatible Backends - Local & Flexible
```bash
# LocalAI (OpenAI-compatible local server)
export LOCALAI_BASE_URL="http://localhost:8080/v1"
export REV_LLM_PROVIDER=localai

# vLLM (High-performance inference server)
export VLLM_BASE_URL="http://localhost:8000/v1"
export REV_LLM_PROVIDER=vllm

# LMStudio (Local LLM development environment)
export LMSTUDIO_BASE_URL="http://localhost:1234/v1"
export REV_LLM_PROVIDER=lmstudio
```

### 2. Install Dependencies

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

### LLM Provider Selection

```bash
# Use specific provider
rev "your task" --llm-provider gemini
rev "your task" --llm-provider openai --model gpt-4
rev "your task" --llm-provider anthropic --model claude-3-5-sonnet-20241022

# Auto-detection from model name
rev "your task" --model gpt-4           # Uses OpenAI
rev "your task" --model claude-3-opus   # Uses Anthropic
rev "your task" --model gemini-pro      # Uses Gemini

# OpenAI-compatible backends
rev "your task" --llm-provider localai
rev "your task" --llm-provider vllm
rev "your task" --llm-provider lmstudio

# Set default provider
export REV_LLM_PROVIDER=gemini
export REV_EXECUTION_MODEL=gemini-2.0-flash-exp
rev "your task"
```

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
- **Model Selection** - Choose from Ollama, GPT-4, Claude, Gemini
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
# LLM Provider Selection
export REV_LLM_PROVIDER=ollama        # ollama, openai, anthropic, gemini, localai, vllm, lmstudio
export REV_EXECUTION_MODEL=gemini-3-flash-preview:cloud

# Provider-Specific Configuration
## Ollama (local)
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3-coder:480b-cloud"

## OpenAI
export OPENAI_API_KEY="your-key"
export OPENAI_MODEL="gpt-4"

## Anthropic
export ANTHROPIC_API_KEY="your-key"
export ANTHROPIC_MODEL="claude-3-5-sonnet-20241022"

## Gemini
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-2.0-flash-exp"

## OpenAI-Compatible Backends (LocalAI, vLLM, LMStudio)
export LOCALAI_BASE_URL="http://localhost:8080/v1"
export VLLM_BASE_URL="http://localhost:8000/v1"
export LMSTUDIO_BASE_URL="http://localhost:1234/v1"
# These reuse OpenAIProvider with custom base URLs

# LLM Generation Parameters
export OLLAMA_TEMPERATURE=0.1           # Lower = more accurate
export OLLAMA_NUM_CTX=16384             # Context window

# Feature Toggles
export REV_UNCERTAINTY_DETECTION_ENABLED=true   # Uncertainty detection (default: true)
export REV_UNCERTAINTY_THRESHOLD=5              # Score to trigger guidance
export REV_CONTEXT_GUARD=true                   # Context validation (default: true)
export REV_TDD_ENABLED=false                    # Test-driven development

# Resource Budgets
export REV_MAX_STEPS=500                # Maximum execution steps
export REV_MAX_TOKENS=1000000           # Token budget
export REV_MAX_SECONDS=3600             # Wallclock timeout (60 min)
```

### Command-Line Options

```bash
rev [OPTIONS] "task description"

Core Options:
  --repl                       Interactive REPL mode
  --model MODEL                LLM model to use
  --llm-provider PROVIDER      LLM provider (ollama, openai, anthropic, gemini, localai, vllm, lmstudio)
  --base-url URL               Ollama API URL

IDE Integration:
  --ide-api                    Start IDE API server
  --ide-lsp                    Start IDE LSP server
  --ide-api-port PORT          API server port (default: 8765)
  --ide-lsp-port PORT          LSP server port (default: 2087)
  --ide-lsp-stdio              Use stdio for LSP

Advanced:
  --research                   Enable research agent (default: enabled)
  --research-depth DEPTH       Research depth (shallow/medium/deep)
  --review-strictness LEVEL    Review level (lenient/moderate/strict)
  --parallel -j N              Parallel execution (N workers)
  --tui                        Curses-based TUI mode
  --debug                      Enable debug logging

Other:
  -y, --yes                    Auto-approve changes
  -h, --help                   Show all options
```

## Troubleshooting

### "Connection refused" (Ollama)

Ensure Ollama is running:

```bash
ollama serve
```

### "Model not found" (Ollama)

Pull the model first:

```bash
ollama pull qwen3-coder:480b-cloud
```

### "Authentication error" (Cloud providers)

Verify your API keys:

```bash
# OpenAI
echo $OPENAI_API_KEY

# Anthropic
echo $ANTHROPIC_API_KEY

# Gemini
echo $GEMINI_API_KEY

# Save keys permanently
rev save-api-key openai YOUR_KEY
rev save-api-key anthropic YOUR_KEY
rev save-api-key gemini YOUR_KEY
```

### "Connection refused" (OpenAI-Compatible Backends)

For LocalAI, vLLM, or LMStudio, ensure the server is running and the base URL is correct:

```bash
# Verify server is running
curl http://localhost:8080/v1/models  # LocalAI
curl http://localhost:8000/v1/models  # vLLM
curl http://localhost:1234/v1/models  # LMStudio

# Set correct base URL
export LOCALAI_BASE_URL="http://localhost:8080/v1"
export VLLM_BASE_URL="http://localhost:8000/v1"
export LMSTUDIO_BASE_URL="http://localhost:1234/v1"
```

### Verification Failure

If you see messages like:

```
[!] Verification failed: No Python files found - extraction may have failed
[!] Verification failed, marking for re-planning
```

This is **expected behavior!** The verification system detected that a task didn't complete properly and is re-planning. Let it retry — it will often succeed on the second attempt with a different approach.

### Uncertainty Guidance

When Rev asks for guidance:

```
🤔 Rev is uncertain and needs guidance:
• Task failed 3 times with identical error
```

**This is working correctly!** Rev detected repeated failures and is asking for help instead of wasting time. Provide specific guidance to resolve the issue quickly.

## Testing & Coverage

**Test Coverage: 80%+** - Production Ready ✅

- **136+ tests passing** (100% pass rate)
- **Cross-platform tested** (Windows, Linux, macOS)
- **Provider-specific tests** for Gemini, OpenAI, Anthropic
- **Uncertainty detection tests** (11 test cases)
- **Schema sanitization tests** (7 test cases)

### Running Tests

```bash
# Run all tests
python -m pytest tests -v

# Run specific test suites
python -m pytest tests/test_uncertainty_detection.py -v
python -m pytest tests/test_gemini_schema_sanitization.py -v
python -m pytest tests/test_quick_verify.py -v

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
7. **Provide Guidance When Asked** — Answer uncertainty prompts to save time
8. **Choose the Right Provider** — Ollama for privacy, cloud providers for power

## Key Documents

- **[docs/IDE_INTEGRATION.md](docs/IDE_INTEGRATION.md)** — IDE integration guide (VSCode, Visual Studio, Vim, Emacs, etc.)
- **[docs/WORKFLOW_VERIFICATION_FIX.md](docs/WORKFLOW_VERIFICATION_FIX.md)** — Verification loop implementation
- **[docs/UNCERTAINTY_DETECTION_IMPLEMENTATION.md](docs/UNCERTAINTY_DETECTION_IMPLEMENTATION.md)** — Uncertainty detection system
- **[docs/GEMINI_COMPLETE_FIX.md](docs/GEMINI_COMPLETE_FIX.md)** — Gemini integration fixes
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

### Multi-Provider Support (7 Providers)

**Flexibility:**
- **Local** (Ollama, LocalAI, vLLM, LMStudio) - No API costs, fully private, works offline
- **Cloud** (OpenAI GPT-4, Anthropic Claude, Google Gemini) - Most powerful models, best results

**Per-Phase Configuration:**
- Different providers for planning vs execution
- Mix and match for cost/quality optimization
- Fallback support for reliability

## File Structure

```
.
├── README.md                  # Main documentation (you are here)
├── docs/
│   ├── IDE_INTEGRATION.md     # IDE integration guide
│   ├── UNCERTAINTY_DETECTION_IMPLEMENTATION.md  # Uncertainty system
│   ├── GEMINI_COMPLETE_FIX.md                  # Gemini integration
│   ├── WORKFLOW_VERIFICATION_FIX.md            # Verification implementation
│   ├── IMPLEMENTATION_SUMMARY.md               # Agentic patterns reference
│   ├── ARCHITECTURE.md                         # System architecture
│   └── ... (50+ documentation files)
├── rev/                       # Main package (CLI entry: `rev`)
│   ├── execution/
│   │   ├── orchestrator.py    # Sub-agent coordinator (with verification)
│   │   ├── quick_verify.py    # Task verification module
│   │   ├── uncertainty_detector.py  # Uncertainty detection
│   │   ├── user_guidance.py   # User guidance dialog
│   │   └── ...
│   ├── agents/
│   │   ├── code_writer.py     # CodeWriterAgent
│   │   ├── refactoring.py     # RefactoringAgent
│   │   ├── test_executor.py   # TestExecutorAgent
│   │   ├── debugging.py       # DebuggingAgent
│   │   ├── documentation.py   # DocumentationAgent
│   │   ├── research.py        # ResearchAgent
│   │   ├── analysis.py        # AnalysisAgent
│   │   └── ...
│   ├── llm/
│   │   ├── providers/
│   │   │   ├── ollama.py      # Ollama provider
│   │   │   ├── openai_provider.py   # OpenAI/GPT-4
│   │   │   ├── anthropic_provider.py  # Anthropic/Claude
│   │   │   ├── gemini_provider.py     # Google Gemini
│   │   │   └── base.py        # Provider interface
│   │   └── provider_factory.py  # Provider selection
│   ├── ide/                   # IDE integration
│   │   ├── lsp_server.py      # LSP server
│   │   ├── api_server.py      # HTTP/WebSocket API
│   │   └── client.py          # Python client library
│   └── ...
├── ide-extensions/
│   ├── vscode/                # VSCode extension
│   └── visual-studio/         # Visual Studio extension
├── tests/
│   ├── test_uncertainty_detection.py  # Uncertainty tests
│   ├── test_gemini_schema_sanitization.py  # Gemini schema tests
│   ├── test_ide_integration.py  # IDE integration tests
│   └── ... (comprehensive test suite)
└── requirements.txt           # Project dependencies
```

## License

MIT

## Contributing

Contributions are welcome! This is a production-grade agentic development system focused on autonomous workflows with specialized sub-agents.

For feature requests or bug reports, please open an issue on GitHub.
