#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration constants and settings for rev."""

import os
import pathlib
import platform
from typing import Dict, Any, Optional, List

# Check for optional dependencies
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    paramiko = None

# Configuration
ROOT = pathlib.Path(os.getcwd()).resolve()
# Allowlist of additional roots that tools can access (populated via /add-dir)
ADDITIONAL_ROOTS: list[pathlib.Path] = []


def register_additional_root(path: pathlib.Path) -> None:
    """Register an additional root directory that tools may access."""

    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValueError(f"Additional root must be a directory: {path}")

    if resolved not in ADDITIONAL_ROOTS:
        ADDITIONAL_ROOTS.append(resolved)


def get_allowed_roots() -> List[pathlib.Path]:
    """Return the primary project root plus any additional allowed roots."""

    return [ROOT, *ADDITIONAL_ROOTS]
REV_DIR = ROOT / ".rev"
CACHE_DIR = REV_DIR / "cache"
CHECKPOINTS_DIR = REV_DIR / "checkpoints"
LOGS_DIR = REV_DIR / "logs"
SESSIONS_DIR = REV_DIR / "sessions"
MEMORY_DIR = REV_DIR / "memory"
METRICS_DIR = REV_DIR / "metrics"
SETTINGS_FILE = REV_DIR / "settings.json"
TEST_MARKER_FILE = REV_DIR / "test"
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-coder:480b-cloud")  # default model

# Determine default provider based on configured credentials
# Priority: explicit REV_LLM_PROVIDER > Gemini > Anthropic > OpenAI > Ollama
def _get_primary_provider_and_model():
    """Get primary provider and its default model based on configured credentials.

    Returns the provider name and its default model.
    The model will be the one configured for that provider.

    Priority order:
    1. REV_LLM_PROVIDER (explicit override)
    2. Gemini (if GEMINI_API_KEY is set)
    3. Anthropic (if ANTHROPIC_API_KEY is set)
    4. OpenAI (if OPENAI_API_KEY is set)
    5. Ollama (default)
    """
    # Check for explicit provider override first
    explicit_provider = os.getenv("REV_LLM_PROVIDER")
    if explicit_provider:
        explicit_provider = explicit_provider.lower()
        # Map provider to its default model
        provider_models = {
            "gemini": os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp"),
            "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            "openai": os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview"),
            "ollama": DEFAULT_OLLAMA_MODEL,
        }
        return explicit_provider, provider_models.get(explicit_provider, DEFAULT_OLLAMA_MODEL)

    # Check Gemini credentials (highest priority when present)
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return "gemini", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

    # Check Anthropic credentials
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return "anthropic", os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

    # Check OpenAI credentials
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        return "openai", os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")

    # Default to Ollama
    return "ollama", DEFAULT_OLLAMA_MODEL

_PRIMARY_PROVIDER, _DEFAULT_MODEL = _get_primary_provider_and_model()

# Debug: Log provider and model selection
if os.getenv("OLLAMA_DEBUG"):
    print(f"[DEBUG] Config initialized: PRIMARY_PROVIDER={_PRIMARY_PROVIDER}, DEFAULT_MODEL={_DEFAULT_MODEL}")

OLLAMA_BASE_URL = DEFAULT_OLLAMA_BASE_URL
OLLAMA_MODEL = DEFAULT_OLLAMA_MODEL
EXECUTION_MODEL = os.getenv("REV_EXECUTION_MODEL", _DEFAULT_MODEL)
PLANNING_MODEL = os.getenv("REV_PLANNING_MODEL", _DEFAULT_MODEL)
REVIEW_MODEL = os.getenv("REV_REVIEW_MODEL", _DEFAULT_MODEL)
RESEARCH_MODEL = os.getenv("REV_RESEARCH_MODEL", _DEFAULT_MODEL)
DEFAULT_SUPPORTS_TOOLS = os.getenv("REV_MODEL_SUPPORTS_TOOLS", "true").lower() == "true"
EXECUTION_SUPPORTS_TOOLS = os.getenv("REV_EXECUTION_SUPPORTS_TOOLS", str(DEFAULT_SUPPORTS_TOOLS)).lower() == "true"
PLANNING_SUPPORTS_TOOLS = os.getenv("REV_PLANNING_SUPPORTS_TOOLS", str(DEFAULT_SUPPORTS_TOOLS)).lower() == "true"
RESEARCH_SUPPORTS_TOOLS = os.getenv("REV_RESEARCH_SUPPORTS_TOOLS", str(DEFAULT_SUPPORTS_TOOLS)).lower() == "true"

