"""Provider factory for creating LLM provider instances."""

import os
from typing import Optional

from rev.llm.providers.base import LLMProvider
from rev.llm.providers.ollama import OllamaProvider
from rev.llm.providers.openai_provider import OpenAIProvider
from rev.llm.providers.anthropic_provider import AnthropicProvider
from rev.llm.providers.gemini_provider import GeminiProvider


# Cache for provider instances (singleton pattern)
_provider_cache = {}


def get_provider(provider_name: Optional[str] = None, force_new: bool = False) -> LLMProvider:
    """Get a provider instance by name.

    Args:
        provider_name: Name of the provider (ollama, openai, anthropic, gemini).
                      If None, uses REV_LLM_PROVIDER env var or defaults to ollama.
        force_new: If True, creates a new instance instead of using cached one.

    Returns:
        An instance of the requested provider.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    # Determine provider name
    if provider_name is None:
        provider_name = os.getenv("REV_LLM_PROVIDER", "ollama")

    provider_name = provider_name.lower().strip()

    # Check cache unless force_new is requested
    if not force_new and provider_name in _provider_cache:
        return _provider_cache[provider_name]

    # Create new provider instance
    if provider_name == "ollama":
        provider = OllamaProvider()
    elif provider_name == "openai":
        provider = OpenAIProvider()
    elif provider_name == "anthropic":
        provider = AnthropicProvider()
    elif provider_name == "gemini":
        provider = GeminiProvider()
    else:
        # Default to Ollama for all other provider names instead of raising ValueError.
        # This allows for custom provider names (e.g. local proxies) to work
        # automatically with the Ollama implementation.
        if os.getenv("OLLAMA_DEBUG"):
            print(f"[DEBUG] Unknown provider '{provider_name}', falling back to ollama")
        provider = OllamaProvider()

    # Cache the provider
    _provider_cache[provider_name] = provider
    return provider


def detect_provider_from_model(model_str: str) -> str:
    """Auto-detect provider from model name.

    Args:
        model_str: Model name string

    Returns:
        Provider name (ollama, openai, anthropic, or gemini)
    """
    model_str = model_str.lower().strip()

    # Check for specific model name patterns
    # Some Ollama models are GPT-prefixed (e.g., `gpt-oss`) but are still served
    # by Ollama. Keep an explicit allowlist to avoid mis-routing to OpenAI.
    if model_str.startswith("gpt-oss"):
        detected = "ollama"
    elif model_str.startswith("gpt-") or model_str.startswith("o1-"):
        detected = "openai"
    elif model_str.startswith("claude-"):
        detected = "anthropic"
    elif model_str.startswith("gemini-"):
        detected = "gemini"
    else:
        # Default to Ollama for all other models
        detected = "ollama"

    # Debug logging
    import sys
    if os.getenv("OLLAMA_DEBUG"):
        print(f"[DEBUG] detect_provider_from_model: '{model_str}' -> '{detected}'", file=sys.stderr)

    return detected


def get_provider_for_model(model: str, override_provider: Optional[str] = None) -> LLMProvider:
    """Get the appropriate provider for a given model.

    Args:
        model: Model name
        override_provider: Optional provider name to use instead of auto-detection

    Returns:
        An instance of the appropriate provider
    """
    if override_provider:
        return get_provider(override_provider)

    # Auto-detect provider from model name
    provider_name = detect_provider_from_model(model)
    return get_provider(provider_name)


def list_available_providers() -> list[str]:
    """List all available providers.

    Returns:
        List of provider names
    """
    return ["ollama", "openai", "anthropic", "gemini"]


def validate_provider(provider_name: str) -> bool:
    """Validate that a provider is configured correctly.

    Args:
        provider_name: Name of the provider to validate

    Returns:
        True if the provider is configured correctly, False otherwise
    """
    try:
        provider = get_provider(provider_name, force_new=True)
        return provider.validate_config()
    except Exception:
        return False


def clear_provider_cache():
    """Clear the provider cache.

    Useful for testing or when configuration changes.
    """
    global _provider_cache
    _provider_cache = {}
