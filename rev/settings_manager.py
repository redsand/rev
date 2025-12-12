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
SETTINGS_FILE = config.ROOT / ".rev_settings.json"


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
        "parallel": 1,
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
        "parallel": 1,
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


RUNTIME_SETTINGS: Dict[str, RuntimeSetting] = {
    "log_retention": RuntimeSetting(
        key="log_retention",
        description="Number of .rev_logs files to keep (newest preserved)",
        section="Logging",
        parser=_parse_positive_int,
        getter=lambda: config.LOG_RETENTION_LIMIT,
        setter=lambda value: setattr(config, "LOG_RETENTION_LIMIT", value),
        default=config.LOG_RETENTION_LIMIT_DEFAULT,
    )
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
    """Return a snapshot of runtime setting values for persistence."""

    return {key: setting.getter() for key, setting in RUNTIME_SETTINGS.items()}


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

    try:
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