# LLM Generation Parameters (for improved tool calling with local models)
# Lower temperature improves consistency and accuracy for tool calling
# Recommended: 0.1 for tool calling, 0.7 for creative tasks
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))

# Context window size (num_ctx) - recommended 8K-16K for tool calling
# Higher values allow for more context but use more memory
# 8192 = 8K, 16384 = 16K, 32768 = 32K
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

# Top-p (nucleus sampling) for controlling randomness
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))

# Top-k for limiting vocabulary selection
OLLAMA_TOP_K = int(os.getenv("OLLAMA_TOP_K", "40"))

# ============================================================================
# Multi-Provider LLM Configuration
# ============================================================================
# Provider selection: ollama, openai, anthropic, gemini
# Uses the primary provider determined above based on configured credentials
# Priority: explicit REV_LLM_PROVIDER > Gemini > Anthropic > OpenAI > Ollama
LLM_PROVIDER = _PRIMARY_PROVIDER

# Per-phase provider overrides (optional)
# These allow different providers for different agent phases
# If not explicitly set, use the primary provider
EXECUTION_PROVIDER = os.getenv("REV_EXECUTION_PROVIDER", LLM_PROVIDER)
PLANNING_PROVIDER = os.getenv("REV_PLANNING_PROVIDER", LLM_PROVIDER)
RESEARCH_PROVIDER = os.getenv("REV_RESEARCH_PROVIDER", LLM_PROVIDER)
EXECUTION_MODE = os.getenv("REV_EXECUTION_MODE", "linear").lower()

def set_execution_mode(mode: str) -> bool:
    """Set the execution mode for the current session.

    Args:
        mode: Either "linear" or "sub-agent"

    Returns:
        True if mode was set successfully, False otherwise
    """
    global EXECUTION_MODE
    mode = mode.lower().strip()

    valid_modes = ["linear", "sub-agent", "inline"]  # "inline" is alias for "linear"

    if mode == "inline":
        mode = "linear"

    if mode not in valid_modes:
        print(f"[X] Invalid execution mode: '{mode}'. Valid modes: {', '.join(valid_modes)}")
        return False

    EXECUTION_MODE = mode
    # Also set the environment variable for child processes
    os.environ["REV_EXECUTION_MODE"] = mode

    print(f"[OK] Execution mode set to: {mode}")
    return True

def get_execution_mode() -> str:
    """Get the current execution mode.

    Returns:
        The current execution mode ("linear" or "sub-agent")
    """
    return EXECUTION_MODE

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))

# Anthropic (Claude) Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
ANTHROPIC_TEMPERATURE = float(os.getenv("ANTHROPIC_TEMPERATURE", "0.1"))
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))

