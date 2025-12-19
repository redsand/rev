#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tool registry and execution for rev."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, TYPE_CHECKING

from rev import config
from rev.debug_logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - used only for type hints
    from rev.execution.timeout_manager import TimeoutManager, TimeoutConfig

# Import tool functions from their respective modules
from rev.tools.file_ops import (
    read_file, write_file, list_dir, delete_file, move_file,
    append_to_file, replace_in_file, create_directory, get_file_info,
    copy_file, file_exists, read_file_lines, tree_view, search_code
)
from rev.tools.code_ops import (
    remove_unused_imports, extract_constants, simplify_conditionals
)
from rev.tools.conversion import (
    convert_json_to_yaml, convert_yaml_to_json, convert_csv_to_json,
    convert_json_to_csv, convert_env_to_json
)
from rev.tools.git_ops import (
    git_diff, apply_patch, git_add, git_commit, git_status, git_log, git_branch,
    run_cmd, run_tests, get_repo_context
)
from rev.tools.ssh_ops import (
    ssh_connect, ssh_exec, ssh_copy_to, ssh_copy_from, ssh_disconnect, ssh_list_connections
)
from rev.tools.utils import (
    install_package, web_fetch, execute_python, get_system_info
)
from rev.tools.analysis import (
    analyze_ast_patterns, run_pylint, run_mypy, run_radon_complexity,
    find_dead_code, run_all_analysis, analyze_code_structures,
    analyze_static_types, check_structural_consistency
)
from rev.tools.advanced_analysis import (
    analyze_test_coverage, analyze_code_context, find_symbol_usages,
    analyze_dependencies, analyze_semantic_diff
)
from rev.tools.security import (
    scan_security_issues, detect_secrets, check_license_compliance
)
from rev.tools.dependencies import (
    check_dependency_vulnerabilities, check_dependency_updates,
    update_dependencies, scan_dependencies_vulnerabilities
)
from rev.tools.linting import run_linters, run_type_checks
from rev.tools.test_quality import (
    run_property_tests,
    generate_property_tests,
    check_contracts,
    detect_flaky_tests,
    compare_behavior_with_baseline,
    bisect_test_failure,
    generate_repro_case
)
from rev.tools.runtime_analysis import (
    analyze_runtime_logs,
    analyze_performance_regression,
    analyze_error_traces
)
from rev.tools.config_checks import (
    validate_ci_config,
    verify_migrations
)
from rev.tools.refactoring_utils import split_python_module_classes
from rev.tools.python_ast_ops import (
    rewrite_python_imports,
    rewrite_python_keyword_args,
    rename_imported_symbols,
    move_imported_symbols,
    rewrite_python_function_parameters,
)
from rev.tools.cache_ops import (
    get_cache_stats, clear_caches, persist_caches
)


