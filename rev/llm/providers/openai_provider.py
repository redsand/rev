"""OpenAI LLM provider implementation."""

import os
from typing import Any, Callable, Dict, List, Optional

from rev.debug_logger import get_logger
from .base import LLMProvider, ErrorClass, ProviderError, RetryConfig


class OpenAIProvider(LLMProvider):
    """OpenAI (ChatGPT/GPT-4) LLM provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self.name = "openai"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "OpenAI package not installed. Install with: pip install openai"
                )
        return self._client

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request to OpenAI."""
        client = self._get_client()
        debug_logger = get_logger()

        # Default to GPT-4
        model_name = model or os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")

        # Build request parameters
        request_params = {
            "model": model_name,
            "messages": messages,
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
        }

        # Optional: thinking mode for OpenAI-compatible backends (e.g., DeepSeek).
        # Passed through as-is; auto-detection is handled at a higher level.
        if "thinking" in kwargs and kwargs["thinking"] is not None:
            request_params["thinking"] = kwargs["thinking"]

        # Add tools if provided and supported
        if tools and supports_tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        # Log request
        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            response = client.chat.completions.create(**request_params)

            # Convert OpenAI response to our standard format
            message_content = response.choices[0].message

            result_message = {
                "role": "assistant",
                "content": message_content.content or "",
            }

            # Add tool calls if present
            if hasattr(message_content, "tool_calls") and message_content.tool_calls:
                result_message["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in message_content.tool_calls
                ]

            result = {
                "message": result_message,
                "done": True,
                "usage": {
                    "prompt": response.usage.prompt_tokens if response.usage else 0,
                    "completion": response.usage.completion_tokens if response.usage else 0,
                    "total": response.usage.total_tokens if response.usage else 0,
                }
            }

            debug_logger.log_llm_response(model_name, result, cached=False)
            return result

        except Exception as e:
            debug_logger.log("llm", "OPENAI_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"OpenAI API error: {e}"}

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
        """Stream chat responses from OpenAI."""
        client = self._get_client()
        debug_logger = get_logger()

        model_name = model or os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")

        request_params = {
            "model": model_name,
            "messages": messages,
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
            "stream": True,
        }

        if "thinking" in kwargs and kwargs["thinking"] is not None:
            request_params["thinking"] = kwargs["thinking"]

        if tools and supports_tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            stream = client.chat.completions.create(**request_params)

            accumulated_content = ""
            accumulated_tool_calls = []
            usage_info = {"prompt": 0, "completion": 0, "total": 0}

            for chunk in stream:
                # Check for interrupts
                if check_interrupt and check_interrupt():
                    if on_chunk:
                        on_chunk("\n[Cancelled]")
                    raise KeyboardInterrupt("Execution interrupted")

                if check_user_messages:
                    check_user_messages()

                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                # Handle content
                if hasattr(delta, "content") and delta.content:
                    accumulated_content += delta.content
                    if on_chunk:
                        on_chunk(delta.content)

                # Handle tool calls
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc in delta.tool_calls:
                        accumulated_tool_calls.append({
                            "function": {
                                "name": tc.function.name if hasattr(tc.function, "name") else "",
                                "arguments": tc.function.arguments if hasattr(tc.function, "arguments") else "",
                            }
                        })

            # Build final result
            final_message = {
                "role": "assistant",
                "content": accumulated_content,
            }

            if accumulated_tool_calls:
                final_message["tool_calls"] = accumulated_tool_calls

            # Estimate tokens (OpenAI streaming doesn't include usage)
            usage_info["completion"] = len(accumulated_content) // 3
            usage_info["prompt"] = sum(len(str(m.get("content", ""))) for m in messages) // 3
            usage_info["total"] = usage_info["prompt"] + usage_info["completion"]

            result = {
                "message": final_message,
                "done": True,
                "usage": usage_info,
            }

            debug_logger.log_llm_response(model_name, result, cached=False)
            return result

        except KeyboardInterrupt:
            raise
        except Exception as e:
            debug_logger.log("llm", "OPENAI_STREAM_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"OpenAI streaming error: {e}"}

    def supports_tool_calling(self, model: str) -> bool:
        """Check if model supports tool calling."""
        # Most GPT-4 and GPT-3.5-turbo models support tool calling
        tool_capable_models = ["gpt-4", "gpt-3.5-turbo"]
        return any(model.startswith(prefix) for prefix in tool_capable_models)

    def validate_config(self) -> bool:
        """Validate OpenAI configuration."""
        if not self.api_key:
            return False

        try:
            client = self._get_client()
            # Try a simple list models call to verify credentials
            client.models.list()
            return True
        except Exception:
            return False

    def get_model_list(self) -> List[str]:
        """Get list of available OpenAI models."""
        try:
            client = self._get_client()
            models = client.models.list()
            # Filter for chat models
            chat_models = [
                m.id for m in models.data
                if "gpt" in m.id.lower()
            ]
            return sorted(chat_models)
        except Exception:
            return []

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens for messages using character-based estimation.

        For accurate token counting, use tiktoken library.
        This is a fallback estimation: ~4 characters per token.
        """
        total_chars = 0
        for message in messages:
            # Count content
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Handle structured content
                for item in content:
                    if isinstance(item, dict):
                        total_chars += len(str(item))
                    else:
                        total_chars += len(str(item))

            # Count role overhead (~4 tokens per message)
            total_chars += 16

            # Count tool calls if present
            if "tool_calls" in message:
                total_chars += len(str(message["tool_calls"]))

        # Estimate: 1 token ≈ 4 characters
        return max(1, total_chars // 4)

    def classify_error(self, error: Exception) -> ProviderError:
        """Classify an error into standard ErrorClass."""
        error_str = str(error).lower()
        error_type = type(error).__name__

        # Check for timeout errors
        if "timeout" in error_str or "timed out" in error_str:
            return ProviderError(
                error_class=ErrorClass.TIMEOUT,
                message=str(error),
                retryable=True,
                original_error=error
            )

        # Check for connection/network errors
        if any(keyword in error_str for keyword in ["connection", "network", "unreachable", "refused"]):
            return ProviderError(
                error_class=ErrorClass.NETWORK_ERROR,
                message=str(error),
                retryable=True,
                original_error=error
            )

        # Check for rate limit errors
        if "rate" in error_str and "limit" in error_str or "429" in error_str or "too many requests" in error_str:
            # Try to extract retry-after
            retry_after = None
            if "retry after" in error_str:
                try:
                    import re
                    match = re.search(r"retry after (\d+)", error_str)
                    if match:
                        retry_after = float(match.group(1))
                except:
                    pass

            return ProviderError(
                error_class=ErrorClass.RATE_LIMIT,
                message=str(error),
                retryable=True,
                retry_after=retry_after,
                original_error=error
            )

        # Check for authentication errors
        if any(keyword in error_str for keyword in ["auth", "unauthorized", "401", "api key", "invalid_api_key"]):
            return ProviderError(
                error_class=ErrorClass.AUTH_ERROR,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for model not found errors
        if "404" in error_str or "model not found" in error_str or "does not exist" in error_str:
            return ProviderError(
                error_class=ErrorClass.MODEL_NOT_FOUND,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for invalid request errors
        if "400" in error_str or "invalid" in error_str or "bad request" in error_str:
            return ProviderError(
                error_class=ErrorClass.INVALID_REQUEST,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for context length errors
        if "context" in error_str and ("length" in error_str or "too long" in error_str or "maximum" in error_str):
            return ProviderError(
                error_class=ErrorClass.CONTEXT_LENGTH_EXCEEDED,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for server errors (5xx)
        if any(keyword in error_str for keyword in ["500", "502", "503", "504", "server error", "internal server"]):
            return ProviderError(
                error_class=ErrorClass.SERVER_ERROR,
                message=str(error),
                retryable=True,
                original_error=error
            )

        # Default: unknown error
        return ProviderError(
            error_class=ErrorClass.UNKNOWN,
            message=str(error),
            retryable=False,
            original_error=error
        )

    def get_retry_config(self) -> RetryConfig:
        """Get retry configuration for OpenAI."""
        return RetryConfig(
            max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
            base_backoff=float(os.getenv("OPENAI_BASE_BACKOFF", "1.0")),
            max_backoff=float(os.getenv("OPENAI_MAX_BACKOFF", "60.0")),
            exponential=True,
            retry_on=[
                ErrorClass.RATE_LIMIT,
                ErrorClass.TIMEOUT,
                ErrorClass.SERVER_ERROR,
                ErrorClass.NETWORK_ERROR,
            ]
        )