# Google Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.1"))
GEMINI_TOP_P = float(os.getenv("GEMINI_TOP_P", "0.9"))
GEMINI_TOP_K = int(os.getenv("GEMINI_TOP_K", "40"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192"))

# Load saved API keys from secrets file (if environment variables not set)
# This is done at module load time to make saved keys available immediately
def _load_saved_api_keys():
    """Load saved API keys from secrets file if not already set via environment."""
    try:
        from rev.secrets_manager import get_api_key

        global OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY

        # Only load from secrets if not set in environment
        if not OPENAI_API_KEY:
            saved_key = get_api_key("openai")
            if saved_key:
                OPENAI_API_KEY = saved_key

        if not ANTHROPIC_API_KEY:
            saved_key = get_api_key("anthropic")
            if saved_key:
                ANTHROPIC_API_KEY = saved_key

        if not GEMINI_API_KEY:
            saved_key = get_api_key("gemini")
            if saved_key:
                GEMINI_API_KEY = saved_key
    except ImportError:
        # secrets_manager not available yet (circular import during initial load)
        pass

# Try to load saved API keys
_load_saved_api_keys()
# ============================================================================

VALIDATION_MODE_DEFAULT = os.getenv("REV_VALIDATION_MODE", "targeted").lower()
MAX_FILE_BYTES = 5 * 1024 * 1024
READ_RETURN_LIMIT = 80_000
SEARCH_MATCH_LIMIT = 2000
LIST_LIMIT = 2000
MAX_READ_FILE_PER_TASK = int(os.getenv("REV_MAX_READ_FILE_PER_TASK", "999"))
MAX_SEARCH_CODE_PER_TASK = int(os.getenv("REV_MAX_SEARCH_CODE_PER_TASK", "999"))
MAX_RUN_CMD_PER_TASK = int(os.getenv("REV_MAX_RUN_CMD_PER_TASK", "999"))
MAX_EXECUTION_ITERATIONS = int(os.getenv("REV_MAX_EXEC_ITER", "45"))
MAX_TASK_ITERATIONS = int(os.getenv("REV_MAX_TASK_ITER", "45"))
MAX_PLANNING_TOOL_ITERATIONS = int(os.getenv("REV_MAX_PLANNING_ITER", "45"))
CONTEXT_WINDOW_HISTORY = int(os.getenv("REV_CONTEXT_WINDOW_HISTORY", "8"))

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".next", "out", "coverage", ".cache",
    ".venv", "venv", "target"
}

ALLOW_CMDS = {
    "python", "pip", "pytest", "ruff", "black", "isort", "mypy",
    "node", "npm", "npx", "pnpm", "prettier", "eslint", "git", "make"
}

# Resource budgets (for resource-aware optimization pattern)
MAX_STEPS_PER_RUN = int(os.getenv("REV_MAX_STEPS", "500"))
# Keep token budget comfortably below the provider cap to avoid hard failures when the heuristic
# token estimates differ from true usage.
MAX_LLM_TOKENS_PER_RUN = int(os.getenv("REV_MAX_TOKENS", str(1_000_000)))
MAX_WALLCLOCK_SECONDS = int(os.getenv("REV_MAX_SECONDS", "3600"))  # 60 minutes default
MAX_PLAN_TASKS = int(os.getenv("REV_MAX_PLAN_TASKS", "999"))
RESEARCH_DEPTH_DEFAULT = os.getenv("REV_RESEARCH_DEPTH", "shallow").lower()
MAX_ORCHESTRATOR_RETRIES = int(os.getenv("REV_MAX_ORCH_RETRIES", "2"))
MAX_PLAN_REGEN_RETRIES = int(os.getenv("REV_MAX_PLAN_REGEN_RETRIES", "2"))
MAX_VALIDATION_RETRIES = int(os.getenv("REV_MAX_VALIDATION_RETRIES", "2"))
MAX_ADAPTIVE_REPLANS = int(os.getenv("REV_MAX_ADAPTIVE_REPLANS", "1"))
VALIDATION_TIMEOUT_SECONDS = int(os.getenv("REV_VALIDATION_TIMEOUT", "180"))

# Logging configuration
LOG_RETENTION_LIMIT_DEFAULT = int(os.getenv("REV_LOG_RETENTION", "7"))
LOG_RETENTION_LIMIT = LOG_RETENTION_LIMIT_DEFAULT

# History configuration
HISTORY_SIZE = int(os.getenv("REV_HISTORY_SIZE", "100"))  # Number of history entries to keep
# Default to .rev/history; set REV_HISTORY_FILE to an empty string to disable persistence
HISTORY_FILE = os.getenv("REV_HISTORY_FILE", str(REV_DIR / "history"))

# Input configuration
PASTE_THRESHOLD = int(os.getenv("REV_PASTE_THRESHOLD", "3"))  # Lines threshold for paste detection
PASTE_TIME_THRESHOLD = float(os.getenv("REV_PASTE_TIME_THRESHOLD", "0.5"))  # Seconds between lines for paste detection
ESCAPE_INTERVAL = float(os.getenv("REV_ESCAPE_INTERVAL", "0.05"))  # Escape key check interval in seconds
ESCAPE_TIMEOUT = float(os.getenv("REV_ESCAPE_TIMEOUT", "0.1"))  # Escape key timeout in seconds

# Code reuse policies (Phase 2)
PREFER_REUSE = os.getenv("REV_PREFER_REUSE", "true").lower() == "true"
WARN_ON_NEW_FILES = os.getenv("REV_WARN_NEW_FILES", "true").lower() == "true"
REQUIRE_REUSE_JUSTIFICATION = os.getenv("REV_REQUIRE_JUSTIFICATION", "false").lower() == "true"
MAX_FILES_PER_FEATURE = int(os.getenv("REV_MAX_FILES", "5"))  # Encourage consolidation
SIMILARITY_THRESHOLD = float(os.getenv("REV_SIMILARITY_THRESHOLD", "0.6"))  # For file name similarity

# MCP (Model Context Protocol) Configuration
# PRIVATE_MODE: When enabled, disables all public MCP servers for secure/confidential code work
# Set REV_PRIVATE_MODE=true or use /private command to enable
DEFAULT_PRIVATE_MODE = os.getenv("REV_PRIVATE_MODE", "false").lower() == "true"
PRIVATE_MODE = DEFAULT_PRIVATE_MODE

# Default MCP servers (local NPM packages)
# These are public, free servers that enhance AI capabilities without requiring API keys
# Disabled when PRIVATE_MODE is enabled
DEFAULT_MCP_SERVERS = {
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "description": "Persistent memory storage for AI context across sessions",
        "enabled": os.getenv("REV_MCP_MEMORY", "false").lower() == "true",
        "public": True
    },
    "sequential-thinking": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "description": "Enable step-by-step reasoning for complex problem solving",
        "enabled": os.getenv("REV_MCP_SEQUENTIAL_THINKING", "true").lower() == "true",
        "public": True
    },
    "fetch": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
        "description": "Make HTTP requests to access documentation and APIs",
        "enabled": os.getenv("REV_MCP_FETCH", "true").lower() == "true",
        "public": True
    }
}

