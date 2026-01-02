"""OpenAI LLM provider implementation."""

import os
from typing import Any, Callable, Dict, List, Optional

from rev import config
from rev.debug_logger import get_logger
from .base import LLMProvider, ErrorClass, ProviderError, RetryConfig


class OpenAIProvider(LLMProvider):
    """OpenAI (ChatGPT/GPT-4) LLM provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self.name = "openai"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "") or config.OPENAI_API_KEY
        self._client = None
        self._responses_only_models: set[str] = set()
        self._no_temperature_models: set[str] = set()
        # Allow overriding base URL for OpenAI-compatible local backends (LocalAI/vLLM/LM Studio)
        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip()

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                import openai
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = openai.OpenAI(**client_kwargs)
            except ImportError:
                raise ImportError(
                    "OpenAI package not installed. Install with: pip install openai"
                )
        return self._client

    @staticmethod
    def _is_responses_only_error(error: Exception) -> bool:
        message = str(error).lower()
        return "v1/responses" in message and "chat/completions" in message

    @staticmethod
    def _is_temperature_unsupported_error(error: Exception) -> bool:
        message = str(error).lower()
        if "temperature" not in message:
            return False
        return (
            "unsupported parameter" in message
            or "not supported" in message
            or "unsupported value" in message
        )

    @staticmethod
    def _get_value(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _extract_output_text(self, response: Any) -> str:
        text = self._get_value(response, "output_text", "")
        if text:
            return text

        output = self._get_value(response, "output", [])
        parts: List[str] = []
        if isinstance(output, list):
            for item in output:
                item_type = self._get_value(item, "type", "")
                if item_type == "message":
                    content = self._get_value(item, "content", [])
                    parts.extend(self._extract_content_parts(content))
                elif item_type in ("output_text", "text"):
                    value = self._get_value(item, "text", "") or self._get_value(item, "content", "")
                    if value:
                        parts.append(str(value))
        return "".join(parts)

    def _extract_content_parts(self, content: Any) -> List[str]:
        parts: List[str] = []
        if isinstance(content, str):
            parts.append(content)
            return parts
        if isinstance(content, list):
            for part in content:
                part_type = self._get_value(part, "type", "")
                if part_type in ("output_text", "text"):
                    value = self._get_value(part, "text", "") or self._get_value(part, "content", "")
                    if value:
                        parts.append(str(value))
                elif isinstance(part, str):
                    parts.append(part)
        return parts

    def _extract_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        output = self._get_value(response, "output", [])
        tool_calls: List[Dict[str, Any]] = []
        if not isinstance(output, list):
            return tool_calls

        for item in output:
            item_type = self._get_value(item, "type", "")
            if item_type not in ("tool_call", "function_call"):
                continue
            function = self._get_value(item, "function", {}) or self._get_value(item, "tool", {})
            name = self._get_value(function, "name", "") or self._get_value(item, "name", "")
            arguments = self._get_value(function, "arguments", "") or self._get_value(item, "arguments", "")
            tool_calls.append({
                "function": {
                    "name": name,
                    "arguments": arguments,
                }
            })
        return tool_calls

    @staticmethod
    def _normalize_tools_for_responses(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return tools
        normalized: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if "name" in tool and "type" in tool:
                normalized.append(tool)
                continue
            func = tool.get("function")
            if isinstance(func, dict) and func.get("name"):
                entry = {
                    "type": tool.get("type", "function"),
                    "name": func.get("name"),
                }
                desc = func.get("description")
                params = func.get("parameters")
                if desc is not None:
                    entry["description"] = desc
                if params is not None:
                    entry["parameters"] = params
                normalized.append(entry)
                continue
            normalized.append(tool)
        return normalized

    def _extract_usage(self, response: Any) -> Dict[str, int]:
        usage = self._get_value(response, "usage", {}) or {}
        prompt = self._get_value(usage, "prompt_tokens", None)
        if prompt is None:
            prompt = self._get_value(usage, "input_tokens", 0)
        completion = self._get_value(usage, "completion_tokens", None)
        if completion is None:
            completion = self._get_value(usage, "output_tokens", 0)
        total = self._get_value(usage, "total_tokens", None)
        if total is None:
            total = int(prompt or 0) + int(completion or 0)
        return {
            "prompt": int(prompt or 0),
            "completion": int(completion or 0),
            "total": int(total or 0),
        }

    def _chat_with_responses(
        self,
        client: Any,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model_name: str,
        supports_tools: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not hasattr(client, "responses"):
            raise RuntimeError("OpenAI client does not support responses API; upgrade the openai package.")

        request_params: Dict[str, Any] = {
            "model": model_name,
            "input": messages,
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", str(config.OPENAI_TEMPERATURE))),
        }
        if model_name in self._no_temperature_models:
            request_params.pop("temperature", None)

        if tools:
            request_params["tools"] = self._normalize_tools_for_responses(tools)
            request_params["tool_choice"] = "auto"

        if "response_format" in kwargs and kwargs["response_format"] is not None:
            request_params["response_format"] = kwargs["response_format"]

        try:
            response = client.responses.create(**request_params)
        except Exception as e:
            if self._is_temperature_unsupported_error(e) and "temperature" in request_params:
                self._no_temperature_models.add(model_name)
                request_params.pop("temperature", None)
                response = client.responses.create(**request_params)
            else:
                raise

        content = self._extract_output_text(response)
        result_message = {
            "role": "assistant",
            "content": content or "",
        }
        tool_calls = self._extract_tool_calls(response)
        if tool_calls:
            result_message["tool_calls"] = tool_calls

        return {
            "message": result_message,
            "done": True,
            "usage": self._extract_usage(response),
        }

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
        model_name = model or os.getenv("OPENAI_MODEL", "gpt-5.2-mini")
        if model_name in self._responses_only_models:
            try:
                result = self._chat_with_responses(client, messages, tools, model_name, supports_tools, **kwargs)
                debug_logger.log_llm_response(model_name, result, cached=False)
                return result
            except Exception as e:
                debug_logger.log("llm", "OPENAI_RESPONSES_ERROR", {"error": str(e)}, "ERROR")
                return {"error": f"OpenAI API error: {e}"}

        # Build request parameters
        request_params = {
            "model": model_name,
            "messages": messages,
            # Respect runtime setting; fallback to env if provided, else config default
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", str(getattr(config, "OPENAI_TEMPERATURE", 1.0)))),
        }
        if model_name in self._no_temperature_models:
            request_params.pop("temperature", None)

        # Optional: thinking mode for OpenAI-compatible backends (e.g., DeepSeek).
        # Passed through as-is; auto-detection is handled at a higher level.
        if "thinking" in kwargs and kwargs["thinking"] is not None:
            request_params["thinking"] = kwargs["thinking"]

        # Add tools if provided and supported
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "required"  # BEST PRACTICE: Force tool use when provided
            # Enable Structured Outputs for guaranteed schema compliance
            # This ensures the model's tool calls exactly match the JSON schema
            if supports_tools:
                request_params["parallel_tool_calls"] = True  # Allow multiple tool calls in one response

        if "response_format" in kwargs and kwargs["response_format"] is not None:
            request_params["response_format"] = kwargs["response_format"]

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
            if self._is_responses_only_error(e):
                self._responses_only_models.add(model_name)
                try:
                    result = self._chat_with_responses(client, messages, tools, model_name, supports_tools, **kwargs)
                    debug_logger.log_llm_response(model_name, result, cached=False)
                    return result
                except Exception as inner:
                    debug_logger.log("llm", "OPENAI_RESPONSES_ERROR", {"error": str(inner)}, "ERROR")
                    return {"error": f"OpenAI API error: {inner}"}
            if self._is_temperature_unsupported_error(e):
                self._no_temperature_models.add(model_name)
                request_params.pop("temperature", None)
                try:
                    response = client.chat.completions.create(**request_params)
                    message_content = response.choices[0].message

                    result_message = {
                        "role": "assistant",
                        "content": message_content.content or "",
                    }
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
                except Exception as inner:
                    debug_logger.log("llm", "OPENAI_ERROR", {"error": str(inner)}, "ERROR")
                    return {"error": f"OpenAI API error: {inner}"}
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

        model_name = model or os.getenv("OPENAI_MODEL", "gpt-5.2-mini")
        if model_name in self._responses_only_models:
            try:
                result = self._chat_with_responses(client, messages, tools, model_name, supports_tools, **kwargs)
                if on_chunk and result.get("message", {}).get("content"):
                    on_chunk(result["message"]["content"])
                debug_logger.log_llm_response(model_name, result, cached=False)
                return result
            except Exception as e:
                debug_logger.log("llm", "OPENAI_RESPONSES_ERROR", {"error": str(e)}, "ERROR")
                return {"error": f"OpenAI streaming error: {e}"}

        request_params = {
            "model": model_name,
            "messages": messages,
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", str(getattr(config, "OPENAI_TEMPERATURE", 1.0)))),
            "stream": True,
        }
        if model_name in self._no_temperature_models:
            request_params.pop("temperature", None)

        if "thinking" in kwargs and kwargs["thinking"] is not None:
            request_params["thinking"] = kwargs["thinking"]

        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "required"  # Force tool use when tools provided
            if supports_tools:
                request_params["parallel_tool_calls"] = True

        if "response_format" in kwargs and kwargs["response_format"] is not None:
            request_params["response_format"] = kwargs["response_format"]

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

                # Handle tool calls - CRITICAL FIX: Properly merge streaming deltas
                # OpenAI streams tool calls incrementally, we need to merge them by index
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        # Get the index of this tool call
                        tc_index = tc_delta.index if hasattr(tc_delta, "index") else len(accumulated_tool_calls)

                        # Ensure we have enough slots
                        while len(accumulated_tool_calls) <= tc_index:
                            accumulated_tool_calls.append({
                                "id": "",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                }
                            })

                        # Merge the delta into the accumulated tool call
                        if hasattr(tc_delta, "id") and tc_delta.id:
                            accumulated_tool_calls[tc_index]["id"] = tc_delta.id

                        if hasattr(tc_delta, "function"):
                            if hasattr(tc_delta.function, "name") and tc_delta.function.name:
                                accumulated_tool_calls[tc_index]["function"]["name"] = tc_delta.function.name
                            if hasattr(tc_delta.function, "arguments") and tc_delta.function.arguments:
                                # Append arguments incrementally (they stream character by character)
                                accumulated_tool_calls[tc_index]["function"]["arguments"] += tc_delta.function.arguments

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
            if self._is_responses_only_error(e):
                self._responses_only_models.add(model_name)
                try:
                    result = self._chat_with_responses(client, messages, tools, model_name, supports_tools, **kwargs)
                    if on_chunk and result.get("message", {}).get("content"):
                        on_chunk(result["message"]["content"])
                    debug_logger.log_llm_response(model_name, result, cached=False)
                    return result
                except Exception as inner:
                    debug_logger.log("llm", "OPENAI_RESPONSES_ERROR", {"error": str(inner)}, "ERROR")
                    return {"error": f"OpenAI streaming error: {inner}"}
            if self._is_temperature_unsupported_error(e):
                self._no_temperature_models.add(model_name)
                request_params.pop("temperature", None)
                try:
                    stream = client.chat.completions.create(**request_params)
                    accumulated_content = ""
                    accumulated_tool_calls = []
                    usage_info = {"prompt": 0, "completion": 0, "total": 0}

                    for chunk in stream:
                        if check_interrupt and check_interrupt():
                            if on_chunk:
                                on_chunk("\n[Cancelled]")
                            raise KeyboardInterrupt("Execution interrupted")

                        if check_user_messages:
                            check_user_messages()

                        delta = chunk.choices[0].delta if chunk.choices else None
                        if not delta:
                            continue

                        if hasattr(delta, "content") and delta.content:
                            accumulated_content += delta.content
                            if on_chunk:
                                on_chunk(delta.content)

                        if hasattr(delta, "tool_calls") and delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                tc_index = tc_delta.index if hasattr(tc_delta, "index") else len(accumulated_tool_calls)

                                while len(accumulated_tool_calls) <= tc_index:
                                    accumulated_tool_calls.append({
                                        "id": "",
                                        "function": {
                                            "name": "",
                                            "arguments": "",
                                        }
                                    })

                                if hasattr(tc_delta, "id") and tc_delta.id:
                                    accumulated_tool_calls[tc_index]["id"] = tc_delta.id

                                if hasattr(tc_delta, "function"):
                                    if hasattr(tc_delta.function, "name") and tc_delta.function.name:
                                        accumulated_tool_calls[tc_index]["function"]["name"] = tc_delta.function.name
                                    if hasattr(tc_delta.function, "arguments") and tc_delta.function.arguments:
                                        accumulated_tool_calls[tc_index]["function"]["arguments"] += tc_delta.function.arguments

                    final_message = {
                        "role": "assistant",
                        "content": accumulated_content,
                    }

                    if accumulated_tool_calls:
                        final_message["tool_calls"] = accumulated_tool_calls

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
                except Exception as inner:
                    debug_logger.log("llm", "OPENAI_STREAM_ERROR", {"error": str(inner)}, "ERROR")
                    return {"error": f"OpenAI streaming error: {inner}"}
            debug_logger.log("llm", "OPENAI_STREAM_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"OpenAI streaming error: {e}"}

    def supports_tool_calling(self, model: str) -> bool:
        """Check if model supports tool calling."""
        # OpenAI tool-capable families: GPT-x, O-family (o1/o3/o4), and 5.x mini/preview
        model_lower = model.lower()
        prefixes = ("gpt-", "o1", "o3", "o4", "o-", "gpt-5", "gpt5")
        return model_lower.startswith(prefixes)

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
            def is_chat_model(model_id: str) -> bool:
                mid = model_id.lower()
                return (
                    mid.startswith("gpt-")
                    or mid.startswith("o1")
                    or mid.startswith("o3")
                    or mid.startswith("o4")
                    or mid.startswith("o-preview")
                )

            chat_models = [m.id for m in models.data if is_chat_model(m.id)]
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