def rag_search(query: str, k: int = 10, filters: dict = None) -> str:
    """Semantic code search using RAG (Retrieval-Augmented Generation).

    Args:
        query: Natural language query
        k: Number of results to return
        filters: Optional filters (language, chunk_type, file_pattern)

    Returns:
        JSON string with search results
    """
    try:
        from pathlib import Path
        from rev.retrieval import SimpleCodeRetriever

        # Initialize or reuse retriever
        retriever = SimpleCodeRetriever(root=Path.cwd(), chunk_size=50)

        if not retriever.index_built:
            retriever.build_index()

        # Query
        chunks = retriever.query(query, k=k, filters=filters)

        # Format results
        results = []
        for chunk in chunks:
            results.append({
                "location": chunk.get_location(),
                "score": chunk.score,
                "preview": chunk.get_preview(max_lines=5),
                "chunk_type": chunk.chunk_type,
                "language": chunk.metadata.get("language", "unknown")
            })

        return json.dumps({
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


logger = get_logger()

# Track last executed tool call for verification helpers
_LAST_TOOL_CALL: dict[str, Any] | None = None

# Cache for static descriptions (tools with no dynamic args)
_DESCRIPTION_CACHE = {}

# Global timeout manager instance (lazy initialization)
_TIMEOUT_MANAGER = None

_SNAPSHOT_PATH = Path(__file__).with_name("_tool_registry_snapshot.json")

# Tools that should have timeout protection
_TIMEOUT_PROTECTED_TOOLS = {
    "run_cmd",
    "run_tests",
    "execute_python",
    "search_code",
    "rag_search",
    "web_fetch",
    "ssh_exec",
    "run_pylint",
    "run_mypy",
    "analyze_static_types",
    "run_linters",
    "run_type_checks",
    "scan_security_issues",
    "run_property_tests",
    "generate_property_tests",
    "check_contracts",
    "detect_flaky_tests",
    "compare_behavior_with_baseline",
    "check_dependency_vulnerabilities",
    "check_dependency_updates",
    "analyze_runtime_logs",
    "analyze_performance_regression",
    "analyze_error_traces",
    "bisect_test_failure",
    "generate_repro_case",
    "validate_ci_config",
    "verify_migrations",
    "run_radon_complexity",
    "find_dead_code",
    "run_all_analysis",
    "remove_unused_imports",
    "update_dependencies",
    "scan_dependencies_vulnerabilities",
    "detect_secrets",
    "check_license_compliance",
    "split_python_module_classes",
}

def _get_timeout_manager() -> TimeoutManager | None:
    """Get or create the global timeout manager."""
    global _TIMEOUT_MANAGER
    if _TIMEOUT_MANAGER is None:
        # Check if timeouts are disabled via environment variable
        if os.getenv("REV_DISABLE_TIMEOUTS", "0") == "1":
            return None
        # Import lazily to avoid circular import with planning modules
        from rev.execution.timeout_manager import TimeoutManager, TimeoutConfig

        _TIMEOUT_MANAGER = TimeoutManager(TimeoutConfig.from_env())
    return _TIMEOUT_MANAGER


def _load_registry_snapshot() -> set[str]:
    """Load the baseline tool registry snapshot for guardrails."""
    try:
        data = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        names = data.get("tool_names", [])
        return {name for name in names if isinstance(name, str)}
    except FileNotFoundError:
        logger.info("Tool registry snapshot missing at %s; it will be created.", _SNAPSHOT_PATH)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to load tool registry snapshot: %s", exc)
    return set()


def _write_registry_snapshot(tool_names: set[str]) -> None:
    """Persist the given tool names to the snapshot file."""
    try:
        _SNAPSHOT_PATH.write_text(
            json.dumps({"tool_names": sorted(tool_names)}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to update tool registry snapshot: %s", exc)


def _enforce_registry_guard(tools: list[dict]) -> None:
    """Abort if any previously registered tools are missing.

    The guard compares the current tool definitions against a snapshot to
    ensure existing tool names are never removed unintentionally.
    """

    snapshot = _load_registry_snapshot()
    current = {tool.get("function", {}).get("name") for tool in tools if tool.get("function")}

    if not snapshot:
        _write_registry_snapshot(current)
        return

    missing_tools = snapshot - current
    if missing_tools:
        missing_list = ", ".join(sorted(missing_tools))
        raise RuntimeError(
            "Tool registry guard failed: missing previously registered tools: "
            f"{missing_list}. Update the snapshot after adding tools, but do not remove existing entries."
        )

    if current != snapshot:
        _write_registry_snapshot(current)


# Tool dispatch table for O(1) lookup
def _build_tool_dispatch() -> Dict[str, callable]:
    """Build the tool dispatch dictionary for fast O(1) lookup."""
    return {
        # File operations
        "read_file": lambda args: read_file(args["path"]),
        "write_file": lambda args: write_file(args["path"], args["content"]),
        "list_dir": lambda args: list_dir(args.get("pattern", "**/*")),
        "search_code": lambda args: search_code(args["pattern"], args.get("include", "**/*")),
        "rag_search": lambda args: rag_search(args["query"], args.get("k", 10), args.get("filters")),
        "delete_file": lambda args: delete_file(args["path"]),
        "move_file": lambda args: move_file(args["src"], args["dest"]),
        "append_to_file": lambda args: append_to_file(args["path"], args["content"]),
        "replace_in_file": lambda args: replace_in_file(args["path"], args["find"], args["replace"], args.get("regex", False)),
        "rewrite_python_imports": lambda args: rewrite_python_imports(
            args["path"],
            args["rules"],
            args.get("dry_run", False),
            args.get("engine", "auto"),
        ),
        "rewrite_python_keyword_args": lambda args: rewrite_python_keyword_args(
            args["path"],
            args["callee"],
            args["renames"],
            args.get("dry_run", False),
            args.get("engine", "libcst"),
        ),
        "rename_imported_symbols": lambda args: rename_imported_symbols(
            args["path"],
            args["renames"],
            args.get("dry_run", False),
            args.get("engine", "libcst"),
        ),
        "move_imported_symbols": lambda args: move_imported_symbols(
            args["path"],
            args["old_module"],
            args["new_module"],
            args["symbols"],
            args.get("dry_run", False),
            args.get("engine", "libcst"),
        ),
        "rewrite_python_function_parameters": lambda args: rewrite_python_function_parameters(
            args["path"],
            args["function"],
            args.get("rename"),
            args.get("add"),
            args.get("remove"),
            args.get("dry_run", False),
            args.get("engine", "libcst"),
        ),
        "create_directory": lambda args: create_directory(args["path"]),
        "get_file_info": lambda args: get_file_info(args["path"]),
        "copy_file": lambda args: copy_file(args["src"], args["dest"]),
        "file_exists": lambda args: file_exists(args["path"]),
        "read_file_lines": lambda args: read_file_lines(args["path"], args.get("start", 1), args.get("end")),
        "tree_view": lambda args: tree_view(args.get("path", "."), args.get("max_depth", 3), args.get("max_files", 100)),

        # Code operations
        "remove_unused_imports": lambda args: remove_unused_imports(args["file_path"], args.get("language", "python")),
        "extract_constants": lambda args: extract_constants(args["file_path"], args.get("threshold", 3)),
        "simplify_conditionals": lambda args: simplify_conditionals(args["file_path"]),

        # Data conversion
        "convert_json_to_yaml": lambda args: convert_json_to_yaml(args["json_path"], args.get("yaml_path")),
        "convert_yaml_to_json": lambda args: convert_yaml_to_json(args["yaml_path"], args.get("json_path")),
        "convert_csv_to_json": lambda args: convert_csv_to_json(args["csv_path"], args.get("json_path")),
        "convert_json_to_csv": lambda args: convert_json_to_csv(args["json_path"], args.get("csv_path")),
        "convert_env_to_json": lambda args: convert_env_to_json(args["env_path"], args.get("json_path")),

        # Git operations
        "git_diff": lambda args: git_diff(args.get("pathspec", ".")),
        "apply_patch": lambda args: apply_patch(args["patch"], args.get("dry_run", False)),
        "git_add": lambda args: git_add(args.get("files", ".")),
        "git_commit": lambda args: git_commit(args["message"], args.get("add_files", False), args.get("files", ".")),
        "git_status": lambda args: git_status(),
        "git_log": lambda args: git_log(args.get("count", 10), args.get("oneline", False)),
        "git_branch": lambda args: git_branch(args.get("action", "list"), args.get("branch_name")),
        "run_cmd": lambda args: run_cmd(args["cmd"], args.get("timeout", 300)),
        "run_tests": lambda args: run_tests(args.get("cmd", "pytest -q"), args.get("timeout", 600)),
        "get_repo_context": lambda args: get_repo_context(args.get("commits", 6)),

        # Utility tools
        "install_package": lambda args: install_package(args["package"]),
        "web_fetch": lambda args: web_fetch(args["url"]),
        "execute_python": lambda args: execute_python(args["code"]),
        "get_system_info": lambda args: get_system_info(),

        # SSH operations
        "ssh_connect": lambda args: ssh_connect(args["host"], args["username"], args.get("password"), args.get("key_file"), args.get("port", 22)),
        "ssh_exec": lambda args: ssh_exec(args["connection_id"], args["command"], args.get("timeout", 30)),
        "ssh_copy_to": lambda args: ssh_copy_to(args["connection_id"], args["local_path"], args["remote_path"]),
        "ssh_copy_from": lambda args: ssh_copy_from(args["connection_id"], args["remote_path"], args["local_path"]),
        "ssh_disconnect": lambda args: ssh_disconnect(args["connection_id"]),
        "ssh_list_connections": lambda args: ssh_list_connections(),

        # Static analysis tools
        "analyze_ast_patterns": lambda args: analyze_ast_patterns(args.get("path", "."), args.get("patterns")),
        "run_pylint": lambda args: run_pylint(args.get("path", "."), args.get("config")),
        "run_mypy": lambda args: run_mypy(args.get("path", "."), args.get("config")),
        "analyze_static_types": lambda args: analyze_static_types(
            args.get("paths"),
            args.get("config_file", "mypy.ini"),
            args.get("strict", False)
        ),
        "run_linters": lambda args: run_linters(args.get("paths")),
        "run_type_checks": lambda args: run_type_checks(args.get("paths")),
        "run_radon_complexity": lambda args: run_radon_complexity(args.get("path", "."), args.get("min_rank", "C")),
        "find_dead_code": lambda args: find_dead_code(args.get("path", ".")),
        "run_all_analysis": lambda args: run_all_analysis(args.get("path", ".")),
        "analyze_code_structures": lambda args: analyze_code_structures(args.get("path", ".")),
        "check_structural_consistency": lambda args: check_structural_consistency(args.get("path", "."), args.get("entity")),
        "scan_security_issues": lambda args: scan_security_issues(args.get("paths"), args.get("severity_threshold", "MEDIUM")),
        "detect_secrets": lambda args: detect_secrets(args.get("path", ".")),
        "check_license_compliance": lambda args: check_license_compliance(args.get("path", ".")),
        "split_python_module_classes": lambda args: (
            split_python_module_classes(
                args["source_path"],
                args.get("target_directory"),
                args.get("overwrite", False),
                args.get("delete_source", True),
            )
            if "source_path" in args
            else json.dumps({"error": "Missing required argument 'source_path' for split_python_module_classes"})
        ),
        "run_property_tests": lambda args: run_property_tests(args.get("test_paths"), args.get("max_examples", 200)),
        "generate_property_tests": lambda args: generate_property_tests(args.get("targets", []), args.get("max_examples", 200)),
        "check_contracts": lambda args: check_contracts(args.get("paths"), args.get("timeout_seconds", 60)),
        "detect_flaky_tests": lambda args: detect_flaky_tests(args.get("pattern"), args.get("runs", 5)),
        "compare_behavior_with_baseline": lambda args: compare_behavior_with_baseline(args.get("baseline_ref", "origin/main"), args.get("test_selector")),
        "analyze_runtime_logs": lambda args: analyze_runtime_logs(args.get("log_paths", []), args.get("since")),
        "analyze_performance_regression": lambda args: analyze_performance_regression(
            args["benchmark_cmd"],
            args.get("baseline_file", str(config.METRICS_DIR / "perf-baseline.json")),
            args.get("tolerance_pct", 10.0)
        ),
        "analyze_error_traces": lambda args: analyze_error_traces(args.get("log_paths", []), args.get("max_traces", 200)),
        "check_dependency_vulnerabilities": lambda args: check_dependency_vulnerabilities(args.get("language", "auto")),
        "check_dependency_updates": lambda args: check_dependency_updates(args.get("language", "auto")),
        "update_dependencies": lambda args: update_dependencies(args.get("language", "auto"), args.get("major", False)),
        "scan_dependencies_vulnerabilities": lambda args: scan_dependencies_vulnerabilities(args.get("language", "auto")),
        "bisect_test_failure": lambda args: bisect_test_failure(args["test_command"], args.get("good_ref"), args.get("bad_ref", "HEAD")),
        "generate_repro_case": lambda args: generate_repro_case(args["context"], args.get("target_path", "tests/regressions/test_repro_case.py")),
        "validate_ci_config": lambda args: validate_ci_config(args.get("paths")),
        "verify_migrations": lambda args: verify_migrations(args.get("path", "migrations")),

        # Advanced analysis tools
        "analyze_test_coverage": lambda args: analyze_test_coverage(args.get("path", "."), args.get("show_untested", True)),
        "analyze_code_context": lambda args: analyze_code_context(args["file_path"], args.get("line_range")),
        "find_symbol_usages": lambda args: find_symbol_usages(args["symbol"], args.get("scope", "project")),
        "analyze_dependencies": lambda args: analyze_dependencies(args["target"], args.get("depth", 3)),
        "analyze_semantic_diff": lambda args: analyze_semantic_diff(args["file_path"], args.get("compare_to", "HEAD")),

        # Cache operations
        "get_cache_stats": lambda args: get_cache_stats(),
        "clear_caches": lambda args: clear_caches(args.get("cache_name", "all")),
        "persist_caches": lambda args: persist_caches(),
    }


# Build dispatch table once at module load time
_TOOL_DISPATCH = _build_tool_dispatch()


def get_last_tool_call() -> dict[str, Any] | None:
    """Return the most recent tool call metadata."""
    if _LAST_TOOL_CALL is None:
        return None
    name = _LAST_TOOL_CALL.get("name")
    args = _LAST_TOOL_CALL.get("args")
    args_copy = dict(args) if isinstance(args, dict) else args
    return {"name": name, "args": args_copy}


def _handle_mcp_tool(name: str, args: Dict[str, Any]) -> str:
    """Handle MCP tools with lazy import."""
    try:
        if name == "mcp_add_server":
            from rev import mcp_add_server as mcp_add_server_impl
            return mcp_add_server_impl(args["name"], args["command"], args.get("args", ""))
        elif name == "mcp_list_servers":
            from rev import mcp_list_servers as mcp_list_servers_impl
            return mcp_list_servers_impl()
        elif name == "mcp_call_tool":
            from rev import mcp_call_tool as mcp_call_tool_impl
            return mcp_call_tool_impl(args["server"], args["tool"], args.get("arguments", "{}"))
    except ImportError:
        return json.dumps({"error": "MCP tools not available"})
    return json.dumps({"error": f"Unknown MCP tool: {name}"})


def _get_friendly_description(name: str, args: Dict[str, Any]) -> str:
    """Generate a user-friendly description for tool execution.

    Uses caching for static descriptions (tools with no dynamic arguments).
    """
    # Static descriptions (no dynamic args) - cache these
    static_descriptions = {
        "git_status", "get_system_info", "ssh_list_connections",
        "mcp_list_servers", "execute_python"
    }

    # Check cache for static descriptions
    if name in static_descriptions:
        if name not in _DESCRIPTION_CACHE:
            _DESCRIPTION_CACHE[name] = _format_description(name, args)
        return _DESCRIPTION_CACHE[name]

    # For dynamic descriptions, compute each time
    return _format_description(name, args)


def _format_description(name: str, args: Dict[str, Any]) -> str:
    """Format the friendly description for a tool."""
    # Map tool names to friendly action descriptions with key arguments
    descriptions = {
        # File operations
        "read_file": f"Reading file: {args.get('path', '')}",
        "write_file": f"Writing file: {args.get('path', '')}",
        "list_dir": f"Listing directory: {args.get('pattern', '**/*')}",
        "search_code": f"Searching code: {args.get('pattern', '')} in {args.get('include', '**/*')}",
        "rag_search": f"RAG semantic search: {args.get('query', '')}",
        "delete_file": f"Deleting file: {args.get('path', '')}",
        "move_file": f"Moving file: {args.get('src', '')} → {args.get('dest', '')}",
        "append_to_file": f"Appending to file: {args.get('path', '')}",
        "replace_in_file": f"Replacing in file: {args.get('path', '')}",
        "create_directory": f"Creating directory: {args.get('path', '')}",
        "get_file_info": f"Getting file info: {args.get('path', '')}",
        "copy_file": f"Copying file: {args.get('src', '')} → {args.get('dest', '')}",
        "file_exists": f"Checking file exists: {args.get('path', '')}",
        "read_file_lines": f"Reading lines from file: {args.get('path', '')}",
        "tree_view": f"Displaying tree view: {args.get('path', '.')}",

        # Code operations
        "remove_unused_imports": f"Removing unused imports in: {args.get('file_path', '')}",
        "extract_constants": f"Extracting constants from: {args.get('file_path', '')}",
        "simplify_conditionals": f"Simplifying conditionals in: {args.get('file_path', '')}",

        # Data conversion
        "convert_json_to_yaml": f"Converting JSON to YAML: {args.get('json_path', '')}",
        "convert_yaml_to_json": f"Converting YAML to JSON: {args.get('yaml_path', '')}",
        "convert_csv_to_json": f"Converting CSV to JSON: {args.get('csv_path', '')}",
        "convert_json_to_csv": f"Converting JSON to CSV: {args.get('json_path', '')}",
        "convert_env_to_json": f"Converting .env to JSON: {args.get('env_path', '')}",

        # Git operations
        "git_diff": f"Showing git diff: {args.get('pathspec', '.')}",
        "apply_patch": f"Applying patch{' (dry run)' if args.get('dry_run') else ''}",
        "git_add": f"Adding files to staging: {args.get('files', '.')}",
        "git_commit": f"Creating git commit{' (with auto-add)' if args.get('add_files') else ''}: {args.get('message', '')[:50]}{'...' if len(args.get('message', '')) > 50 else ''}",
        "git_status": "Getting git status",
        "git_log": f"Viewing git log ({args.get('count', 10)} commits)",
        "git_branch": f"Git branch: {args.get('action', 'list')}" + (f" {args.get('branch_name', '')}" if args.get('branch_name') else ""),
        "run_cmd": f"Running command: {args.get('cmd', '')}",
        "run_tests": f"Running tests: {args.get('cmd', 'pytest -q')}",
        "get_repo_context": f"Getting repository context ({args.get('commits', 6)} commits)",

        # Utility tools
        "install_package": f"Installing package: {args.get('package', '')}",
        "web_fetch": f"Fetching URL: {args.get('url', '')}",
        "execute_python": "Executing Python code",
        "get_system_info": "Getting system information",

        # SSH operations
        "ssh_connect": f"Connecting via SSH: {args.get('username', '')}@{args.get('host', '')}",
        "ssh_exec": f"Executing SSH command on {args.get('connection_id', '')}: {args.get('command', '')}",
        "ssh_copy_to": f"Copying to SSH server: {args.get('local_path', '')} → {args.get('remote_path', '')}",
        "ssh_copy_from": f"Copying from SSH server: {args.get('remote_path', '')} → {args.get('local_path', '')}",
        "ssh_disconnect": f"Disconnecting SSH: {args.get('connection_id', '')}",
        "ssh_list_connections": "Listing SSH connections",

        # MCP tools
        "mcp_add_server": f"Adding MCP server: {args.get('name', '')}",
        "mcp_list_servers": "Listing MCP servers",
        "mcp_call_tool": f"Calling MCP tool: {args.get('server', '')}.{args.get('tool', '')}",

        # Static analysis tools
        "analyze_ast_patterns": f"Analyzing AST patterns: {args.get('path', '.')}",
        "run_pylint": f"Running pylint on: {args.get('path', '.')}",
        "run_mypy": f"Running mypy type check on: {args.get('path', '.')}",
        "analyze_static_types": f"Running static type checks on: {args.get('paths', args.get('path', '.'))}",
        "run_linters": f"Running aggregated linters on: {args.get('paths', args.get('path', '.'))}",
        "run_type_checks": f"Running aggregated type checks on: {args.get('paths', args.get('path', '.'))}",
        "run_property_tests": f"Running property tests on: {args.get('test_paths', args.get('path', '.'))}",
        "generate_property_tests": f"Generating property tests for: {args.get('targets', [])}",
        "check_contracts": f"Checking contracts in: {args.get('paths', args.get('path', '.'))}",
        "detect_flaky_tests": f"Detecting flaky tests (pattern: {args.get('pattern', '')})",
        "compare_behavior_with_baseline": f"Comparing behavior vs {args.get('baseline_ref', 'origin/main')} on {args.get('test_selector', 'selected tests')}",
        "analyze_runtime_logs": f"Analyzing runtime logs: {args.get('log_paths', [])}",
        "analyze_performance_regression": f"Analyzing performance vs baseline using: {args.get('benchmark_cmd', '')}",
        "analyze_error_traces": f"Analyzing error traces from: {args.get('log_paths', [])}",
        "check_dependency_vulnerabilities": f"Scanning dependency vulnerabilities ({args.get('language', 'auto')})",
        "check_dependency_updates": f"Checking dependency updates ({args.get('language', 'auto')})",
        "update_dependencies": f"Updating dependencies ({args.get('language', 'auto')})",
        "scan_dependencies_vulnerabilities": f"Scanning dependency vulnerabilities ({args.get('language', 'auto')})",
        "bisect_test_failure": f"Bisecting failing test: {args.get('test_command', '')}",
        "generate_repro_case": f"Generating repro case at: {args.get('target_path', 'tests/regressions/test_repro_case.py')}",
        "validate_ci_config": f"Validating CI configs: {args.get('paths', [])}",
        "verify_migrations": f"Verifying migrations at: {args.get('path', 'migrations')}",
        "run_radon_complexity": f"Analyzing code complexity: {args.get('path', '.')}",
        "find_dead_code": f"Finding dead code in: {args.get('path', '.')}",
        "run_all_analysis": f"Running full analysis suite on: {args.get('path', '.')}",
        "analyze_code_structures": f"Analyzing code structures: {args.get('path', '.')}",
        "check_structural_consistency": f"Checking structural consistency: {args.get('path', '.')}",
        "scan_security_issues": f"Scanning security issues in: {args.get('paths', args.get('path', '.'))}",
        "detect_secrets": f"Detecting secrets in: {args.get('path', '.')}",
        "check_license_compliance": f"Checking license compliance in: {args.get('path', '.')}",
        "split_python_module_classes": f"Splitting classes from {args.get('source_path', '')} into package: {args.get('target_directory', '')}",

        # Advanced analysis tools
        "analyze_test_coverage": f"Analyzing test coverage: {args.get('path', '.')}",
        "analyze_code_context": f"Analyzing code context: {args.get('file_path', '')}",
        "find_symbol_usages": f"Finding usages of symbol: {args.get('symbol', '')}",
        "analyze_dependencies": f"Analyzing dependencies: {args.get('target', '')}",
        "analyze_semantic_diff": f"Analyzing semantic diff: {args.get('file_path', '')}",

        # Cache operations
        "get_cache_stats": "Inspecting cache statistics",
        "clear_caches": f"Clearing caches: {args.get('cache_name', 'all')}",
        "persist_caches": "Persisting caches to disk",
    }

    # Return the friendly description or fall back to technical format
    return descriptions.get(name, f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool and return result.

    Optimized for O(1) lookup using dictionary dispatch instead of O(n) elif chain.
    Tools in the timeout-protected list will be executed with automatic retry on timeout.
    """
    try:
        args = maybe_fix_tool_paths(args)
    except Exception:
        pass

    # Compatibility shim: normalize common alternate argument names that some models emit
    # (e.g. "file_path" vs the canonical "path") so tools don't KeyError.
    if isinstance(args, dict):
        # Some models mistakenly wrap tool args one level deep (e.g. {"arguments": {...}}).
        # Unwrap safely to avoid tools defaulting to empty args and doing the wrong thing.
        while (
            isinstance(args, dict)
            and len(args) == 1
            and isinstance(args.get("arguments"), dict)
        ):
            args = args["arguments"]

        tool = (name or "").lower()
        normalized_args = dict(args)

        if tool in {"read_file", "get_file_info", "delete_file", "file_exists"}:
            if "path" not in normalized_args and isinstance(normalized_args.get("file_path"), str):
                normalized_args["path"] = normalized_args["file_path"]

        if tool in {"write_file", "append_to_file"}:
            if "path" not in normalized_args and isinstance(normalized_args.get("file_path"), str):
                normalized_args["path"] = normalized_args["file_path"]
            if tool == "write_file" and "content" not in normalized_args:
                for alt in ("text", "contents", "new_content"):
                    if isinstance(normalized_args.get(alt), str):
                        normalized_args["content"] = normalized_args[alt]
                        break

        if tool == "list_dir":
            if "pattern" not in normalized_args:
                for alt in ("path", "dir", "directory", "folder", "glob"):
                    if isinstance(normalized_args.get(alt), str):
                        normalized_args["pattern"] = normalized_args[alt]
                        break

        if tool == "replace_in_file":
            if "path" not in normalized_args and isinstance(normalized_args.get("file_path"), str):
                normalized_args["path"] = normalized_args["file_path"]
            if "find" not in normalized_args and isinstance(normalized_args.get("old_string"), str):
                normalized_args["find"] = normalized_args["old_string"]
            if "replace" not in normalized_args and isinstance(normalized_args.get("new_string"), str):
                normalized_args["replace"] = normalized_args["new_string"]

        if tool == "create_directory":
            if "path" not in normalized_args:
                for alt in ("dir", "dir_path", "directory", "folder"):
                    if isinstance(normalized_args.get(alt), str):
                        normalized_args["path"] = normalized_args[alt]
                        break

        if tool == "split_python_module_classes":
            if "source_path" not in normalized_args and isinstance(normalized_args.get("module_path"), str):
                normalized_args["source_path"] = normalized_args["module_path"]
            if "target_directory" not in normalized_args and isinstance(normalized_args.get("output_dir"), str):
                normalized_args["target_directory"] = normalized_args["output_dir"]
            if "delete_source" not in normalized_args:
                # Default to True to align with "convert module to package" semantics.
                normalized_args["delete_source"] = True

        args = normalized_args

    friendly_desc = _get_friendly_description(name, args)
    print(f"  → {friendly_desc}")

    # Get debug logger
    debug_logger = get_logger()

    global _LAST_TOOL_CALL
    if isinstance(args, dict):
        _LAST_TOOL_CALL = {"name": name, "args": dict(args)}
    else:
        _LAST_TOOL_CALL = {"name": name, "args": args}

    try:
        # Check if it's an MCP tool (special handling for lazy imports)
        start_time = time.time()
        if name.startswith("mcp_"):
            result = _handle_mcp_tool(name, args)
            duration = (time.time() - start_time) * 1000
            debug_logger.log_tool_execution(name, args, result, duration_ms=duration)
            return result

        # O(1) dictionary lookup
        handler = _TOOL_DISPATCH.get(name)
        if handler is None:
            error_result = json.dumps({"error": f"Unknown tool: {name}"})
            debug_logger.log_tool_execution(name, args, error=f"Unknown tool: {name}")
            return error_result

        # Execute with timeout protection if applicable
        if name in _TIMEOUT_PROTECTED_TOOLS:
            timeout_mgr = _get_timeout_manager()
            if timeout_mgr:
                try:
                    result = timeout_mgr.execute_with_retry(
                        handler,
                        f"{name}({', '.join(f'{k}={v!r}' for k, v in list(args.items())[:2])})",
                        args
                    )
                    duration = (time.time() - start_time) * 1000
                    debug_logger.log_tool_execution(name, args, result, duration_ms=duration)
                    return result
                except Exception as e:
                    # Timeout or max retries exceeded
                    error_msg = f"{type(e).__name__}: {e}"
                    debug_logger.log_tool_execution(name, args, error=error_msg)
                    return json.dumps({"error": error_msg})

        # Execute the tool handler without timeout protection
        result = handler(args)
        duration = (time.time() - start_time) * 1000
        debug_logger.log_tool_execution(name, args, result, duration_ms=duration)
        return result

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        debug_logger.log_tool_execution(name, args, error=error_msg)
        return json.dumps({"error": error_msg})


def get_available_tools() -> list:
    """Get the list of available tools for LLM function calling.

    Returns a list of tool definitions in OpenAI format that can be passed
    to language models that support function calling.
    """
    tools = [
        # File operations
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file (creates or overwrites)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "File content"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files matching a pattern (glob syntax)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)", "default": "**/*"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search code using regex pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search"},
                        "include": {"type": "string", "description": "Glob pattern for files to search", "default": "**/*"}
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rag_search",
                "description": "Semantic code search using RAG (Retrieval-Augmented Generation). Searches codebase using natural language queries with TF-IDF scoring. More effective than regex for conceptual searches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query"},
                        "k": {"type": "integer", "description": "Number of results to return", "default": 10},
                        "filters": {"type": "object", "description": "Optional filters: language, chunk_type, file_pattern"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file to delete"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move or rename a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source file path"},
                        "dest": {"type": "string", "description": "Destination file path"}
                    },
                    "required": ["src", "dest"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "append_to_file",
                "description": "Append content to end of file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "Content to append"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "replace_in_file",
                "description": "Find and replace text in a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "find": {"type": "string", "description": "Text to find"},
                        "replace": {"type": "string", "description": "Replacement text"},
                        "regex": {"type": "boolean", "description": "Use regex pattern", "default": False}
                    },
                    "required": ["path", "find", "replace"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rewrite_python_imports",
                "description": "Rewrite Python import statements using AST parsing (safer than string replace). Prefer this for import-path migrations; falls back to replace_in_file for non-import edits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to a .py file"},
                        "rules": {
                            "type": "array",
                            "description": "Rewrite rules: [{from_module,to_module,match}] where match is 'exact'|'prefix'",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from_module": {"type": "string"},
                                    "to_module": {"type": "string"},
                                    "match": {"type": "string", "enum": ["exact", "prefix"], "default": "exact"}
                                },
                                "required": ["from_module", "to_module"]
                            }
                        },
                        "dry_run": {"type": "boolean", "description": "If true, do not write file; return diff only", "default": False}
                        ,
                        "engine": {
                            "type": "string",
                            "description": "Rewrite engine: 'auto' (prefer libcst), 'libcst' (require format-preserving), or 'ast' (stdlib fallback)",
                            "enum": ["auto", "libcst", "ast"],
                            "default": "auto"
                        }
                    },
                    "required": ["path", "rules"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rewrite_python_keyword_args",
                "description": "Rename keyword arguments at call sites for a specific callee (libcst format-preserving).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to a .py file"},
                        "callee": {"type": "string", "description": "Callee to match (e.g., 'foo' or 'obj.foo')"},
                        "renames": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old": {"type": "string"},
                                    "new": {"type": "string"}
                                },
                                "required": ["old", "new"]
                            }
                        },
                        "dry_run": {"type": "boolean", "default": False},
                        "engine": {"type": "string", "enum": ["libcst", "auto"], "default": "libcst"}
                    },
                    "required": ["path", "callee", "renames"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rename_imported_symbols",
                "description": "Rename imported symbol(s) and update references in the same file (libcst + qualified name resolution).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to a .py file"},
                        "renames": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from_module": {"type": "string", "description": "Optional module filter"},
                                    "old_name": {"type": "string"},
                                    "new_name": {"type": "string"}
                                },
                                "required": ["old_name", "new_name"]
                            }
                        },
                        "dry_run": {"type": "boolean", "default": False},
                        "engine": {"type": "string", "enum": ["libcst", "auto"], "default": "libcst"}
                    },
                    "required": ["path", "renames"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_imported_symbols",
                "description": "Move specific symbols from `from old_module import ...` to `from new_module import ...` within one file (preserves formatting).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to a .py file"},
                        "old_module": {"type": "string"},
                        "new_module": {"type": "string"},
                        "symbols": {"type": "array", "items": {"type": "string"}},
                        "dry_run": {"type": "boolean", "default": False},
                        "engine": {"type": "string", "enum": ["libcst", "auto"], "default": "libcst"}
                    },
                    "required": ["path", "old_module", "new_module", "symbols"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rewrite_python_function_parameters",
                "description": "Add/remove/rename function parameters and update call sites (conservative, file-scoped; format-preserving).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to a .py file"},
                        "function": {"type": "string", "description": "Target function name (e.g., 'foo' or 'Class.method')"},
                        "rename": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                                "required": ["old", "new"]
                            },
                            "default": []
                        },
                        "add": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}, "default": {"type": "string"}},
                                "required": ["name", "default"]
                            },
                            "default": []
                        },
                        "remove": {"type": "array", "items": {"type": "string"}, "default": []},
                        "dry_run": {"type": "boolean", "default": False},
                        "engine": {"type": "string", "enum": ["libcst", "auto"], "default": "libcst"}
                    },
                    "required": ["path", "function"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_directory",
                "description": "Create a directory (including parent directories)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path to create"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_info",
                "description": "Get file metadata (size, modified time, etc)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "copy_file",
                "description": "Copy a file to a new location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source file path"},
                        "dest": {"type": "string", "description": "Destination file path"}
                    },
                    "required": ["src", "dest"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_exists",
                "description": "Check if a file exists",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to check"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_lines",
                "description": "Read specific lines from a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file"},
                        "start": {"type": "integer", "description": "Starting line number", "default": 1},
                        "end": {"type": "integer", "description": "Ending line number (optional)"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tree_view",
                "description": "Display directory tree structure",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path", "default": "."},
                        "max_depth": {"type": "integer", "description": "Maximum depth to traverse", "default": 3},
                        "max_files": {"type": "integer", "description": "Maximum files to show", "default": 100}
                    }
                }
            }
        },

        # Code operations
        {
            "type": "function",
            "function": {
                "name": "remove_unused_imports",
                "description": "Remove unused imports from a source file using autoflake (Python only).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to code file to clean"},
                        "language": {"type": "string", "description": "Language of the file", "default": "python"}
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "extract_constants",
                "description": "Analyze code for repeated literals and suggest constants to extract.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to code file to analyze"},
                        "threshold": {"type": "integer", "description": "Minimum occurrences before suggesting a constant", "default": 3}
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "simplify_conditionals",
                "description": "Detect complex conditionals (deep boolean expressions, nested ternaries) that should be simplified.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to code file to inspect"}
                    },
                    "required": ["file_path"]
                }
            }
        },

        # Data conversion
        {
            "type": "function",
            "function": {
                "name": "convert_json_to_yaml",
                "description": "Convert a JSON file to YAML format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "json_path": {"type": "string", "description": "Path to JSON file to convert"},
                        "yaml_path": {"type": "string", "description": "Optional output path for the YAML file"}
                    },
                    "required": ["json_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "convert_yaml_to_json",
                "description": "Convert a YAML file to JSON format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "yaml_path": {"type": "string", "description": "Path to YAML file to convert"},
                        "json_path": {"type": "string", "description": "Optional output path for the JSON file"}
                    },
                    "required": ["yaml_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "convert_csv_to_json",
                "description": "Convert a CSV file into JSON array format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "csv_path": {"type": "string", "description": "Path to CSV file"},
                        "json_path": {"type": "string", "description": "Optional output path for the JSON file"}
                    },
                    "required": ["csv_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "convert_json_to_csv",
                "description": "Convert a JSON array of objects to CSV format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "json_path": {"type": "string", "description": "Path to JSON file"},
                        "csv_path": {"type": "string", "description": "Optional output path for the CSV file"}
                    },
                    "required": ["json_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "convert_env_to_json",
                "description": "Convert a .env file to JSON representation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "env_path": {"type": "string", "description": "Path to .env file"},
                        "json_path": {"type": "string", "description": "Optional output path for the JSON file"}
                    },
                    "required": ["env_path"]
                }
            }
        },

        # Git operations
        {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Show git diff for current changes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pathspec": {"type": "string", "description": "Path or pattern to diff", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Apply a unified diff patch to files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patch": {"type": "string", "description": "Unified diff patch content"},
                        "dry_run": {"type": "boolean", "description": "Test patch without applying", "default": False}
                    },
                    "required": ["patch"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_add",
                "description": "Add files to git staging area",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "files": {"type": "string", "description": "Files to add (path or pattern)", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": "Create a git commit. Use git_add first to stage files, or set add_files=true to auto-stage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"},
                        "add_files": {"type": "boolean", "description": "Automatically add files before committing", "default": False},
                        "files": {"type": "string", "description": "Files to add if add_files is true", "default": "."}
                    },
                    "required": ["message"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_status",
                "description": "Get git status",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_log",
                "description": "View git commit history",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of commits to show", "default": 10},
                        "oneline": {"type": "boolean", "description": "Show one line per commit", "default": False}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "git_branch",
                "description": "Git branch operations (list, create, delete)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action: list, create, delete", "default": "list"},
                        "branch_name": {"type": "string", "description": "Branch name for create/delete"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_cmd",
                "description": "Execute a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 300}
                    },
                    "required": ["cmd"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Run test suite",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Test command", "default": "pytest -q"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 600}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_repo_context",
                "description": "Get repository status and recent commits",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "commits": {"type": "integer", "description": "Number of recent commits", "default": 6}
                    }
                }
            }
        },

        # Utility tools
        {
            "type": "function",
            "function": {
                "name": "install_package",
                "description": "Install a Python package via pip",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "package": {"type": "string", "description": "Package name to install"}
                    },
                    "required": ["package"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Fetch content from a URL",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": "Execute Python code in a subprocess",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"}
                    },
                    "required": ["code"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_system_info",
                "description": "Get system information (OS, platform, architecture)",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },

        # Cache operations
        {
            "type": "function",
            "function": {
                "name": "get_cache_stats",
                "description": "Inspect cache statistics (file content, LLM responses, repo context, dependencies).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "clear_caches",
                "description": "Clear one cache or all caches (file content, LLM response, repo context, dependency tree).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cache_name": {"type": "string", "description": "Cache to clear: file_content, llm_response, repo_context, dependency_tree, or all", "default": "all"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "persist_caches",
                "description": "Persist all caches to disk so the session can resume later.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },

        # SSH operations
        {
            "type": "function",
            "function": {
                "name": "ssh_connect",
                "description": "Connect to a remote server via SSH",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "description": "Hostname or IP"},
                        "username": {"type": "string", "description": "SSH username"},
                        "password": {"type": "string", "description": "SSH password (optional)"},
                        "key_file": {"type": "string", "description": "Path to private key file (optional)"},
                        "port": {"type": "integer", "description": "SSH port", "default": 22}
                    },
                    "required": ["host", "username"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_exec",
                "description": "Execute command on remote SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "command": {"type": "string", "description": "Command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}
                    },
                    "required": ["connection_id", "command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_copy_to",
                "description": "Copy local file to remote SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "local_path": {"type": "string", "description": "Local file path"},
                        "remote_path": {"type": "string", "description": "Remote file path"}
                    },
                    "required": ["connection_id", "local_path", "remote_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_copy_from",
                "description": "Copy file from remote SSH server to local",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"},
                        "remote_path": {"type": "string", "description": "Remote file path"},
                        "local_path": {"type": "string", "description": "Local file path"}
                    },
                    "required": ["connection_id", "remote_path", "local_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_disconnect",
                "description": "Disconnect from SSH server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string", "description": "SSH connection ID"}
                    },
                    "required": ["connection_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ssh_list_connections",
                "description": "List active SSH connections",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },

        # MCP tools
        {
            "type": "function",
            "function": {
                "name": "mcp_add_server",
                "description": "Add a new MCP server configuration",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Server name"},
                        "command": {"type": "string", "description": "Server command to execute"},
                        "args": {"type": "string", "description": "Server arguments (optional)", "default": ""}
                    },
                    "required": ["name", "command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_list_servers",
                "description": "List configured MCP servers",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call_tool",
                "description": "Call a tool from an MCP server",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "MCP server name"},
                        "tool": {"type": "string", "description": "Tool name"},
                        "arguments": {"type": "string", "description": "Tool arguments as JSON", "default": "{}"}
                    },
                    "required": ["server", "tool"]
                }
            }
        },

        # Static analysis tools
        {
            "type": "function",
            "function": {
                "name": "analyze_ast_patterns",
                "description": "Analyze Python code using AST for pattern matching (cross-platform). Detects TODOs, print statements, dangerous functions, missing type hints, complex functions, global variables. More accurate than regex.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to Python file or directory", "default": "."},
                        "patterns": {"type": "array", "items": {"type": "string"}, "description": "Patterns to check: todos, prints, dangerous, type_hints, complex_functions, globals"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_pylint",
                "description": "Run pylint static code analysis (cross-platform). Checks code errors, style violations, code smells, unused imports, naming conventions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "config": {"type": "string", "description": "Path to pylintrc config file (optional)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_mypy",
                "description": "Run mypy static type checking (cross-platform). Verifies type hints and catches type-related bugs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "config": {"type": "string", "description": "Path to mypy.ini config file (optional)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_static_types",
                "description": "Run mypy across one or more paths with optional strict mode. Returns structured issues and summary counts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to analyze", "default": ["."]},
                        "config_file": {"type": "string", "description": "Path to mypy config file", "default": "mypy.ini"},
                        "strict": {"type": "boolean", "description": "Enable mypy strict mode", "default": False}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_linters",
                "description": "Run aggregated linters (Ruff/flake8, ESLint, golangci-lint) across provided paths and return parsed issues.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to lint", "default": ["."]}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_type_checks",
                "description": "Run aggregated type checkers (mypy/pyright/tsc) where configs exist, returning structured errors and summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to type-check", "default": ["."]}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_property_tests",
                "description": "Run pytest suites that use Hypothesis with configurable max_examples.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "test_paths": {"type": "array", "items": {"type": "string"}, "description": "Test paths to run", "default": ["tests"]},
                        "max_examples": {"type": "integer", "description": "Hypothesis max examples per test", "default": 200}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_property_tests",
                "description": "Generate Hypothesis property tests for target functions and run them.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "targets": {"type": "array", "items": {"type": "string"}, "description": "Targets like 'path/to/file.py::function'", "default": []},
                        "max_examples": {"type": "integer", "description": "Hypothesis max examples per test", "default": 200}
                    },
                    "required": ["targets"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_contracts",
                "description": "Run CrossHair contract checking to find counterexamples to annotated functions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to check", "default": ["."]},
                        "timeout_seconds": {"type": "integer", "description": "Per-path timeout seconds", "default": 60}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "detect_flaky_tests",
                "description": "Run pytest multiple times to find tests that pass and fail intermittently.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Pytest pattern to select tests"},
                        "runs": {"type": "integer", "description": "Number of repetitions", "default": 5}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "compare_behavior_with_baseline",
                "description": "Run selected tests on a baseline git ref vs current and report semantic differences.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "baseline_ref": {"type": "string", "description": "Git ref for baseline", "default": "origin/main"},
                        "test_selector": {"type": "string", "description": "Pytest selector, e.g., tests/test_file.py::TestClass"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_runtime_logs",
                "description": "Parse runtime logs for warnings, errors, and tracebacks; cluster and summarize findings.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "log_paths": {"type": "array", "items": {"type": "string"}, "description": "Log file paths to analyze"},
                        "since": {"type": "string", "description": "ISO timestamp; only include log entries after this time"}
                    },
                    "required": ["log_paths"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_performance_regression",
                "description": "Run benchmarks and compare to stored baseline metrics with tolerance threshold.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "benchmark_cmd": {"type": "string", "description": "Command to run benchmarks (e.g., pytest ... --benchmark-only)"},
                        "baseline_file": {"type": "string", "description": "Path to baseline metrics file", "default": str(config.METRICS_DIR / "perf-baseline.json")},
                        "tolerance_pct": {"type": "number", "description": "Allowed performance regression percentage", "default": 10.0}
                    },
                    "required": ["benchmark_cmd"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_error_traces",
                "description": "Cluster stack traces from logs and identify suspected modules.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "log_paths": {"type": "array", "items": {"type": "string"}, "description": "Log files containing stack traces"},
                        "max_traces": {"type": "integer", "description": "Maximum traces to analyze", "default": 200}
                    },
                    "required": ["log_paths"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_dependency_vulnerabilities",
                "description": "Scan Python/Node dependencies for known vulnerabilities using pip-audit or npm audit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "description": "Language/ecosystem (auto/python/javascript)", "default": "auto"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_dependency_updates",
                "description": "Identify outdated dependencies and group by impact (breaking/minor/patch).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "description": "Language/ecosystem (auto/python/javascript)", "default": "auto"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_dependencies",
                "description": "Alias for check_dependency_updates to maintain backward compatibility with earlier toolkits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "description": "Language/ecosystem (auto/python/javascript)", "default": "auto"},
                        "major": {"type": "boolean", "description": "Ignored legacy flag for requesting major upgrades", "default": False}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scan_dependencies_vulnerabilities",
                "description": "Alias for check_dependency_vulnerabilities (pip-audit / npm audit).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "description": "Language/ecosystem (auto/python/javascript)", "default": "auto"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "bisect_test_failure",
                "description": "Use git bisect to locate the commit that causes a test failure.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "test_command": {"type": "string", "description": "Command to run the failing test"},
                        "good_ref": {"type": "string", "description": "Known good git ref"},
                        "bad_ref": {"type": "string", "description": "Known bad git ref", "default": "HEAD"}
                    },
                    "required": ["test_command", "good_ref"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_repro_case",
                "description": "Create a minimal regression test file from provided context/logs and run it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "context": {"type": "string", "description": "Failing stack trace or description"},
                        "target_path": {"type": "string", "description": "Path to write the repro test", "default": "tests/regressions/test_repro_case.py"}
                    },
                    "required": ["context"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "validate_ci_config",
                "description": "Validate CI configuration files (GitHub Actions via actionlint/yamllint).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Specific CI config paths to check"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "verify_migrations",
                "description": "Lightweight migration sanity checks (presence and optional Alembic dry-run).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to migration directory", "default": "migrations"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_radon_complexity",
                "description": "Analyze code complexity using radon (cross-platform). Measures cyclomatic complexity, maintainability index, and code metrics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."},
                        "min_rank": {"type": "string", "description": "Minimum complexity rank to report (A-F)", "default": "C"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_dead_code",
                "description": "Find dead/unused code using vulture (cross-platform). Detects unused functions, classes, variables, imports, and unreachable code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_all_analysis",
                "description": "Run all available static analysis tools and combine results (cross-platform). Includes AST analysis, pylint, mypy, radon, and vulture.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_code_structures",
                "description": "Analyze code structures across multiple languages and file types. Detects: database schemas (Prisma, SQL), TypeScript/JavaScript (interfaces, types, enums, classes), Python (classes, Enum), C/C++ (struct, typedef, enum), configuration files, and documentation. CRITICAL: always use this before creating new structures to avoid duplication and find existing definitions to reuse.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file or directory to analyze for code structures", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_structural_consistency",
                "description": "Cross-check schemas and models across DB, backend, and frontend layers. Highlights missing fields, type mismatches, and enum value drift.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to scan for schemas/models", "default": "."},
                        "entity": {"type": "string", "description": "Optional entity name to focus on"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scan_security_issues",
                "description": "Run Bandit/Ruff security checks to find hardcoded secrets, unsafe APIs, and injection patterns. Filter by severity threshold.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to scan for security issues", "default": ["."]},
                        "severity_threshold": {"type": "string", "description": "Minimum severity to report (LOW/MEDIUM/HIGH/CRITICAL)", "default": "MEDIUM"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "detect_secrets",
                "description": "Run detect-secrets against the repository to find accidentally committed credentials.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to scan", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_license_compliance",
                "description": "Review dependency licenses (pip-licenses / license-checker) and flag restrictive licenses.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Project root to inspect", "default": "."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "split_python_module_classes",
                "description": "Split top-level classes from a module into individual files inside a package directory and regenerate __init__.py exports. Note: some models use aliases `module_path` for `source_path` and `output_dir` for `target_directory` (both are accepted).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string", "description": "Path to the module to split (e.g., src/module.py)"},
                        "target_directory": {"type": "string", "description": "Directory/package for extracted classes", "default": None},
                        "overwrite": {"type": "boolean", "description": "Overwrite files if they already exist", "default": False},
                        "delete_source": {"type": "boolean", "description": "Move the original source module aside (.bak) so the package becomes the import target", "default": True}
                    },
                    "required": ["source_path"]
                }
            }
        },

        # Advanced analysis tools
        {
            "type": "function",
            "function": {
                "name": "analyze_test_coverage",
                "description": "Analyze test coverage using coverage.py (Python) or Istanbul/nyc (JavaScript/TypeScript). Identifies untested code paths and critical gaps. Use BEFORE modifying code to ensure adequate test coverage exists.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to analyze coverage for", "default": "."},
                        "show_untested": {"type": "boolean", "description": "Show untested functions and lines", "default": True}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_code_context",
                "description": "Analyze code history and context using git blame, commit history, and comments. Shows WHY code exists, what bugs were fixed, change frequency, and warnings. Use BEFORE refactoring to understand original intent and avoid re-introducing bugs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file to analyze"},
                        "line_range": {"type": "array", "items": {"type": "integer"}, "description": "Optional [start_line, end_line] to focus analysis"}
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_symbol_usages",
                "description": "Find all usages of a symbol (function, class, variable, type) across the codebase. Shows where it's defined, referenced, and imported. Use BEFORE renaming, deleting, or modifying to understand impact. Returns safe_to_delete and rename_impact assessments.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Symbol name to find (e.g., 'UserRole', 'authenticate', 'Config')"},
                        "scope": {"type": "string", "description": "Search scope", "enum": ["project", "file", "directory"], "default": "project"}
                    },
                    "required": ["symbol"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_dependencies",
                "description": "Build dependency graph showing what code depends on the target (reverse dependencies) and what the target depends on (forward dependencies). Calculates impact radius and detects circular dependencies. Use BEFORE major refactoring to understand ripple effects.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "File path or symbol to analyze dependencies for"},
                        "depth": {"type": "integer", "description": "Dependency traversal depth", "default": 3}
                    },
                    "required": ["target"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_semantic_diff",
                "description": "Analyze semantic changes beyond line diffs. Detects breaking changes (signature changes, deleted functions), behavior changes (error handling, control flow), and performance impacts. Use AFTER making changes to verify backward compatibility.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file to analyze"},
                        "compare_to": {"type": "string", "description": "Git ref to compare against", "default": "HEAD"}
                    },
                    "required": ["file_path"]
                }
            }
        }
    ]

    _enforce_registry_guard(tools)
    return tools
