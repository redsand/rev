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
