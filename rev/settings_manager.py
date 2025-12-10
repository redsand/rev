#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent settings management for rev."""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
        "parallel": 2,
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
        "parallel": 3,
        "description": "Comprehensive analysis and validation",
    },
}

MODE_ALIASES = {
    "standard": "advanced",
    "thorough": "deep",
    "max": "deep",
}

DEFAULT_MODE_NAME = "advanced"


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
        config.OLLAMA_MODEL = settings["model"]
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

    config.OLLAMA_MODEL = config.DEFAULT_OLLAMA_MODEL
    config.OLLAMA_BASE_URL = config.DEFAULT_OLLAMA_BASE_URL
    config.set_private_mode(config.DEFAULT_PRIVATE_MODE)
    os.environ["REV_PRIVATE_MODE"] = "true" if config.DEFAULT_PRIVATE_MODE else "false"

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
