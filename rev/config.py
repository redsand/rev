#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration constants and settings for rev."""

import os
import pathlib
import platform
from typing import Dict, Any, Optional

# Check for optional dependencies
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    paramiko = None

# Configuration
ROOT = pathlib.Path(os.getcwd()).resolve()
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")  # default model

OLLAMA_BASE_URL = DEFAULT_OLLAMA_BASE_URL
OLLAMA_MODEL = DEFAULT_OLLAMA_MODEL
MAX_FILE_BYTES = 5 * 1024 * 1024
READ_RETURN_LIMIT = 80_000
SEARCH_MATCH_LIMIT = 2000
LIST_LIMIT = 2000

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
MAX_STEPS_PER_RUN = int(os.getenv("REV_MAX_STEPS", "200"))
# Keep token budget conservative to avoid hitting provider limits when heuristic
# token estimates differ from true usage.
MAX_LLM_TOKENS_PER_RUN = int(os.getenv("REV_MAX_TOKENS", "80000"))
MAX_WALLCLOCK_SECONDS = int(os.getenv("REV_MAX_SECONDS", "1800"))  # 30 minutes default

# History configuration
HISTORY_SIZE = int(os.getenv("REV_HISTORY_SIZE", "100"))  # Number of history entries to keep
HISTORY_FILE = os.getenv("REV_HISTORY_FILE", "")  # Empty means no file persistence

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
        "enabled": os.getenv("REV_MCP_MEMORY", "true").lower() == "true",
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

# Global private mode flag (can be toggled at runtime)
_PRIVATE_MODE_OVERRIDE: Optional[bool] = None


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
