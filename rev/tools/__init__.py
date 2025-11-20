#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tool functions for rev - file operations, git operations, code analysis, etc."""

# File operations
from rev.tools.file_ops import (
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
)

# Git operations
from rev.tools.git_ops import (
    git_diff,
    apply_patch,
    git_commit,
    git_status,
    git_log,
    git_branch,
    run_cmd,
    run_tests,
    get_repo_context,
)

# Code operations
from rev.tools.code_ops import (
    remove_unused_imports,
    extract_constants,
    simplify_conditionals,
)

# Data conversion
from rev.tools.conversion import (
    convert_json_to_yaml,
    convert_yaml_to_json,
    convert_csv_to_json,
    convert_json_to_csv,
    convert_env_to_json,
)

# Dependency management
from rev.tools.dependencies import (
    analyze_dependencies,
    update_dependencies,
    scan_dependencies_vulnerabilities,
)

# Security tools
from rev.tools.security import (
    scan_code_security,
    detect_secrets,
    check_license_compliance,
)

# SSH operations
from rev.tools.ssh_ops import (
    ssh_connect,
    ssh_exec,
    ssh_copy_to,
    ssh_copy_from,
    ssh_disconnect,
    ssh_list_connections,
)

# Cache operations
from rev.tools.cache_ops import (
    set_cache_references,
    get_cache_stats,
    clear_caches,
    persist_caches,
)

# Utilities
from rev.tools.utils import (
    install_package,
    web_fetch,
    execute_python,
    get_system_info,
)

# Registry
from rev.tools.registry import (
    execute_tool,
    get_available_tools,
)

__all__ = [
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
]
