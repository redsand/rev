#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent settings management for rev."""

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from rev import config

# Location for persisted settings
SETTINGS_FILE = config.SETTINGS_FILE
LEGACY_SETTINGS_FILE = config.ROOT / ".rev_settings.json"


# Mode presets and aliases
MODE_PRESETS: Dict[str, Dict[str, Any]] = {
    "simple": {
        "orchestrate": False,
        "research": False,
        "learn": False,
        "review": True,
        "review_strictness": "lenient",
        "research_depth": "shallow",
        "validate": False,
        "auto_fix": False,
        "action_review": False,
        "parallel": 1,
        "description": "Fast execution with minimal overhead",
    },
    "advanced": {
        "orchestrate": True,
        "research": True,
        "learn": False,
        "review": True,
        "review_strictness": "moderate",
        "research_depth": "medium",
        "validate": True,
        "auto_fix": False,
        "action_review": False,
        "parallel": 4,
        "description": "Balanced approach with orchestration",
    },
    "deep": {
        "orchestrate": True,
        "research": True,
        "learn": True,
        "review": True,
        "review_strictness": "strict",
        "research_depth": "deep",
        "validate": True,
        "auto_fix": True,
        "action_review": True,
        "parallel": 4,
        "description": "Comprehensive analysis and validation",
    },
}

MODE_ALIASES = {
    "standard": "advanced",
    "thorough": "deep",
    "max": "deep",
}

DEFAULT_MODE_NAME = "advanced"


@dataclass
class RuntimeSetting:
    """Runtime setting that can be viewed and updated from the REPL."""

    key: str
    description: str
    section: str
    parser: Callable[[Any], Any]
    getter: Callable[[], Any]
    setter: Callable[[Any], None]
    default: Any


def _parse_positive_int(value: Any) -> int:
    """Parse and validate a positive integer setting."""

    parsed = int(str(value).strip())
    if parsed < 1:
        raise ValueError("Value must be at least 1")
    return parsed


def _parse_non_negative_int(value: Any) -> int:
    """Parse and validate a non-negative integer setting."""

    parsed = int(str(value).strip())
    if parsed < 0:
        raise ValueError("Value cannot be negative")
    return parsed


def _parse_positive_float(value: Any) -> float:
    """Parse and validate a positive float setting."""

    parsed = float(str(value).strip())
    if parsed <= 0:
        raise ValueError("Value must be greater than 0")
    return parsed


def _parse_float_between_zero_and_one(value: Any) -> float:
    """Parse a float constrained to the inclusive range [0, 1]."""

    parsed = float(str(value).strip())
    if not 0 <= parsed <= 1:
        raise ValueError("Value must be between 0 and 1")
    return parsed


def _parse_temperature(value: Any) -> float:
    """Parse and validate temperature setting (0.0-2.0)."""

    parsed = float(str(value).strip())
    if not 0.0 <= parsed <= 2.0:
        raise ValueError("Temperature must be between 0.0 and 2.0")
    return parsed


def _parse_bool(value: Any) -> bool:
    """Parse boolean-like inputs (true/false, yes/no, 1/0)."""

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False

    raise ValueError("Value must be a boolean (true/false)")


def _parse_choice(value: Any, *, choices: set[str], case_insensitive: bool = True) -> str:
    """Validate that the value is one of the allowed choices."""

    raw = str(value).strip()
    candidate = raw.lower() if case_insensitive else raw
    normalized_choices = {c.lower() if case_insensitive else c for c in choices}
    if candidate not in normalized_choices:
        allowed_display = ", ".join(sorted(normalized_choices))
        raise ValueError(f"Value must be one of: {allowed_display}")
    return candidate if case_insensitive else raw


def _parse_non_empty_str(value: Any) -> str:
    """Parse and validate a non-empty string setting."""

    parsed = str(value).strip()
    if not parsed:
        raise ValueError("Value cannot be empty")
    return parsed


def _parse_optional_str(value: Any) -> str:
    """Parse a string setting that may be empty (used to clear values)."""

    if value is None:
        return ""
    return str(value).strip()


def _set_private_mode_runtime(enabled: bool) -> None:
    """Apply private mode changes and refresh MCP server registry."""

    config.set_private_mode(enabled)
    os.environ["REV_PRIVATE_MODE"] = "true" if enabled else "false"

    # Reload MCP servers to reflect privacy changes
    try:
        from rev.mcp.client import mcp_client

        mcp_client.servers.clear()
        mcp_client._load_default_servers()
    except Exception:
        # Avoid hard failures if MCP is unavailable in the current context
        pass


