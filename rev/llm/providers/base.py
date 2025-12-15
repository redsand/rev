"""Base interface for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional


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

    def __str__(self) -> str:
        """String representation of the provider."""
        return f"{self.__class__.__name__}"

    def __repr__(self) -> str:
        """Detailed string representation of the provider."""
        return f"{self.__class__.__name__}(name='{self.name}')"
