#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev - Autonomous AI Development System with Multi-Agent Orchestration."""

__version__ = "2.0.0"

# Configuration
from rev.config import ROOT

# Core models
from rev.models import (
    Task,
    TaskStatus,
    RiskLevel,
    ExecutionPlan,
)

# Cache classes
from rev.cache import (
    IntelligentCache,
    FileContentCache,
    LLMResponseCache,
    RepoContextCache,
    DependencyTreeCache,
    initialize_caches,
)

# Terminal utilities
from rev.terminal import (
    get_input_with_escape,
    repl_mode,
)

# Tool functions - All functions from tools module
from rev.tools import (
    # File operations
    read_file,
    write_file,
    list_dir,
    search_code,
    delete_file,
    move_file,
    append_to_file,
    replace_in_file,
    create_directory,
    get_file_info,
    copy_file,
    file_exists,
    read_file_lines,
    tree_view,
    # Git operations
    git_diff,
    apply_patch,
    git_commit,
    git_status,
    git_log,
    git_branch,
    run_cmd,
    run_tests,
    get_repo_context,
    # Code operations
    remove_unused_imports,
    extract_constants,
    simplify_conditionals,
    # Data conversion
    convert_json_to_yaml,
    convert_yaml_to_json,
    convert_csv_to_json,
    convert_json_to_csv,
    convert_env_to_json,
    # Dependency management
    analyze_dependencies,
    update_dependencies,
    scan_dependencies_vulnerabilities,
    # Security tools
    scan_code_security,
    detect_secrets,
    check_license_compliance,
    # SSH operations
    ssh_connect,
    ssh_exec,
    ssh_copy_to,
    ssh_copy_from,
    ssh_disconnect,
    ssh_list_connections,
    # Cache operations
    set_cache_references,
    get_cache_stats,
    clear_caches,
    persist_caches,
    # Utilities
    install_package,
    web_fetch,
    execute_python,
    get_system_info,
    # Registry
    execute_tool,
    get_available_tools,
)

# MCP operations
from rev.mcp import (
    mcp_add_server,
    mcp_list_servers,
    mcp_call_tool,
)

# Internal functions (for testing)
from rev.tools.file_ops import _safe_path

__all__ = [
    # Version
    "__version__",
    # Configuration
    "ROOT",
    # Models
    "Task",
    "TaskStatus",
    "RiskLevel",
    "ExecutionPlan",
    # Cache classes
    "IntelligentCache",
    "FileContentCache",
    "LLMResponseCache",
    "RepoContextCache",
    "DependencyTreeCache",
    "initialize_caches",
    # Terminal
    "get_input_with_escape",
    "repl_mode",
    # File operations
    "read_file",
    "write_file",
    "list_dir",
    "search_code",
    "delete_file",
    "move_file",
    "append_to_file",
    "replace_in_file",
    "create_directory",
    "get_file_info",
    "copy_file",
    "file_exists",
    "read_file_lines",
    "tree_view",
    # Git operations
    "git_diff",
    "apply_patch",
    "git_commit",
    "git_status",
    "git_log",
    "git_branch",
    "run_cmd",
    "run_tests",
    "get_repo_context",
    # Code operations
    "remove_unused_imports",
    "extract_constants",
    "simplify_conditionals",
    # Data conversion
    "convert_json_to_yaml",
    "convert_yaml_to_json",
    "convert_csv_to_json",
    "convert_json_to_csv",
    "convert_env_to_json",
    # Dependency management
    "analyze_dependencies",
    "update_dependencies",
    "scan_dependencies_vulnerabilities",
    # Security tools
    "scan_code_security",
    "detect_secrets",
    "check_license_compliance",
    # SSH operations
    "ssh_connect",
    "ssh_exec",
    "ssh_copy_to",
    "ssh_copy_from",
    "ssh_disconnect",
    "ssh_list_connections",
    # Cache operations
    "set_cache_references",
    "get_cache_stats",
    "clear_caches",
    "persist_caches",
    # Utilities
    "install_package",
    "web_fetch",
    "execute_python",
    "get_system_info",
    # Registry
    "execute_tool",
    "get_available_tools",
    # MCP operations
    "mcp_add_server",
    "mcp_list_servers",
    "mcp_call_tool",
    # Internal (for testing)
    "_safe_path",
]

# Compatibility shim for legacy tests expecting a low‑level shell runner.
import json
import subprocess

def _run_shell(cmd, timeout=30):
    """Execute a shell command and return a JSON string.

    Captures ``stdout``, ``stderr`` and the return code. On error returns a JSON
    object with an ``error`` key. This matches the legacy interface expected by
    the test suite.
    """
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.dumps({
            "rc": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})
