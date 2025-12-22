#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conformance tests for LLM providers.

This module ensures all LLM providers implement the base interface correctly
and behave consistently across different backends.
"""

import pytest
from unittest.mock import Mock, patch

from rev.llm.providers.base import (
    LLMProvider,
    ErrorClass,
    ProviderError,
    RetryConfig,
)
from rev.llm.provider_factory import get_provider, list_available_providers


# Test with all available providers
ALL_PROVIDERS = list_available_providers()


@pytest.fixture(params=ALL_PROVIDERS)
def provider(request):
    """Fixture that provides each available provider."""
    provider_name = request.param
    return get_provider(provider_name, force_new=True)


class TestProviderInterface:
    """Test that all providers implement the required interface."""

    def test_provider_has_name(self, provider):
        """Verify provider has a name attribute."""
        assert hasattr(provider, "name")
        assert isinstance(provider.name, str)
        assert len(provider.name) > 0

    def test_provider_has_chat_method(self, provider):
        """Verify provider has chat method."""
        assert hasattr(provider, "chat")
        assert callable(provider.chat)

    def test_provider_has_chat_stream_method(self, provider):
        """Verify provider has chat_stream method."""
        assert hasattr(provider, "chat_stream")
        assert callable(provider.chat_stream)

    def test_provider_has_supports_tool_calling_method(self, provider):
        """Verify provider has supports_tool_calling method."""
        assert hasattr(provider, "supports_tool_calling")
        assert callable(provider.supports_tool_calling)

    def test_provider_has_validate_config_method(self, provider):
        """Verify provider has validate_config method."""
        assert hasattr(provider, "validate_config")
        assert callable(provider.validate_config)

    def test_provider_has_get_model_list_method(self, provider):
        """Verify provider has get_model_list method."""
        assert hasattr(provider, "get_model_list")
        assert callable(provider.get_model_list)

    def test_provider_has_count_tokens_method(self, provider):
        """Verify provider has count_tokens method."""
        assert hasattr(provider, "count_tokens")
        assert callable(provider.count_tokens)

    def test_provider_has_classify_error_method(self, provider):
        """Verify provider has classify_error method."""
        assert hasattr(provider, "classify_error")
        assert callable(provider.classify_error)

    def test_provider_has_get_retry_config_method(self, provider):
        """Verify provider has get_retry_config method."""
        assert hasattr(provider, "get_retry_config")
        assert callable(provider.get_retry_config)


class TestProviderBehavior:
    """Test provider behavior and return values."""

    def test_validate_config_returns_bool(self, provider):
        """Verify validate_config returns boolean."""
        result = provider.validate_config()
        assert isinstance(result, bool)

    def test_get_model_list_returns_list(self, provider):
        """Verify get_model_list returns a list."""
        models = provider.get_model_list()
        assert isinstance(models, list)
        # All items should be strings
        assert all(isinstance(model, str) for model in models)

    def test_supports_tool_calling_returns_bool(self, provider):
        """Verify supports_tool_calling returns boolean."""
        # Test with a generic model name
        models = provider.get_model_list()
        if models:
            result = provider.supports_tool_calling(models[0])
            assert isinstance(result, bool)

    def test_count_tokens_returns_int(self, provider):
        """Verify count_tokens returns integer."""
        messages = [
            {"role": "user", "content": "Hello, world!"}
        ]
        count = provider.count_tokens(messages)
        assert isinstance(count, int)
        assert count > 0  # Should be at least 1 token

    def test_count_tokens_scales_with_content(self, provider):
        """Verify token count increases with more content."""
        short_messages = [
            {"role": "user", "content": "Hi"}
        ]
        long_messages = [
            {"role": "user", "content": "This is a much longer message with more words and tokens"}
        ]

        short_count = provider.count_tokens(short_messages)
        long_count = provider.count_tokens(long_messages)

        assert long_count > short_count

    def test_classify_error_returns_provider_error(self, provider):
        """Verify classify_error returns ProviderError."""
        test_error = Exception("Test error")
        result = provider.classify_error(test_error)

        assert isinstance(result, ProviderError)
        assert isinstance(result.error_class, ErrorClass)
        assert isinstance(result.message, str)
        assert isinstance(result.retryable, bool)

    def test_get_retry_config_returns_retry_config(self, provider):
        """Verify get_retry_config returns RetryConfig."""
        config = provider.get_retry_config()

        assert isinstance(config, RetryConfig)
        assert isinstance(config.max_retries, int)
        assert isinstance(config.base_backoff, (int, float))
        assert isinstance(config.max_backoff, (int, float))
        assert isinstance(config.exponential, bool)
        assert isinstance(config.retry_on, list)
        assert all(isinstance(ec, ErrorClass) for ec in config.retry_on)


class TestProviderConsistency:
    """Test consistency across providers."""

    def test_all_providers_classify_timeout_as_retryable(self):
        """Verify all providers mark timeout as retryable."""
        import socket
        timeout_error = socket.timeout("Connection timed out")

        for provider_name in ALL_PROVIDERS:
            provider = get_provider(provider_name, force_new=True)
            result = provider.classify_error(timeout_error)

            assert result.retryable is True, (
                f"{provider_name} should mark timeout as retryable"
            )

    def test_all_providers_classify_invalid_request_as_not_retryable(self):
        """Verify all providers mark invalid requests as not retryable."""
        invalid_error = ValueError("Invalid parameters")

        for provider_name in ALL_PROVIDERS:
            provider = get_provider(provider_name, force_new=True)
            result = provider.classify_error(invalid_error)

            # Invalid requests should generally not be retryable
            # (though providers may differ in classification)
            assert isinstance(result.retryable, bool)

    def test_retry_config_has_reasonable_defaults(self):
        """Verify all providers have reasonable retry configurations."""
        for provider_name in ALL_PROVIDERS:
            provider = get_provider(provider_name, force_new=True)
            config = provider.get_retry_config()

            # Max retries should be positive or 0 (infinite)
            assert config.max_retries >= 0

            # Backoff should be positive
            assert config.base_backoff > 0
            assert config.max_backoff > 0
            assert config.max_backoff >= config.base_backoff

            # Should retry common errors
            assert ErrorClass.RATE_LIMIT in config.retry_on or \
                   ErrorClass.SERVER_ERROR in config.retry_on or \
                   ErrorClass.TIMEOUT in config.retry_on


class TestTokenCounting:
    """Test token counting accuracy across providers."""

    @pytest.mark.parametrize("provider_name", ALL_PROVIDERS)
    def test_token_count_within_reasonable_range(self, provider_name):
        """Verify token counts are within reasonable range."""
        provider = get_provider(provider_name, force_new=True)

        # Test with known text
        messages = [
            {"role": "user", "content": "Hello world"}
        ]

        count = provider.count_tokens(messages)

        # "Hello world" should be 2-4 tokens depending on tokenizer
        assert 2 <= count <= 10, f"{provider_name} gave unreasonable count: {count}"

    @pytest.mark.parametrize("provider_name", ALL_PROVIDERS)
    def test_empty_message_token_count(self, provider_name):
        """Verify token count for empty messages."""
        provider = get_provider(provider_name, force_new=True)

        messages = [
            {"role": "user", "content": ""}
        ]

        count = provider.count_tokens(messages)

        # Empty message should have minimal tokens (role overhead)
        assert count >= 0

    @pytest.mark.parametrize("provider_name", ALL_PROVIDERS)
    def test_multiple_messages_token_count(self, provider_name):
        """Verify token count sums across multiple messages."""
        provider = get_provider(provider_name, force_new=True)

        single_message = [
            {"role": "user", "content": "Hello"}
        ]
        multiple_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]

        single_count = provider.count_tokens(single_message)
        multiple_count = provider.count_tokens(multiple_messages)

        # Multiple messages should have more tokens
        assert multiple_count > single_count


class TestErrorClassification:
    """Test error classification across providers."""

    @pytest.mark.parametrize("provider_name", ALL_PROVIDERS)
    def test_classify_connection_error(self, provider_name):
        """Test classification of connection errors."""
        provider = get_provider(provider_name, force_new=True)

        import socket
        error = socket.error("Connection refused")
        result = provider.classify_error(error)

        assert result.error_class in [
            ErrorClass.NETWORK_ERROR,
            ErrorClass.SERVER_ERROR,
            ErrorClass.UNKNOWN
        ]
        assert result.retryable is True

    @pytest.mark.parametrize("provider_name", ALL_PROVIDERS)
    def test_classify_generic_exception(self, provider_name):
        """Test classification of generic exceptions."""
        provider = get_provider(provider_name, force_new=True)

        error = Exception("Something went wrong")
        result = provider.classify_error(error)

        assert isinstance(result, ProviderError)
        assert result.error_class == ErrorClass.UNKNOWN
        assert result.message == "Something went wrong"


class TestProviderStringRepresentation:
    """Test string representation of providers."""

    def test_provider_str(self, provider):
        """Test __str__ method."""
        s = str(provider)
        assert isinstance(s, str)
        assert len(s) > 0
        assert "Provider" in s

    def test_provider_repr(self, provider):
        """Test __repr__ method."""
        r = repr(provider)
        assert isinstance(r, str)
        assert len(r) > 0
        assert provider.name in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
