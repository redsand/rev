"""OpenAI LLM provider implementation."""

import os
from typing import Any, Callable, Dict, List, Optional

from rev.debug_logger import get_logger
from .base import LLMProvider


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
