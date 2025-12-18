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
from rev.tools.python_ast_ops import (
    rewrite_python_imports,
    rewrite_python_keyword_args,
    rename_imported_symbols,
    move_imported_symbols,
    rewrite_python_function_parameters,
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
    check_dependency_updates,
    check_dependency_vulnerabilities,
    update_dependencies,
    scan_dependencies_vulnerabilities,
)

# Security tools
from rev.tools.security import (
    scan_security_issues,
    detect_secrets,
    check_license_compliance,
)

# Linting and type checks
from rev.tools.linting import (
    run_linters,
    run_type_checks,
)

# Test quality tools
from rev.tools.test_quality import (
    run_property_tests,
    generate_property_tests,
    check_contracts,
    detect_flaky_tests,
    compare_behavior_with_baseline,
)
from rev.tools.runtime_analysis import (
    analyze_runtime_logs,
    analyze_performance_regression,
    analyze_error_traces,
)
from rev.tools.config_checks import (
    validate_ci_config,
    verify_migrations,
)
from rev.tools.refactoring_utils import (
    split_python_module_classes,
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
    get_last_tool_call,
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
    "rewrite_python_imports",
    "rewrite_python_keyword_args",
    "rename_imported_symbols",
    "move_imported_symbols",
    "rewrite_python_function_parameters",
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
    "check_dependency_updates",
    "check_dependency_vulnerabilities",
    "update_dependencies",
    "scan_dependencies_vulnerabilities",
    # Security tools
    "scan_security_issues",
    "detect_secrets",
    "check_license_compliance",
    # Linting and type checks
    "run_linters",
    "run_type_checks",
    # Test quality tools
    "run_property_tests",
    "generate_property_tests",
    "check_contracts",
    "detect_flaky_tests",
    "compare_behavior_with_baseline",
    # Runtime analysis
    "analyze_runtime_logs",
    "analyze_performance_regression",
    "analyze_error_traces",
    # Config / migrations
    "validate_ci_config",
    "verify_migrations",
    # Refactoring utilities
    "split_python_module_classes",
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
    "get_last_tool_call",
]