def _mask_api_key(api_key: str) -> str:
    """Mask an API key for display purposes."""
    if not api_key:
        return "(not set)"
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _set_api_key_runtime(provider: str, api_key: str) -> None:
    """Set API key for a provider and save to secrets file."""
    from rev.secrets_manager import set_api_key

    # Save to secrets file
    set_api_key(provider, api_key)

    # Update config module
    if provider == "openai":
        config.OPENAI_API_KEY = api_key
    elif provider == "anthropic":
        config.ANTHROPIC_API_KEY = api_key
    elif provider == "gemini":
        config.GEMINI_API_KEY = api_key


RUNTIME_SETTINGS: Dict[str, RuntimeSetting] = {
    "model": RuntimeSetting(
        key="model",
        description="Active LLM model for all agent phases",
        section="Models",
        parser=_parse_non_empty_str,
        getter=lambda: config.OLLAMA_MODEL,
        setter=lambda value: config.set_model(value),
        default=config.DEFAULT_OLLAMA_MODEL,
    ),
    "execution_model": RuntimeSetting(
        key="execution_model",
        description="Model used for execution tasks (overrides /model)",
        section="Models",
        parser=_parse_non_empty_str,
        getter=lambda: config.EXECUTION_MODEL,
        setter=lambda value: setattr(config, "EXECUTION_MODEL", value),
        default=config.EXECUTION_MODEL,
    ),
    "execution_model_fallback": RuntimeSetting(
        key="execution_model_fallback",
        description="Fallback execution model used after repeated tool failures",
        section="Models",
        parser=_parse_optional_str,
        getter=lambda: config.EXECUTION_MODEL_FALLBACK,
        setter=lambda value: setattr(config, "EXECUTION_MODEL_FALLBACK", value),
        default=config.EXECUTION_MODEL_FALLBACK,
    ),
    "planning_model": RuntimeSetting(
        key="planning_model",
        description="Model used for planning tasks (overrides /model)",
        section="Models",
        parser=_parse_non_empty_str,
        getter=lambda: config.PLANNING_MODEL,
        setter=lambda value: setattr(config, "PLANNING_MODEL", value),
        default=config.PLANNING_MODEL,
    ),
    "research_model": RuntimeSetting(
        key="research_model",
        description="Model used for research tasks (overrides /model)",
        section="Models",
        parser=_parse_non_empty_str,
        getter=lambda: config.RESEARCH_MODEL,
        setter=lambda value: setattr(config, "RESEARCH_MODEL", value),
        default=config.RESEARCH_MODEL,
    ),
    "ollama_base_url": RuntimeSetting(
        key="ollama_base_url",
        description="Base URL for the Ollama server",
        section="Models",
        parser=_parse_non_empty_str,
        getter=lambda: config.OLLAMA_BASE_URL,
        setter=lambda value: setattr(config, "OLLAMA_BASE_URL", value),
        default=config.DEFAULT_OLLAMA_BASE_URL,
    ),
    "execution_supports_tools": RuntimeSetting(
        key="execution_supports_tools",
        description="Whether the execution model supports tool usage",
        section="Models",
        parser=_parse_bool,
        getter=lambda: config.EXECUTION_SUPPORTS_TOOLS,
        setter=lambda value: setattr(config, "EXECUTION_SUPPORTS_TOOLS", value),
        default=config.EXECUTION_SUPPORTS_TOOLS,
    ),
    "planning_supports_tools": RuntimeSetting(
        key="planning_supports_tools",
        description="Whether the planning model supports tool usage",
        section="Models",
        parser=_parse_bool,
        getter=lambda: config.PLANNING_SUPPORTS_TOOLS,
        setter=lambda value: setattr(config, "PLANNING_SUPPORTS_TOOLS", value),
        default=config.PLANNING_SUPPORTS_TOOLS,
    ),
    "tdd_enabled": RuntimeSetting(
        key="tdd_enabled",
        description="Enable test-driven development enforcement (requires tests to run)",
        section="Testing",
        parser=_parse_bool,
        getter=lambda: getattr(config, "TDD_ENABLED", False),
        setter=lambda value: setattr(config, "TDD_ENABLED", value),
        default=getattr(config, "TDD_ENABLED", False),
    ),
    "tdd_defer_tests": RuntimeSetting(
        key="tdd_defer_tests",
        description="Defer auto-injected TDD test runs until after implementation steps",
        section="Testing",
        parser=_parse_bool,
        getter=lambda: getattr(config, "TDD_DEFER_TEST_EXECUTION", True),
        setter=lambda value: setattr(config, "TDD_DEFER_TEST_EXECUTION", value),
        default=getattr(config, "TDD_DEFER_TEST_EXECUTION", True),
    ),
    "research_supports_tools": RuntimeSetting(
        key="research_supports_tools",
        description="Whether the research model supports tool usage",
        section="Models",
        parser=_parse_bool,
        getter=lambda: config.RESEARCH_SUPPORTS_TOOLS,
        setter=lambda value: setattr(config, "RESEARCH_SUPPORTS_TOOLS", value),
        default=config.RESEARCH_SUPPORTS_TOOLS,
    ),
    "temperature": RuntimeSetting(
        key="temperature",
        description="LLM temperature (0.0-2.0; lower = more deterministic)",
        section="LLM Generation",
        parser=_parse_temperature,
        getter=lambda: config.OLLAMA_TEMPERATURE,
        setter=lambda value: setattr(config, "OLLAMA_TEMPERATURE", value),
        default=0.1,
    ),
    "num_ctx": RuntimeSetting(
        key="num_ctx",
        description="Context window size in tokens (e.g., 8192, 16384, 32768)",
        section="LLM Generation",
        parser=_parse_positive_int,
        getter=lambda: config.OLLAMA_NUM_CTX,
        setter=lambda value: setattr(config, "OLLAMA_NUM_CTX", value),
        default=16384,
    ),
    "top_p": RuntimeSetting(
        key="top_p",
        description="Top-p nucleus sampling (0.0-1.0)",
        section="LLM Generation",
        parser=_parse_float_between_zero_and_one,
        getter=lambda: config.OLLAMA_TOP_P,
        setter=lambda value: setattr(config, "OLLAMA_TOP_P", value),
        default=0.9,
    ),
    "top_k": RuntimeSetting(
        key="top_k",
        description="Top-k vocabulary limiting (positive integer)",
        section="LLM Generation",
        parser=_parse_positive_int,
        getter=lambda: config.OLLAMA_TOP_K,
        setter=lambda value: setattr(config, "OLLAMA_TOP_K", value),
        default=40,
    ),
    "thinking_mode": RuntimeSetting(
        key="thinking_mode",
        description="Thinking mode (auto tries once per model; off disables)",
        section="LLM Generation",
        parser=lambda value: _parse_choice(value, choices={"auto", "off"}),
        getter=lambda: getattr(config, "LLM_THINKING_MODE", "auto"),
        setter=lambda value: setattr(config, "LLM_THINKING_MODE", value),
        default=getattr(config, "LLM_THINKING_MODE", "auto"),
    ),
    "validation_mode": RuntimeSetting(
        key="validation_mode",
        description="Default validation mode (none, smoke, targeted, full)",
        section="Validation",
        parser=lambda value: _parse_choice(
            value, choices={"none", "smoke", "targeted", "full"}
        ),
        getter=lambda: config.VALIDATION_MODE_DEFAULT,
        setter=lambda value: setattr(config, "VALIDATION_MODE_DEFAULT", value),
        default=config.VALIDATION_MODE_DEFAULT,
    ),
    "max_read_file_per_task": RuntimeSetting(
        key="max_read_file_per_task",
        description="Maximum number of /read calls per task",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_READ_FILE_PER_TASK,
        setter=lambda value: setattr(config, "MAX_READ_FILE_PER_TASK", value),
        default=config.MAX_READ_FILE_PER_TASK,
    ),
    "max_search_code_per_task": RuntimeSetting(
        key="max_search_code_per_task",
        description="Maximum number of /search code calls per task",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_SEARCH_CODE_PER_TASK,
        setter=lambda value: setattr(config, "MAX_SEARCH_CODE_PER_TASK", value),
        default=config.MAX_SEARCH_CODE_PER_TASK,
    ),
    "max_run_cmd_per_task": RuntimeSetting(
        key="max_run_cmd_per_task",
        description="Maximum number of /run_cmd calls per task",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_RUN_CMD_PER_TASK,
        setter=lambda value: setattr(config, "MAX_RUN_CMD_PER_TASK", value),
        default=config.MAX_RUN_CMD_PER_TASK,
    ),
    "max_execution_iterations": RuntimeSetting(
        key="max_execution_iterations",
        description="Maximum execution loop iterations before stopping",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_EXECUTION_ITERATIONS,
        setter=lambda value: setattr(config, "MAX_EXECUTION_ITERATIONS", value),
        default=config.MAX_EXECUTION_ITERATIONS,
    ),
    "max_task_iterations": RuntimeSetting(
        key="max_task_iterations",
        description="Maximum iterations allowed per task across execution modes",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_TASK_ITERATIONS,
        setter=lambda value: setattr(config, "MAX_TASK_ITERATIONS", value),
        default=config.MAX_TASK_ITERATIONS,
    ),
    "context_window_history": RuntimeSetting(
        key="context_window_history",
        description="Number of recent messages retained before trimming context",
        section="Execution Limits",
        parser=_parse_positive_int,
        getter=lambda: config.CONTEXT_WINDOW_HISTORY,
        setter=lambda value: setattr(config, "CONTEXT_WINDOW_HISTORY", value),
        default=config.CONTEXT_WINDOW_HISTORY,
    ),
    "loop_guard_enabled": RuntimeSetting(
        key="loop_guard_enabled",
        description="Enable loop guard that injects alternative actions after repeated identical tasks",
        section="Execution Limits",
        parser=_parse_bool,
        getter=lambda: getattr(config, "LOOP_GUARD_ENABLED", True),
        setter=lambda value: setattr(config, "LOOP_GUARD_ENABLED", value),
        default=getattr(config, "LOOP_GUARD_ENABLED", True),
    ),
    "workspace_root_only": RuntimeSetting(
        key="workspace_root_only",
        description="Restrict operations to the workspace root (REV_WORKSPACE_ROOT_ONLY)",
        section="Execution Limits",
        parser=_parse_bool,
        getter=lambda: getattr(config, "WORKSPACE_ROOT_ONLY", True),
        setter=lambda value: setattr(config, "WORKSPACE_ROOT_ONLY", value),
        default=getattr(config, "WORKSPACE_ROOT_ONLY", True),
    ),
    "test_executor_fallback_enabled": RuntimeSetting(
        key="test_executor_fallback_enabled",
        description="Enable fallback to generic test commands when explicit tool runs fail",
        section="Testing",
        parser=_parse_bool,
        getter=lambda: getattr(config, "TEST_EXECUTOR_FALLBACK_ENABLED", False),
        setter=lambda value: setattr(config, "TEST_EXECUTOR_FALLBACK_ENABLED", value),
        default=getattr(config, "TEST_EXECUTOR_FALLBACK_ENABLED", False),
    ),
    "test_executor_command_correction_enabled": RuntimeSetting(
        key="test_executor_command_correction_enabled",
        description="Enable automatic correction of test commands (heuristic)",
        section="Testing",
        parser=_parse_bool,
        getter=lambda: getattr(config, "TEST_EXECUTOR_COMMAND_CORRECTION_ENABLED", False),
        setter=lambda value: setattr(config, "TEST_EXECUTOR_COMMAND_CORRECTION_ENABLED", value),
        default=getattr(config, "TEST_EXECUTOR_COMMAND_CORRECTION_ENABLED", False),
    ),
    "context_guard_enabled": RuntimeSetting(
        key="context_guard_enabled",
        description="Enable context-guard on retrieved content similarity",
        section="Safety",
        parser=_parse_bool,
        getter=lambda: getattr(config, "ENABLE_CONTEXT_GUARD", True),
        setter=lambda value: setattr(config, "ENABLE_CONTEXT_GUARD", value),
        default=getattr(config, "ENABLE_CONTEXT_GUARD", True),
    ),
    "context_guard_interactive": RuntimeSetting(
        key="context_guard_interactive",
        description="Prompt interactively when context-guard triggers",
        section="Safety",
        parser=_parse_bool,
        getter=lambda: getattr(config, "CONTEXT_GUARD_INTERACTIVE", True),
        setter=lambda value: setattr(config, "CONTEXT_GUARD_INTERACTIVE", value),
        default=getattr(config, "CONTEXT_GUARD_INTERACTIVE", True),
    ),
    "context_guard_threshold": RuntimeSetting(
        key="context_guard_threshold",
        description="Similarity threshold for context-guard (0-1)",
        section="Safety",
        parser=_parse_float_between_zero_and_one,
        getter=lambda: getattr(config, "CONTEXT_GUARD_THRESHOLD", 0.3),
        setter=lambda value: setattr(config, "CONTEXT_GUARD_THRESHOLD", value),
        default=getattr(config, "CONTEXT_GUARD_THRESHOLD", 0.3),
    ),
    "preflight_enabled": RuntimeSetting(
        key="preflight_enabled",
        description="Enable preflight path/action corrections before executing tasks (DISABLED - marked for removal)",
        section="Execution Limits",
        parser=_parse_bool,
        getter=lambda: getattr(config, "PREFLIGHT_ENABLED", False),
        setter=lambda value: setattr(config, "PREFLIGHT_ENABLED", value),
        default=getattr(config, "PREFLIGHT_ENABLED", False),
    ),
    "max_planning_iterations": RuntimeSetting(
        key="max_planning_iterations",
        description="Maximum tool-calling iterations during planning (separate from max_plan_tasks)",
        section="Planning Limits",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_PLANNING_TOOL_ITERATIONS,
        setter=lambda value: setattr(config, "MAX_PLANNING_TOOL_ITERATIONS", value),
        default=config.MAX_PLANNING_TOOL_ITERATIONS,
    ),
    "max_steps_per_run": RuntimeSetting(
        key="max_steps_per_run",
        description="Resource budget: maximum steps per run",
        section="Resource Budgets",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_STEPS_PER_RUN,
        setter=lambda value: setattr(config, "MAX_STEPS_PER_RUN", value),
        default=config.MAX_STEPS_PER_RUN,
    ),
    "max_llm_tokens_per_run": RuntimeSetting(
        key="max_llm_tokens_per_run",
        description="Resource budget: maximum tokens per run",
        section="Resource Budgets",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_LLM_TOKENS_PER_RUN,
        setter=lambda value: setattr(config, "MAX_LLM_TOKENS_PER_RUN", value),
        default=config.MAX_LLM_TOKENS_PER_RUN,
    ),
    "max_wallclock_seconds": RuntimeSetting(
        key="max_wallclock_seconds",
        description="Resource budget: maximum wallclock seconds per run",
        section="Resource Budgets",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_WALLCLOCK_SECONDS,
        setter=lambda value: setattr(config, "MAX_WALLCLOCK_SECONDS", value),
        default=config.MAX_WALLCLOCK_SECONDS,
    ),
    "max_plan_tasks": RuntimeSetting(
        key="max_plan_tasks",
        description="Resource budget: maximum tasks in generated plans",
        section="Resource Budgets",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_PLAN_TASKS,
        setter=lambda value: setattr(config, "MAX_PLAN_TASKS", value),
        default=config.MAX_PLAN_TASKS,
    ),
    "research_depth": RuntimeSetting(
        key="research_depth",
        description="Default research depth (off, shallow, medium, deep)",
        section="Research",
        parser=lambda value: _parse_choice(
            value, choices={"off", "shallow", "medium", "deep"}
        ),
        getter=lambda: config.RESEARCH_DEPTH_DEFAULT,
        setter=lambda value: setattr(config, "RESEARCH_DEPTH_DEFAULT", value),
        default=config.RESEARCH_DEPTH_DEFAULT,
    ),
    "orchestrator_retries": RuntimeSetting(
        key="orchestrator_retries",
        description="Number of orchestrator retries for coordination",
        section="Retries",
        parser=_parse_non_negative_int,
        getter=lambda: config.MAX_ORCHESTRATOR_RETRIES,
        setter=lambda value: setattr(config, "MAX_ORCHESTRATOR_RETRIES", value),
        default=config.MAX_ORCHESTRATOR_RETRIES,
    ),
    "plan_regen_retries": RuntimeSetting(
        key="plan_regen_retries",
        description="Retries allowed when regenerating plans",
        section="Retries",
        parser=_parse_non_negative_int,
        getter=lambda: config.MAX_PLAN_REGEN_RETRIES,
        setter=lambda value: setattr(config, "MAX_PLAN_REGEN_RETRIES", value),
        default=config.MAX_PLAN_REGEN_RETRIES,
    ),
    "validation_retries": RuntimeSetting(
        key="validation_retries",
        description="Retries allowed during validation",
        section="Retries",
        parser=_parse_non_negative_int,
        getter=lambda: config.MAX_VALIDATION_RETRIES,
        setter=lambda value: setattr(config, "MAX_VALIDATION_RETRIES", value),
        default=config.MAX_VALIDATION_RETRIES,
    ),
    "adaptive_replans": RuntimeSetting(
        key="adaptive_replans",
        description="Adaptive replans allowed after failed validation",
        section="Retries",
        parser=_parse_non_negative_int,
        getter=lambda: config.MAX_ADAPTIVE_REPLANS,
        setter=lambda value: setattr(config, "MAX_ADAPTIVE_REPLANS", value),
        default=config.MAX_ADAPTIVE_REPLANS,
    ),
    "validation_timeout_seconds": RuntimeSetting(
        key="validation_timeout_seconds",
        description="Timeout for validation steps (seconds)",
        section="Validation",
        parser=_parse_positive_int,
        getter=lambda: config.VALIDATION_TIMEOUT_SECONDS,
        setter=lambda value: setattr(config, "VALIDATION_TIMEOUT_SECONDS", value),
        default=config.VALIDATION_TIMEOUT_SECONDS,
    ),
    "log_retention": RuntimeSetting(
        key="log_retention",
        description="Number of .rev/logs files to keep (newest preserved)",
        section="Logging",
        parser=_parse_positive_int,
        getter=lambda: config.LOG_RETENTION_LIMIT,
        setter=lambda value: setattr(config, "LOG_RETENTION_LIMIT", value),
        default=config.LOG_RETENTION_LIMIT_DEFAULT,
    ),
    "llm_trace_enabled": RuntimeSetting(
        key="llm_trace_enabled",
        description="Log full LLM requests/responses to llm_transactions.log",
        section="Logging",
        parser=_parse_bool,
        getter=lambda: getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False),
        setter=lambda value: setattr(config, "LLM_TRANSACTION_LOG_ENABLED", value),
        default=getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False),
    ),
    "history_size": RuntimeSetting(
        key="history_size",
        description="Number of history entries to keep in-memory",
        section="History",
        parser=_parse_positive_int,
        getter=lambda: config.HISTORY_SIZE,
        setter=lambda value: setattr(config, "HISTORY_SIZE", value),
        default=config.HISTORY_SIZE,
    ),
    "history_file": RuntimeSetting(
        key="history_file",
        description="Path to persist history (empty to disable)",
        section="History",
        parser=lambda value: str(value).strip(),
        getter=lambda: config.HISTORY_FILE,
        setter=lambda value: setattr(config, "HISTORY_FILE", value),
        default=config.HISTORY_FILE,
    ),
    "paste_threshold": RuntimeSetting(
        key="paste_threshold",
        description="Line-count threshold to detect pasted input",
        section="Input",
        parser=_parse_positive_int,
        getter=lambda: config.PASTE_THRESHOLD,
        setter=lambda value: setattr(config, "PASTE_THRESHOLD", value),
        default=config.PASTE_THRESHOLD,
    ),
    "paste_time_threshold": RuntimeSetting(
        key="paste_time_threshold",
        description="Inter-line time threshold (seconds) for paste detection",
        section="Input",
        parser=_parse_positive_float,
        getter=lambda: config.PASTE_TIME_THRESHOLD,
        setter=lambda value: setattr(config, "PASTE_TIME_THRESHOLD", value),
        default=config.PASTE_TIME_THRESHOLD,
    ),
    "escape_interval": RuntimeSetting(
        key="escape_interval",
        description="Interval for escape key polling (seconds)",
        section="Input",
        parser=_parse_positive_float,
        getter=lambda: config.ESCAPE_INTERVAL,
        setter=lambda value: setattr(config, "ESCAPE_INTERVAL", value),
        default=config.ESCAPE_INTERVAL,
    ),
    "escape_timeout": RuntimeSetting(
        key="escape_timeout",
        description="Escape key timeout (seconds)",
        section="Input",
        parser=_parse_positive_float,
        getter=lambda: config.ESCAPE_TIMEOUT,
        setter=lambda value: setattr(config, "ESCAPE_TIMEOUT", value),
        default=config.ESCAPE_TIMEOUT,
    ),
    "prefer_reuse": RuntimeSetting(
        key="prefer_reuse",
        description="Prefer reusing existing files over creating new ones",
        section="Code Reuse",
        parser=_parse_bool,
        getter=lambda: config.PREFER_REUSE,
        setter=lambda value: setattr(config, "PREFER_REUSE", value),
        default=config.PREFER_REUSE,
    ),
    "warn_on_new_files": RuntimeSetting(
        key="warn_on_new_files",
        description="Warn when creating new files instead of reusing",
        section="Code Reuse",
        parser=_parse_bool,
        getter=lambda: config.WARN_ON_NEW_FILES,
        setter=lambda value: setattr(config, "WARN_ON_NEW_FILES", value),
        default=config.WARN_ON_NEW_FILES,
    ),
    "require_reuse_justification": RuntimeSetting(
        key="require_reuse_justification",
        description="Require justification when not reusing existing files",
        section="Code Reuse",
        parser=_parse_bool,
        getter=lambda: config.REQUIRE_REUSE_JUSTIFICATION,
        setter=lambda value: setattr(config, "REQUIRE_REUSE_JUSTIFICATION", value),
        default=config.REQUIRE_REUSE_JUSTIFICATION,
    ),
    "max_files_per_feature": RuntimeSetting(
        key="max_files_per_feature",
        description="Maximum files encouraged for a single feature",
        section="Code Reuse",
        parser=_parse_positive_int,
        getter=lambda: config.MAX_FILES_PER_FEATURE,
        setter=lambda value: setattr(config, "MAX_FILES_PER_FEATURE", value),
        default=config.MAX_FILES_PER_FEATURE,
    ),
    "similarity_threshold": RuntimeSetting(
        key="similarity_threshold",
        description="Similarity threshold for file name reuse suggestions",
        section="Code Reuse",
        parser=_parse_float_between_zero_and_one,
        getter=lambda: config.SIMILARITY_THRESHOLD,
        setter=lambda value: setattr(config, "SIMILARITY_THRESHOLD", value),
        default=config.SIMILARITY_THRESHOLD,
    ),
    "openai_api_key": RuntimeSetting(
        key="openai_api_key",
        description="OpenAI API key (saved securely in .rev/secrets.json)",
        section="API Keys",
        parser=lambda value: str(value).strip(),
        getter=lambda: _mask_api_key(config.OPENAI_API_KEY),
        setter=lambda value: _set_api_key_runtime("openai", value),
        default="",
    ),
    "anthropic_api_key": RuntimeSetting(
        key="anthropic_api_key",
        description="Anthropic API key (saved securely in .rev/secrets.json)",
        section="API Keys",
        parser=lambda value: str(value).strip(),
        getter=lambda: _mask_api_key(config.ANTHROPIC_API_KEY),
        setter=lambda value: _set_api_key_runtime("anthropic", value),
        default="",
    ),
    "gemini_api_key": RuntimeSetting(
        key="gemini_api_key",
        description="Google Gemini API key (saved securely in .rev/secrets.json)",
        section="API Keys",
        parser=lambda value: str(value).strip(),
        getter=lambda: _mask_api_key(config.GEMINI_API_KEY),
        setter=lambda value: _set_api_key_runtime("gemini", value),
        default="",
    ),
    "llm_provider": RuntimeSetting(
        key="llm_provider",
        description="Active LLM provider (ollama, openai, anthropic, gemini)",
        section="API Keys",
        parser=lambda value: _parse_choice(
            value, choices={"ollama", "openai", "anthropic", "gemini"}
        ),
        getter=lambda: config.LLM_PROVIDER,
        setter=lambda value: setattr(config, "LLM_PROVIDER", value),
        default=config.LLM_PROVIDER,
    ),
    "private_mode": RuntimeSetting(
        key="private_mode",
        description="Enable to disable all public MCP servers",
        section="Privacy",
        parser=_parse_bool,
        getter=lambda: config.get_private_mode(),
        setter=_set_private_mode_runtime,
        default=config.DEFAULT_PRIVATE_MODE,
    ),
    "mcp_memory_enabled": RuntimeSetting(
        key="mcp_memory_enabled",
        description="Enable MCP memory server for persistent context",
        section="MCP Servers",
        parser=_parse_bool,
        getter=lambda: config.DEFAULT_MCP_SERVERS.get("memory", {}).get("enabled", False),
        setter=lambda value: config.DEFAULT_MCP_SERVERS.get("memory", {}).update({"enabled": value}) if "memory" in config.DEFAULT_MCP_SERVERS else None,
        default=True,
    ),
    "mcp_sequential_thinking_enabled": RuntimeSetting(
        key="mcp_sequential_thinking_enabled",
        description="Enable MCP sequential thinking server",
        section="MCP Servers",
        parser=_parse_bool,
        getter=lambda: config.DEFAULT_MCP_SERVERS.get("sequential-thinking", {}).get("enabled", True),
        setter=lambda value: config.DEFAULT_MCP_SERVERS.get("sequential-thinking", {}).update({"enabled": value}) if "sequential-thinking" in config.DEFAULT_MCP_SERVERS else None,
        default=True,
    ),
    "forbid_shell_security": RuntimeSetting(
        key="forbid_shell_security",
        description="Block shell metacharacters and dangerous tokens in commands (False permits &&, ||, |)",
        section="Execution",
        parser=_parse_bool,
        getter=lambda: getattr(config, "forbid_shell_security", False),
        setter=lambda value: setattr(config, "forbid_shell_security", value),
        default=getattr(config, "forbid_shell_security", False),
    ),
    "mcp_fetch_enabled": RuntimeSetting(
        key="mcp_fetch_enabled",
        description="Enable MCP fetch server for HTTP requests",
        section="MCP Servers",
        parser=_parse_bool,
        getter=lambda: config.DEFAULT_MCP_SERVERS.get("fetch", {}).get("enabled", True),
        setter=lambda value: config.DEFAULT_MCP_SERVERS.get("fetch", {}).update({"enabled": value}) if "fetch" in config.DEFAULT_MCP_SERVERS else None,
        default=True,
    ),
}


