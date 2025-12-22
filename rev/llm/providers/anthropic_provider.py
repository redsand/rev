"""Anthropic LLM provider implementation."""

import os
from typing import Any, Callable, Dict, List, Optional

from rev.debug_logger import get_logger
from .base import LLMProvider, ErrorClass, ProviderError, RetryConfig


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) LLM provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self.name = "anthropic"
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "Anthropic package not installed. Install with: pip install anthropic"
                )
        return self._client

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic format.

        Returns:
            Tuple of (system_message, converted_messages)
        """
        system_message = ""
        converted = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # Anthropic uses separate system parameter
                system_message += content + "\n"
            elif role == "assistant":
                # Convert tool calls if present
                if "tool_calls" in msg:
                    # Anthropic format for tool use
                    tool_uses = []
                    for tc in msg.get("tool_calls", []):
                        func = tc.get("function", {})
                        tool_uses.append({
                            "type": "tool_use",
                            "name": func.get("name", ""),
                            "input": func.get("arguments", ""),
                        })
                    converted.append({
                        "role": "assistant",
                        "content": tool_uses,
                    })
                else:
                    converted.append({
                        "role": "assistant",
                        "content": content,
                    })
            elif role == "user":
                converted.append({
                    "role": "user",
                    "content": content,
                })
            elif role == "tool":
                # Convert tool result
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }]
                })

        return system_message.strip(), converted

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tool definitions to Anthropic format."""
        if not tools:
            return []

        converted = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                converted.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })

        return converted

    def _convert_response(self, response: Any) -> Dict[str, Any]:
        """Convert Anthropic response to our standard format."""
        content = ""
        tool_calls = []

        # Extract content and tool uses from response
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append({
                    "function": {
                        "name": block.name,
                        "arguments": str(block.input),
                    }
                })

        result_message = {
            "role": "assistant",
            "content": content,
        }

        if tool_calls:
            result_message["tool_calls"] = tool_calls

        return {
            "message": result_message,
            "done": True,
            "usage": {
                "prompt": response.usage.input_tokens if hasattr(response, "usage") else 0,
                "completion": response.usage.output_tokens if hasattr(response, "usage") else 0,
                "total": (
                    response.usage.input_tokens + response.usage.output_tokens
                    if hasattr(response, "usage") else 0
                ),
            }
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request to Anthropic."""
        client = self._get_client()
        debug_logger = get_logger()

        # Default to Claude 3.5 Sonnet
        model_name = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        # Convert messages to Anthropic format
        system_message, converted_messages = self._convert_messages(messages)

        # Build request parameters
        request_params = {
            "model": model_name,
            "messages": converted_messages,
            "max_tokens": int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192")),
            "temperature": float(os.getenv("ANTHROPIC_TEMPERATURE", "0.1")),
        }

        if system_message:
            request_params["system"] = system_message

        # Add tools if provided and supported
        if tools and supports_tools:
            anthropic_tools = self._convert_tools(tools)
            if anthropic_tools:
                request_params["tools"] = anthropic_tools

        # Log request
        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            response = client.messages.create(**request_params)
            result = self._convert_response(response)

            debug_logger.log_llm_response(model_name, result, cached=False)
            return result

        except Exception as e:
            debug_logger.log("llm", "ANTHROPIC_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"Anthropic API error: {e}"}

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
        """Stream chat responses from Anthropic."""
        client = self._get_client()
        debug_logger = get_logger()

        model_name = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        system_message, converted_messages = self._convert_messages(messages)

        request_params = {
            "model": model_name,
            "messages": converted_messages,
            "max_tokens": int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192")),
            "temperature": float(os.getenv("ANTHROPIC_TEMPERATURE", "0.1")),
        }

        if system_message:
            request_params["system"] = system_message

        if tools and supports_tools:
            anthropic_tools = self._convert_tools(tools)
            if anthropic_tools:
                request_params["tools"] = anthropic_tools

        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            accumulated_content = ""
            accumulated_tool_calls = []
            usage_info = {"prompt": 0, "completion": 0, "total": 0}

            with client.messages.stream(**request_params) as stream:
                for text in stream.text_stream:
                    # Check for interrupts
                    if check_interrupt and check_interrupt():
                        if on_chunk:
                            on_chunk("\n[Cancelled]")
                        raise KeyboardInterrupt("Execution interrupted")

                    if check_user_messages:
                        check_user_messages()

                    accumulated_content += text
                    if on_chunk:
                        on_chunk(text)

                # Get the final message which includes tool uses
                final_message_obj = stream.get_final_message()

                # Extract tool uses
                for block in final_message_obj.content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        accumulated_tool_calls.append({
                            "function": {
                                "name": block.name,
                                "arguments": str(block.input),
                            }
                        })

                # Get usage info
                if hasattr(final_message_obj, "usage"):
                    usage_info["prompt"] = final_message_obj.usage.input_tokens
                    usage_info["completion"] = final_message_obj.usage.output_tokens
                    usage_info["total"] = usage_info["prompt"] + usage_info["completion"]

            # Build final result
            final_message = {
                "role": "assistant",
                "content": accumulated_content,
            }

            if accumulated_tool_calls:
                final_message["tool_calls"] = accumulated_tool_calls

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
            debug_logger.log("llm", "ANTHROPIC_STREAM_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"Anthropic streaming error: {e}"}

    def supports_tool_calling(self, model: str) -> bool:
        """Check if model supports tool calling."""
        # Claude 3+ models support tool calling
        tool_capable_prefixes = ["claude-3", "claude-3.5"]
        return any(model.startswith(prefix) for prefix in tool_capable_prefixes)

    def validate_config(self) -> bool:
        """Validate Anthropic configuration."""
        if not self.api_key:
            return False

        try:
            client = self._get_client()
            # Try a simple messages call to verify credentials
            client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return True
        except Exception:
            return False

    def get_model_list(self) -> List[str]:
        """Get list of available Anthropic models."""
        # Anthropic doesn't have a models list endpoint, return known models
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens for messages using character-based estimation.

        Anthropic's actual token counting would require their tokenizer.
        This is a fallback estimation: ~4 characters per token.
        """
        total_chars = 0
        for message in messages:
            # Count content
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Handle structured content (Anthropic uses lists for complex content)
                for item in content:
                    if isinstance(item, dict):
                        # Could be text block, tool use, or tool result
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

        # Check for rate limit errors (Anthropic uses 429)
        if "rate" in error_str and "limit" in error_str or "429" in error_str or "too many requests" in error_str:
            # Try to extract retry-after from Anthropic response
            retry_after = None
            if "retry" in error_str:
                try:
                    import re
                    # Anthropic returns retry-after in seconds
                    match = re.search(r"retry[_-]?after[:\s]+(\d+)", error_str)
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
        if any(keyword in error_str for keyword in ["auth", "unauthorized", "401", "api key", "invalid_api_key", "authentication_error"]):
            return ProviderError(
                error_class=ErrorClass.AUTH_ERROR,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for model not found errors
        if "404" in error_str or "model not found" in error_str or "does not exist" in error_str or "not_found_error" in error_str:
            return ProviderError(
                error_class=ErrorClass.MODEL_NOT_FOUND,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for invalid request errors
        if "400" in error_str or "invalid" in error_str or "bad request" in error_str or "invalid_request_error" in error_str:
            return ProviderError(
                error_class=ErrorClass.INVALID_REQUEST,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for context length errors (Anthropic has max_tokens limits)
        if any(keyword in error_str for keyword in [
            "context", "too long", "maximum", "max_tokens", "token limit", "prompt is too long"
        ]):
            return ProviderError(
                error_class=ErrorClass.CONTEXT_LENGTH_EXCEEDED,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for server errors (5xx)
        if any(keyword in error_str for keyword in ["500", "502", "503", "504", "server error", "internal server", "overloaded_error"]):
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
        """Get retry configuration for Anthropic."""
        return RetryConfig(
            max_retries=int(os.getenv("ANTHROPIC_MAX_RETRIES", "3")),
            base_backoff=float(os.getenv("ANTHROPIC_BASE_BACKOFF", "1.0")),
            max_backoff=float(os.getenv("ANTHROPIC_MAX_BACKOFF", "60.0")),
            exponential=True,
            retry_on=[
                ErrorClass.RATE_LIMIT,
                ErrorClass.TIMEOUT,
                ErrorClass.SERVER_ERROR,
                ErrorClass.NETWORK_ERROR,
            ]
        )
