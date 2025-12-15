#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Secure secrets management for API keys and sensitive configuration."""

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from rev import config


# Secrets file location (separate from regular settings for security)
SECRETS_FILE = config.REV_DIR / "secrets.json"


def _ensure_secure_permissions(file_path: Path) -> None:
    """Ensure the secrets file has secure permissions (600 - owner read/write only)."""
    if file_path.exists():
        try:
            # Set file to be readable/writable only by owner
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            # Windows doesn't support Unix permissions, skip on error
            pass


def load_secrets() -> Dict[str, Any]:
    """Load secrets from the secrets file.

    Returns:
        Dict containing saved secrets, or empty dict if file doesn't exist
    """
    if not SECRETS_FILE.exists():
        return {}

    try:
        _ensure_secure_permissions(SECRETS_FILE)
        with open(SECRETS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load secrets file: {e}")
        return {}


def save_secrets(secrets: Dict[str, Any]) -> None:
    """Save secrets to the secrets file with secure permissions.

    Args:
        secrets: Dict of secrets to save
    """
    # Ensure .rev directory exists
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write secrets file
    with open(SECRETS_FILE, 'w') as f:
        json.dump(secrets, f, indent=2)

    # Ensure secure permissions
    _ensure_secure_permissions(SECRETS_FILE)


def get_secret(key: str, default: Any = None) -> Any:
    """Get a secret value by key.

    Args:
        key: Secret key to retrieve
        default: Default value if key not found

    Returns:
        Secret value or default
    """
    secrets = load_secrets()
    return secrets.get(key, default)


def set_secret(key: str, value: Any) -> None:
    """Set a secret value.

    Args:
        key: Secret key to set
        value: Secret value
    """
    secrets = load_secrets()
    secrets[key] = value
    save_secrets(secrets)


def delete_secret(key: str) -> bool:
    """Delete a secret value.

    Args:
        key: Secret key to delete

    Returns:
        True if key was deleted, False if it didn't exist
    """
    secrets = load_secrets()
    if key in secrets:
        del secrets[key]
        save_secrets(secrets)
        return True
    return False


def list_secret_keys() -> list[str]:
    """List all secret keys (not values).

    Returns:
        List of secret key names
    """
    secrets = load_secrets()
    return list(secrets.keys())


def clear_all_secrets() -> None:
    """Clear all secrets (use with caution)."""
    save_secrets({})


# API Key management functions

def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider.

    Checks in order:
    1. Environment variable
    2. Saved secrets file
    3. Returns None if not found

    Args:
        provider: Provider name (openai, anthropic, gemini)

    Returns:
        API key or None
    """
    provider = provider.lower()

    # Map provider to env var name
    env_var_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }

    env_var = env_var_map.get(provider)
    if env_var:
        # Check environment variable first
        env_value = os.getenv(env_var)
        if env_value:
            return env_value

    # Check secrets file
    secret_key = f"{provider}_api_key"
    return get_secret(secret_key)


def set_api_key(provider: str, api_key: str) -> None:
    """Save API key for a provider.

    Args:
        provider: Provider name (openai, anthropic, gemini)
        api_key: API key to save
    """
    provider = provider.lower()
    secret_key = f"{provider}_api_key"
    set_secret(secret_key, api_key)

    # Also update the config module for immediate use
    if provider == "openai":
        config.OPENAI_API_KEY = api_key
    elif provider == "anthropic":
        config.ANTHROPIC_API_KEY = api_key
    elif provider == "gemini":
        config.GEMINI_API_KEY = api_key

    # Clear provider cache so it picks up the new key
    from rev.llm.provider_factory import clear_provider_cache
    clear_provider_cache()


def delete_api_key(provider: str) -> bool:
    """Delete API key for a provider.

    Args:
        provider: Provider name (openai, anthropic, gemini)

    Returns:
        True if key was deleted, False if it didn't exist
    """
    provider = provider.lower()
    secret_key = f"{provider}_api_key"
    result = delete_secret(secret_key)

    # Update config to clear the key
    if result:
        if provider == "openai":
            config.OPENAI_API_KEY = ""
        elif provider == "anthropic":
            config.ANTHROPIC_API_KEY = ""
        elif provider == "gemini":
            config.GEMINI_API_KEY = ""

        # Clear provider cache
        from rev.llm.provider_factory import clear_provider_cache
        clear_provider_cache()

    return result


def load_api_keys_to_config() -> None:
    """Load saved API keys into the config module.

    This should be called at startup to ensure saved keys are available.
    """
    providers = ["openai", "anthropic", "gemini"]

    for provider in providers:
        api_key = get_api_key(provider)
        if api_key:
            if provider == "openai":
                config.OPENAI_API_KEY = api_key
            elif provider == "anthropic":
                config.ANTHROPIC_API_KEY = api_key
            elif provider == "gemini":
                config.GEMINI_API_KEY = api_key


def mask_api_key(api_key: str) -> str:
    """Mask an API key for display (show first/last 4 chars).

    Args:
        api_key: API key to mask

    Returns:
        Masked API key string
    """
    if not api_key:
        return "(not set)"

    if len(api_key) <= 8:
        return "*" * len(api_key)

    return f"{api_key[:4]}...{api_key[-4:]}"