# Remote MCP servers for development (SSE/HTTP endpoints)
# These are publicly hosted servers that provide specialized development capabilities
# Disabled when PRIVATE_MODE is enabled
REMOTE_MCP_SERVERS = {
    "deepwiki": {
        "url": "https://mcp.deepwiki.com/sse",
        "description": "RAG-as-a-Service for GitHub repositories - code understanding",
        "enabled": os.getenv("REV_MCP_DEEPWIKI", "true").lower() == "true",
        "public": True,
        "category": "code-understanding"
    },
    "exa-search": {
        "url": "https://mcp.exa.ai/mcp",
        "description": "Code, documentation, and web search capabilities",
        "enabled": os.getenv("REV_MCP_EXA_SEARCH", "true").lower() == "true",
        "public": True,
        "category": "search"
    },
    "semgrep": {
        "url": "https://mcp.semgrep.ai/sse",
        "description": "Static analysis and security scanning for code",
        "enabled": os.getenv("REV_MCP_SEMGREP", "true").lower() == "true",
        "public": True,
        "category": "security"
    },
    "cloudflare-docs": {
        "url": "https://docs.mcp.cloudflare.com/sse",
        "description": "Cloudflare documentation access",
        "enabled": os.getenv("REV_MCP_CLOUDFLARE_DOCS", "true").lower() == "true",
        "public": True,
        "category": "documentation"
    },
    "llmtext": {
        "url": "https://mcp.llmtxt.dev/sse",
        "description": "Text and data analysis helpers for development",
        "enabled": os.getenv("REV_MCP_LLMTEXT", "true").lower() == "true",
        "public": True,
        "category": "analysis"
    }
}