def get_runtime_setting(key: str) -> Optional[RuntimeSetting]:
    """Return a runtime setting by key if it exists."""

    return RUNTIME_SETTINGS.get(key)


def list_runtime_settings_by_section() -> Dict[str, list[RuntimeSetting]]:
    """Return runtime settings grouped by section for display."""

    grouped: Dict[str, list[RuntimeSetting]] = {}
    for setting in RUNTIME_SETTINGS.values():
        grouped.setdefault(setting.section, []).append(setting)

    for settings in grouped.values():
        settings.sort(key=lambda item: item.key)

    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def set_runtime_setting(key: str, raw_value: Any) -> Any:
    """Update a runtime setting value using its parser for validation."""

    setting = get_runtime_setting(key)
    if not setting:
        raise KeyError(key)

    parsed_value = setting.parser(raw_value)
    setting.setter(parsed_value)
    return parsed_value


def get_runtime_settings_snapshot() -> Dict[str, Any]:
    """Return a snapshot of runtime setting values for persistence.

    Note: API keys are excluded from snapshots as they are stored separately
    in secrets.json to avoid saving masked values.
    """
    # Exclude API keys from snapshots - they're stored in secrets.json
    api_key_settings = {"openai_api_key", "anthropic_api_key", "gemini_api_key"}

    return {
        key: setting.getter()
        for key, setting in RUNTIME_SETTINGS.items()
        if key not in api_key_settings
    }


