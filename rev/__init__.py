#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev - An AI-powered code review and execution framework."""

__version__ = "0.1.0"

# Core models
from rev.models import (
    Task,
    TaskStatus,
    RiskLevel,
    ExecutionPlan,
)

# Terminal utilities
from rev.terminal import (
    get_input_with_escape,
    repl_mode,
)

# Tool functions - key imports for common use
from rev.tools import (
    # File operations (most common)
    read_file,
    write_file,
    list_dir,
    search_code,
    # Git operations
    git_diff,
    git_status,
    git_commit,
    # Execution
    run_cmd,
    run_tests,
)

__all__ = [
    # Version
    "__version__",
    # Models
    "Task",
    "TaskStatus",
    "RiskLevel",
    "ExecutionPlan",
    # Terminal
    "get_input_with_escape",
    "repl_mode",
    # File operations
    "read_file",
    "write_file",
    "list_dir",
    "search_code",
    # Git operations
    "git_diff",
    "git_status",
    "git_commit",
    # Execution
    "run_cmd",
    "run_tests",
]
