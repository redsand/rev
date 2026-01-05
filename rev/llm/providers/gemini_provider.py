"""Google Gemini LLM provider implementation."""

import os
import json
from typing import Any, Callable, Dict, List, Optional

from rev import config
from rev.debug_logger import get_logger
from .base import LLMProvider, ErrorClass, ProviderError, RetryConfig


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: Optional[str] = None, silent: bool = False):
        super().__init__()
        self.name = "gemini"
        self.silent = silent  # Suppress debug prints when True
        # Check: 1) passed parameter, 2) environment variable, 3) config module
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "") or config.GEMINI_API_KEY

        # Debug logging to help verify API key loading
        logger = get_logger()
        if self.api_key:
            # Show only first 10 characters for security
            masked_key = f"{self.api_key[:10]}...{self.api_key[-4:]}" if len(self.api_key) > 14 else "***"
            key_source = "parameter" if api_key else ("env" if os.getenv("GEMINI_API_KEY") else "config")
            logger.log("llm", "GEMINI_API_KEY_LOADED", {
                "source": key_source,
                "key_preview": masked_key,
                "key_length": len(self.api_key)
            }, "DEBUG")
            if not silent:
                print(f"🔑 Gemini API key loaded from {key_source}: {masked_key} (length: {len(self.api_key)})")
        else:
            logger.log("llm", "GEMINI_API_KEY_MISSING", {}, "ERROR")
            if not silent:
                print("  WARNING: No Gemini API key found!")
                print("   Set GEMINI_API_KEY environment variable or use 'rev save-api-key gemini YOUR_KEY'")

        self._genai = None
        self._client = None

    def _get_client(self):
        """Lazy initialization of Gemini client."""
        if self._genai is None:
            try:
                import google.generativeai as genai
                self._genai = genai

                # Debug: verify API key before configuring
                logger = get_logger()
                if self.api_key:
                    masked_key = f"{self.api_key[:10]}...{self.api_key[-4:]}" if len(self.api_key) > 14 else "***"
                    logger.log("llm", "GEMINI_CONFIGURE", {
                        "key_preview": masked_key,
                        "key_length": len(self.api_key)
                    }, "DEBUG")
                    if not self.silent:
                        print(f"🔧 Configuring Gemini with API key: {masked_key} (length: {len(self.api_key)})")
                else:
                    logger.log("llm", "GEMINI_CONFIGURE_NO_KEY", {}, "ERROR")
                    if not self.silent:
                        print("❌ ERROR: Attempting to configure Gemini with empty API key!")

                genai.configure(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "Google GenerativeAI package not installed. Install with: pip install google-generativeai"
                )
        return self._genai

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to Gemini format.

        Returns:
            Tuple of (system_instruction, converted_messages)
        """
        system_instruction = ""
        converted = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # Gemini uses system_instruction parameter
                system_instruction += content + "\n"
            elif role == "assistant":
                parts = []
                if content:
                    parts.append({"text": content})
                
                # IMPORTANT: Include tool calls in history so Gemini can match responses
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        args_raw = func.get("arguments", "{}")
                        try:
                            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                        except Exception:
                            args = {}
                            
                        parts.append({
                            "function_call": {
                                "name": func.get("name", ""),
                                "args": args,
                            }
                        })
                
                if parts:
                    converted.append({
                        "role": "model",
                        "parts": parts,
                    })
            elif role == "user":
                converted.append({
                    "role": "user",
                    "parts": [{"text": content}],
                })
            elif role == "tool":
                # Gemini tool results: use 'user' role for function_response parts
                try:
                    # Gemini expects an object for the response body
                    resp_obj = json.loads(content) if isinstance(content, str) else content
                    if not isinstance(resp_obj, dict):
                        resp_obj = {"result": content}
                except Exception:
                    resp_obj = {"result": content}

                converted.append({
                    "role": "user",
                    "parts": [{
                        "function_response": {
                            "name": msg.get("name", ""),
                            "response": resp_obj,
                        }
                    }],
                })

        return system_instruction.strip(), converted

    def _sanitize_schema(self, schema: Dict[str, Any], is_property_value: bool = False) -> Dict[str, Any]:
        """Recursively remove/clean keywords Gemini rejects (default/oneOf/etc) and invalid required entries.

        Args:
            schema: Schema dict to sanitize
            is_property_value: True if this schema is a value inside a "properties" dict
        """
        if not isinstance(schema, dict):
            return schema

        result = {}
        # Get properties at THIS level for validating required fields
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}

        for key, value in schema.items():
            # Handle "properties" dict - recursively sanitize each property's schema
            # Mark nested schemas as property values so we preserve their structure
            if key == "properties":
                if isinstance(value, dict):
                    result[key] = {
                        prop_name: self._sanitize_schema(prop_value, is_property_value=True) if isinstance(prop_value, dict) else prop_value
                        for prop_name, prop_value in value.items()
                        # Preserve ALL property names, including "default", "add", etc.
                    }
                else:
                    result[key] = value
                continue

            # Improve oneOf/anyOf/allOf handling: use the first valid option instead of stripping
            if key in {"oneOf", "anyOf", "allOf"}:
                if isinstance(value, list) and value:
                    # Sanitize the first sub-schema
                    first_schema = self._sanitize_schema(value[0], is_property_value=is_property_value)
                    if isinstance(first_schema, dict):
                        # Merge properties from the first schema into our result
                        for sub_key, sub_val in first_schema.items():
                            if sub_key not in result:
                                result[sub_key] = sub_val
                continue

            # Remove "default" keyword ONLY when it's used as a schema attribute (default value)
            # Keep "default" when it's a property name inside "properties" dict
            if key == "default":
                # Skip default values (schema keyword), but this was already handled if inside properties
                continue

            if key == "required":
                # Only validate required fields against properties at THIS level
                if not isinstance(value, list):
                    continue

                # Only include required fields that actually exist in properties
                filtered = [item for item in value if isinstance(item, str) and item in properties]
                if filtered:
                    result[key] = filtered
                continue

            # Recursively sanitize nested dicts
            if isinstance(value, dict):
                result[key] = self._sanitize_schema(value, is_property_value=False)
            elif isinstance(value, list):
                result[key] = [
                    self._sanitize_schema(item, is_property_value=False) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result

    def _get_safety_settings(self):
        """Get safety settings that minimize blocking for code generation."""
        import google.generativeai as genai
        return {
            genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
            genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
            genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
            genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
        }

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tool definitions to Gemini format.

        Gemini expects all function declarations in a single tools object:
        [{"function_declarations": [func1, func2, ...]}]
        """
        if not tools:
            return []

        function_declarations = []

        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})

                # Remove unsupported keywords and invalid required entries
                parameters = self._sanitize_schema(func.get("parameters", {}))

                function_declarations.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": parameters,
                })

        # Return all function declarations in a single tools object
        if function_declarations:
            return [{"function_declarations": function_declarations}]
        return []

    def _convert_response(self, response: Any, usage_metadata: Optional[Any] = None) -> Dict[str, Any]:
        """Convert Gemini response to our standard format."""
        content = ""
        tool_calls = []

        # ALWAYS check parts first for function calls
        # response.text might exist but be empty when there are function calls
        if hasattr(response, "parts"):
            for part in response.parts:
                if hasattr(part, "function_call") and part.function_call and getattr(part.function_call, "name", None):
                    # Handle function call
                    fc = part.function_call
                    tool_calls.append({
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args or {})),
                        }
                    })
                else:
                    text = getattr(part, "text", None)
                    if text:
                        content += text
        elif hasattr(response, "text") and response.text:
            content = response.text

        return {
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            },
            "usage": {
                "prompt": getattr(usage_metadata, "prompt_token_count", 0) if usage_metadata else 0,
                "completion": getattr(usage_metadata, "candidates_token_count", 0) if usage_metadata else 0,
                "total": getattr(usage_metadata, "total_token_count", 0) if usage_metadata else 0,
            }
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        tool_choice: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request to Gemini."""
        genai = self._get_client()
        debug_logger = get_logger()

        model_name = model or os.getenv("GEMINI_MODEL", config.GEMINI_MODEL)

        system_instruction, converted_messages = self._convert_messages(messages)

        generation_config = {
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", str(config.GEMINI_TEMPERATURE))),
            "top_p": float(os.getenv("GEMINI_TOP_P", "0.9")),
            "top_k": int(os.getenv("GEMINI_TOP_K", "40")),
            "max_output_tokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
        }

        # Configure tool calling behavior for non-streaming
        tool_config = None
        # Respect tool_choice: "none" means no tools, "required" means any tool, function name means that tool
        effective_tools = tools if tool_choice != "none" else None
        
        if effective_tools:
            mode = "ANY" if tool_choice == "required" or tool_choice == "any" else "AUTO"
            tool_config = {
                "function_calling_config": {
                    "mode": mode
                }
            }
            if tool_choice and tool_choice not in ("auto", "none", "required", "any"):
                # Force a specific function call
                tool_config["function_calling_config"]["allowed_function_names"] = [tool_choice]
                tool_config["function_calling_config"]["mode"] = "ANY"

        # Create model instance
        model_kwargs = {
            "model_name": model_name,
            "generation_config": generation_config,
            "safety_settings": self._get_safety_settings(),
        }

        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        # Add tools if provided and supported
        gemini_tools = None
        if effective_tools:
            gemini_tools = self._convert_tools(effective_tools)
            if gemini_tools:
                model_kwargs["tools"] = gemini_tools
                # Apply tool configuration to enforce function calling
                if tool_config:
                    model_kwargs["tool_config"] = tool_config
                # DIAGNOSTIC: Log tool provisioning
                # print(f"  [GEMINI] Converted {len(effective_tools)} OpenAI tools to {len(gemini_tools[0].get('function_declarations', []))} Gemini function declarations")
                # print(f"  [GEMINI] Tool config: {tool_config}")
            else:
                print(f"  [GEMINI] WARNING: Tool conversion returned empty! Original tools count: {len(effective_tools)}")

        # Log request
        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            model = genai.GenerativeModel(**model_kwargs)

            # DIAGNOSTIC: Log model configuration
            # print(f"  [GEMINI] Model: {model_name}")
            # print(f"  [GEMINI] Has tools: {bool(gemini_tools)}")
            # print(f"  [GEMINI] Has system_instruction: {bool(system_instruction)}")

            # Generate response
            response = model.generate_content(converted_messages)

            # DIAGNOSTIC: Log raw response structure
            if hasattr(response, 'candidates'):
                # print(f"  [GEMINI] Response has {len(response.candidates)} candidate(s)")
                if response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content'):
                        content = candidate.content
                        if hasattr(content, 'parts'):
                            # print(f"  [GEMINI] First candidate has {len(content.parts)} part(s)")
                            for i, part in enumerate(content.parts):
                                if hasattr(part, 'function_call'):
                                    # print(f"  [GEMINI] Part {i}: function_call - {part.function_call.name}")
                                    pass
                                elif hasattr(part, 'text'):
                                    # print(f"  [GEMINI] Part {i}: text - {part.text[:100]}...")
                                    pass
                    if hasattr(candidate, 'finish_reason'):
                        # print(f"  [GEMINI] Finish reason: {candidate.finish_reason}")
                        pass

            result = self._convert_response(
                response.candidates[0].content if response.candidates else response,
                getattr(response, "usage_metadata", None)
            )

            debug_logger.log_llm_response(model_name, result, cached=False)
            return result

        except Exception as e:
            debug_logger.log("llm", "GEMINI_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"Gemini API error: {e}"}

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        on_chunk: Optional[Callable[[str], None]] = None,
        check_interrupt: Optional[Callable[[], bool]] = None,
        check_user_messages: Optional[Callable[[], bool]] = None,
        tool_choice: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Stream chat responses from Gemini."""
        genai = self._get_client()
        debug_logger = get_logger()

        model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

        system_instruction, converted_messages = self._convert_messages(messages)

        generation_config = {
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", str(config.GEMINI_TEMPERATURE))),
            "top_p": float(os.getenv("GEMINI_TOP_P", "0.9")),
            "top_k": int(os.getenv("GEMINI_TOP_K", "40")),
            "max_output_tokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
        }

        # Configure tool calling behavior for streaming
        tool_config = None
        effective_tools = tools if tool_choice != "none" else None

        if effective_tools:
            mode = "ANY" if tool_choice == "required" or tool_choice == "any" else "AUTO"
            tool_config = {
                "function_calling_config": {
                    "mode": mode
                }
            }
            if tool_choice and tool_choice not in ("auto", "none", "required", "any"):
                # Force a specific function call
                tool_config["function_calling_config"]["allowed_function_names"] = [tool_choice]
                tool_config["function_calling_config"]["mode"] = "ANY"

        model_kwargs = {
            "model_name": model_name,
            "generation_config": generation_config,
            "safety_settings": self._get_safety_settings(),
        }

        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        if effective_tools:
            gemini_tools = self._convert_tools(effective_tools)
            if gemini_tools:
                model_kwargs["tools"] = gemini_tools
                if tool_config:
                    model_kwargs["tool_config"] = tool_config

        debug_logger.log_llm_request(model_name, messages, effective_tools if effective_tools and supports_tools else None)

        try:
            model = genai.GenerativeModel(**model_kwargs)

            accumulated_content = ""
            accumulated_tool_calls = []
            usage_info = {"prompt": 0, "completion": 0, "total": 0}

            # Stream response
            response_stream = model.generate_content(converted_messages, stream=True)

            for chunk in response_stream:
                # Check for interrupts
                if check_interrupt and check_interrupt():
                    if on_chunk:
                        on_chunk("\n[Cancelled]")
                    raise KeyboardInterrupt("Execution interrupted")

                if check_user_messages:
                    check_user_messages()

                # Extract text from chunk - check parts first for function calls
                if hasattr(chunk, "parts"):
                    for part in chunk.parts:
                        if hasattr(part, "function_call") and part.function_call and getattr(part.function_call, "name", None):
                            fc = part.function_call
                            accumulated_tool_calls.append({
                                "function": {
                                    "name": fc.name,
                                    "arguments": json.dumps(dict(fc.args or {})),
                                }
                            })
                        else:
                            text = getattr(part, "text", None)
                            if text:
                                accumulated_content += text
                                if on_chunk:
                                    on_chunk(text)
                elif hasattr(chunk, "text"):
                    text = chunk.text
                    accumulated_content += text
                    if on_chunk:
                        on_chunk(text)

            # Get usage from final chunk
            if hasattr(response_stream, "usage_metadata"):
                usage_info["prompt"] = getattr(response_stream.usage_metadata, "prompt_token_count", 0)
                usage_info["completion"] = getattr(response_stream.usage_metadata, "candidates_token_count", 0)
                usage_info["total"] = getattr(response_stream.usage_metadata, "total_token_count", 0)

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
            debug_logger.log("llm", "GEMINI_STREAM_ERROR", {"error": str(e)}, "ERROR")
            return {"error": f"Gemini streaming error: {e}"}

    def supports_tool_calling(self, model: str) -> bool:
        """Check if model supports tool calling."""
        # Gemini Pro and Flash models support function calling
        tool_capable_models = ["gemini-pro", "gemini-flash", "gemini-1.5", "gemini-2.0"]
        return any(model.startswith(prefix) for prefix in tool_capable_models)

    def validate_config(self) -> bool:
        """Validate Gemini configuration."""
        if not self.api_key:
            return False

        try:
            genai = self._get_client()
            # Try to list models to verify credentials
            list(genai.list_models())
            return True
        except Exception:
            return False

    def get_model_list(self) -> List[str]:
        """Get list of available Gemini models."""
        try:
            genai = self._get_client()
            models = genai.list_models()
            return [m.name.replace("models/", "") for m in models if "generateContent" in m.supported_generation_methods]
        except Exception:
            return []

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens for messages using character-based estimation.

        Gemini has a count_tokens API but this requires actual API calls.
        This is a fallback estimation: ~4 characters per token.
        """
        total_chars = 0
        for message in messages:
            # Count content
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Handle structured content (Gemini uses parts)
                for item in content:
                    if isinstance(item, dict):
                        # Could be text part, function call, or function response
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
        if "timeout" in error_str or "timed out" in error_str or "deadline exceeded" in error_str:
            return ProviderError(
                error_class=ErrorClass.TIMEOUT,
                message=str(error),
                retryable=True,
                original_error=error
            )

        # Check for connection/network errors
        if any(keyword in error_str for keyword in ["connection", "network", "unreachable", "refused", "unavailable"]):
            return ProviderError(
                error_class=ErrorClass.NETWORK_ERROR,
                message=str(error),
                retryable=True,
                original_error=error
            )

        # Check for rate limit errors (Gemini uses 429 and resource_exhausted)
        if any(keyword in error_str for keyword in [
            "rate limit", "429", "too many requests", "quota", "resource_exhausted", "quota exceeded"
        ]):
            # Try to extract retry-after
            retry_after = None
            if "retry" in error_str:
                try:
                    import re
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
        if any(keyword in error_str for keyword in [
            "auth", "unauthorized", "401", "api key", "invalid_api_key", "unauthenticated", "permission denied"
        ]):
            return ProviderError(
                error_class=ErrorClass.AUTH_ERROR,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for model not found errors
        if "404" in error_str or "model not found" in error_str or "does not exist" in error_str or "not found" in error_str:
            return ProviderError(
                error_class=ErrorClass.MODEL_NOT_FOUND,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for invalid request errors (Gemini uses invalid_argument)
        if any(keyword in error_str for keyword in [
            "400", "invalid", "bad request", "invalid_argument", "invalid request"
        ]):
            return ProviderError(
                error_class=ErrorClass.INVALID_REQUEST,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for context length errors
        if any(keyword in error_str for keyword in [
            "context", "too long", "maximum", "max_output_tokens", "token limit", "input too long"
        ]):
            return ProviderError(
                error_class=ErrorClass.CONTEXT_LENGTH_EXCEEDED,
                message=str(error),
                retryable=False,
                original_error=error
            )

        # Check for server errors (5xx, internal, unavailable)
        if any(keyword in error_str for keyword in [
            "500", "502", "503", "504", "server error", "internal error", "internal", "unavailable"
        ]):
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
        """Get retry configuration for Gemini."""
        return RetryConfig(
            max_retries=int(os.getenv("GEMINI_MAX_RETRIES", "3")),
            base_backoff=float(os.getenv("GEMINI_BASE_BACKOFF", "1.0")),
            max_backoff=float(os.getenv("GEMINI_MAX_BACKOFF", "60.0")),
            exponential=True,
            retry_on=[
                ErrorClass.RATE_LIMIT,
                ErrorClass.TIMEOUT,
                ErrorClass.SERVER_ERROR,
                ErrorClass.NETWORK_ERROR,
            ]
        )