def apply_runtime_settings(saved: Dict[str, Any]) -> None:
    """Apply saved runtime settings from disk."""

    for key, value in saved.items():
        setting = get_runtime_setting(key)
        if not setting:
            continue
        try:
            parsed_value = setting.parser(value)
            setting.setter(parsed_value)
        except Exception:
            # Ignore invalid persisted values to avoid breaking startup
            continue


def reset_runtime_settings() -> None:
    """Reset runtime settings to their defaults."""

    for setting in RUNTIME_SETTINGS.values():
        setting.setter(setting.default)


def get_mode_config(mode_name: str) -> Tuple[str, Dict[str, Any]]:
    """Get a normalized mode name and its configuration."""

    normalized = MODE_ALIASES.get(mode_name.lower(), mode_name.lower())
    config_template = MODE_PRESETS.get(normalized)
    if not config_template:
        normalized = DEFAULT_MODE_NAME
        config_template = MODE_PRESETS[normalized]
    return normalized, deepcopy(config_template)


def get_default_mode() -> Tuple[str, Dict[str, Any]]:
    """Return the default mode and configuration."""

    return get_mode_config(DEFAULT_MODE_NAME)


def load_settings() -> Dict[str, Any]:
    """Load persisted settings from disk if they exist."""

    def _migrate_legacy_settings_file() -> None:
        """Move legacy .rev_settings.json into the consolidated .rev directory."""

        if not LEGACY_SETTINGS_FILE.exists():
            return

        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

        try:
            if not SETTINGS_FILE.exists():
                LEGACY_SETTINGS_FILE.rename(SETTINGS_FILE)
            else:
                LEGACY_SETTINGS_FILE.unlink()
        except OSError:
            # If migration fails, continue using the legacy file location for this run
            return

    try:
        _migrate_legacy_settings_file()

        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        # Fail gracefully and fall back to defaults
        return {}
    return {}