# Optional MCP servers (require API keys - user must enable manually)
# These are NOT disabled by PRIVATE_MODE as they require explicit user configuration
OPTIONAL_MCP_SERVERS = {
    "brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "description": "Web search using Brave Search API (requires BRAVE_API_KEY)",
        "env_required": ["BRAVE_API_KEY"],
        "enabled": False,
        "public": False
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "description": "Interact with GitHub repositories (requires GITHUB_TOKEN)",
        "env_required": ["GITHUB_TOKEN"],
        "enabled": False,
        "public": False
    }
}

# System information (cached)
_SYSTEM_INFO: Optional[Dict[str, Any]] = None

# Global interrupt flag for escape key handling
_ESCAPE_INTERRUPT = False


class EscapeInterrupt(RuntimeError):
    """Raised when the user presses ESC to interrupt execution."""


def ensure_escape_is_cleared(message: str = "ESC pressed") -> None:
    """Raise an interrupt if ESC was pressed during processing.

    This helper lets long-running workflows bail out quickly when the
    background escape monitor sets the global flag. It also clears the flag so
    subsequent operations start cleanly.

    Args:
        message: Contextual message for the interrupt exception.
    """
    if get_escape_interrupt():
        set_escape_interrupt(False)
        raise EscapeInterrupt(message)

# Global private mode flag (can be toggled at runtime)
_PRIVATE_MODE_OVERRIDE: Optional[bool] = None


def set_model(model_name: str) -> None:
    """
    Update the active model for all agent phases.

    This keeps execution, planning, and research models in sync with the user
    selection (e.g., via CLI --model or /model command) to avoid falling back
    to the default.
    """
    global OLLAMA_MODEL, EXECUTION_MODEL, PLANNING_MODEL, RESEARCH_MODEL
    OLLAMA_MODEL = model_name
    EXECUTION_MODEL = model_name
    PLANNING_MODEL = model_name
    RESEARCH_MODEL = model_name


def get_system_info_cached() -> Dict[str, Any]:
    """Get cached system information."""
    global _SYSTEM_INFO
    if _SYSTEM_INFO is None:
        _SYSTEM_INFO = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "is_windows": platform.system() == "Windows",
            "is_linux": platform.system() == "Linux",
            "is_macos": platform.system() == "Darwin",
            "shell_type": "powershell" if platform.system() == "Windows" else "bash"
        }
    return _SYSTEM_INFO


def set_escape_interrupt(value: bool):
    """Set the global escape interrupt flag."""
    global _ESCAPE_INTERRUPT
    _ESCAPE_INTERRUPT = value


def get_escape_interrupt() -> bool:
    """Get the global escape interrupt flag."""
    return _ESCAPE_INTERRUPT


def set_private_mode(enabled: bool):
    """
    Set private mode to disable/enable all public MCP servers.

    When private mode is enabled:
    - All public MCP servers are disabled (DEFAULT_MCP_SERVERS, REMOTE_MCP_SERVERS)
    - Only user-configured servers with API keys remain available
    - Use this for working with confidential/proprietary code

    Args:
        enabled: True to enable private mode, False to disable
    """
    global _PRIVATE_MODE_OVERRIDE
    _PRIVATE_MODE_OVERRIDE = enabled


def get_private_mode() -> bool:
    """
    Get the current private mode status.

    Returns:
        True if private mode is enabled (public MCPs disabled), False otherwise
    """
    global _PRIVATE_MODE_OVERRIDE
    if _PRIVATE_MODE_OVERRIDE is not None:
        return _PRIVATE_MODE_OVERRIDE
    return PRIVATE_MODE


def is_mcp_server_allowed(server_config: Dict[str, Any]) -> bool:
    """
    Check if an MCP server is allowed to load based on private mode.

    Args:
        server_config: Server configuration dictionary

    Returns:
        True if server can be loaded, False if blocked by private mode
    """
    # If not in private mode, all servers allowed
    if not get_private_mode():
        return True

    # In private mode, only allow non-public servers
    is_public = server_config.get("public", False)
    return not is_public
