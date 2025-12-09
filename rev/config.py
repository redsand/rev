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
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")
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
MAX_LLM_TOKENS_PER_RUN = int(os.getenv("REV_MAX_TOKENS", "100000"))
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

# Private mode configuration - disables all public MCP servers
PRIVATE_MODE = os.getenv("REV_PRIVATE_MODE", "false").lower() == "true"

# Default MCP (Model Context Protocol) servers
# These are public, free servers that enhance AI capabilities without requiring API keys
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
    },
    "deepwiki": {
        "command": "curl",
        "args": ["-X", "POST", "https://mcp.deepwiki.com/sse"],
        "description": "RAG-as-a-Service for GitHub repositories - search and analyze code",
        "enabled": os.getenv("REV_MCP_DEEPWIKI", "true").lower() == "true",
        "public": True,
        "type": "remote"
    },
    "exa-search": {
        "command": "curl",
        "args": ["-X", "POST", "https://mcp.exa.ai/mcp"],
        "description": "Search code, documentation, and web resources",
        "enabled": os.getenv("REV_MCP_EXA_SEARCH", "true").lower() == "true",
        "public": True,
        "type": "remote"
    },
    "semgrep": {
        "command": "curl",
        "args": ["-X", "POST", "https://mcp.semgrep.ai/sse"],
        "description": "Static code analysis for security and quality",
        "enabled": os.getenv("REV_MCP_SEMGREP", "true").lower() == "true",
        "public": True,
        "type": "remote"
    },
    "cloudflare-docs": {
        "command": "curl",
        "args": ["-X", "POST", "https://docs.mcp.cloudflare.com/sse"],
        "description": "Access Cloudflare API and platform documentation",
        "enabled": os.getenv("REV_MCP_CLOUDFLARE_DOCS", "true").lower() == "true",
        "public": True,
        "type": "remote"
    },
    "astro-docs": {
        "command": "curl",
        "args": ["-X", "POST", "https://mcp.docs.astro.build/mcp"],
        "description": "Access Astro framework documentation",
        "enabled": os.getenv("REV_MCP_ASTRO_DOCS", "true").lower() == "true",
        "public": True,
        "type": "remote"
    },
    "huggingface": {
        "command": "curl",
        "args": ["-X", "POST", "https://hf.co/mcp"],
        "description": "Access Hugging Face models and repositories",
        "enabled": os.getenv("REV_MCP_HUGGINGFACE", "true").lower() == "true",
        "public": True,
        "type": "remote"
    }
}

# Optional MCP servers (require API keys - user must enable manually)
# These are considered private servers since they use personal API keys
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