def save_settings(session_context: Dict[str, Any]) -> Path:
    """Persist the current settings to disk."""

    settings = {
        "model": config.OLLAMA_MODEL,
        "base_url": config.OLLAMA_BASE_URL,
        "private_mode": config.get_private_mode(),
        "execution_mode": session_context.get("execution_mode", DEFAULT_MODE_NAME),
        "mode_config": session_context.get("mode_config", get_default_mode()[1]),
        "runtime_settings": get_runtime_settings_snapshot(),
    }

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
    return SETTINGS_FILE


def apply_saved_settings(session_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Apply persisted settings to config and optional session context."""

    settings = load_settings()
    if not settings:
        return None

    private_mode_before = config.get_private_mode()

    if settings.get("model"):
        config.set_model(settings["model"])
    if settings.get("base_url"):
        config.OLLAMA_BASE_URL = settings["base_url"]
    if "private_mode" in settings:
        private_mode = bool(settings["private_mode"])
        config.set_private_mode(private_mode)
        os.environ["REV_PRIVATE_MODE"] = "true" if private_mode else "false"

    if session_context is not None:
        mode_name, default_mode_config = get_default_mode()
        saved_mode = settings.get("execution_mode", mode_name)
        normalized_mode, normalized_config = get_mode_config(saved_mode)
        merged_config = {**normalized_config, **settings.get("mode_config", {})}
        session_context["execution_mode"] = normalized_mode
        session_context["mode_config"] = merged_config

    if settings.get("runtime_settings"):
        apply_runtime_settings(settings.get("runtime_settings", {}))

    # Reload MCP servers if private mode changed
    if config.get_private_mode() != private_mode_before:
        try:
            from rev.mcp.client import mcp_client

            mcp_client.servers.clear()
            mcp_client._load_default_servers()
        except Exception:
            pass

    return settings


def reset_settings(session_context: Optional[Dict[str, Any]] = None) -> None:
    """Reset settings to defaults and remove persisted configuration."""

    config.set_model(config.DEFAULT_OLLAMA_MODEL)
    config.OLLAMA_BASE_URL = config.DEFAULT_OLLAMA_BASE_URL
    config.set_private_mode(config.DEFAULT_PRIVATE_MODE)
    os.environ["REV_PRIVATE_MODE"] = "true" if config.DEFAULT_PRIVATE_MODE else "false"

    reset_runtime_settings()

    if SETTINGS_FILE.exists():
        SETTINGS_FILE.unlink()

    if session_context is not None:
        mode_name, mode_config = get_default_mode()
        session_context["execution_mode"] = mode_name
        session_context["mode_config"] = mode_config

    try:
        from rev.mcp.client import mcp_client

        mcp_client.servers.clear()
        mcp_client._load_default_servers()
    except Exception:
        pass
