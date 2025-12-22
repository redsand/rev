"""Base interface for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ErrorClass(Enum):
    """Standardized error categories across all providers."""
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"
    AUTH_ERROR = "auth_error"
    MODEL_NOT_FOUND = "model_not_found"
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class ProviderError:
    """Standardized error representation."""
    error_class: ErrorClass
    message: str
    retryable: bool
    retry_after: Optional[float] = None  # Seconds to wait before retry
    original_error: Optional[Exception] = None


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int
    base_backoff: float  # seconds
    max_backoff: float  # seconds
    exponential: bool = True
    retry_on: List[ErrorClass] = field(default_factory=lambda: [
        ErrorClass.RATE_LIMIT,
        ErrorClass.TIMEOUT,
        ErrorClass.SERVER_ERROR,
        ErrorClass.NETWORK_ERROR,
    ])


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM providers must implement this interface to ensure
    consistent behavior across different backends (Ollama, OpenAI,
    Anthropic, Google, etc.).
    """

    def __init__(self):
        """Initialize the provider."""
        self.name = "base"

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Make a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            tools: Optional list of tool definitions in OpenAI format
            model: Model name to use (provider-specific)
            supports_tools: Whether the model supports tool calling
            **kwargs: Additional provider-specific parameters

        Returns:
            Dict with 'message' and optional 'usage' keys

        Raises:
            Exception: If the request fails
        """
        pass

    @abstractmethod
    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        on_chunk: Optional[Callable[[str], None]] = None,
        check_interrupt: Optional[Callable[[], bool]] = None,
        check_user_messages: Optional[Callable[[], bool]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make a streaming chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            tools: Optional list of tool definitions in OpenAI format
            model: Model name to use (provider-specific)
            supports_tools: Whether the model supports tool calling
            on_chunk: Optional callback for streaming chunks
            check_interrupt: Optional callback to check for interrupts
            check_user_messages: Optional callback to check for user messages
            **kwargs: Additional provider-specific parameters

        Returns:
            Dict with 'message' and optional 'usage' keys

        Raises:
            Exception: If the request fails
        """
        pass

    @abstractmethod
    def supports_tool_calling(self, model: str) -> bool:
        """Check if the given model supports tool calling.

        Args:
            model: Model name to check

        Returns:
            True if the model supports tool calling, False otherwise
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate that the provider is configured correctly.

        Returns:
            True if configuration is valid, False otherwise
        """
        pass

    @abstractmethod
    def get_model_list(self) -> List[str]:
        """Get list of available models for this provider.

        Returns:
            List of model names
        """
        pass

    @abstractmethod
    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens for the given messages.

        Args:
            messages: List of message dicts

        Returns:
            Estimated token count
        """
        pass

    @abstractmethod
    def classify_error(self, error: Exception) -> ProviderError:
        """Classify an error into a standard ErrorClass.

        Args:
            error: The exception that occurred

        Returns:
            ProviderError with classified error information
        """
        pass

    @abstractmethod
    def get_retry_config(self) -> RetryConfig:
        """Get retry configuration for this provider.

        Returns:
            RetryConfig with provider-specific retry settings
        """
        pass

    def __str__(self) -> str:
        """String representation of the provider."""
        return f"{self.__class__.__name__}"

    def __repr__(self) -> str:
        """Detailed string representation of the provider."""
        return f"{self.__class__.__name__}(name='{self.name}')"
