"""Google Gemini LLM provider implementation."""

import os
import json
from typing import Any, Callable, Dict, List, Optional

from rev import config
from rev.debug_logger import get_logger
from .base import LLMProvider


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
                print("⚠️  WARNING: No Gemini API key found!")
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
                converted.append({
                    "role": "model",  # Gemini uses "model" instead of "assistant"
                    "parts": [{"text": content}],
                })
            elif role == "user":
                converted.append({
                    "role": "user",
                    "parts": [{"text": content}],
                })
            elif role == "tool":
                # Gemini tool results
                converted.append({
                    "role": "function",
                    "parts": [{
                        "function_response": {
                            "name": msg.get("name", ""),
                            "response": {"result": content},
                        }
                    }],
                })

        return system_instruction.strip(), converted

    def _remove_default_fields(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively remove 'default' fields from schema (Gemini doesn't support them)."""
        if not isinstance(schema, dict):
            return schema

        result = {}
        for key, value in schema.items():
            if key == "default":
                continue  # Skip 'default' fields
            elif isinstance(value, dict):
                result[key] = self._remove_default_fields(value)
            elif isinstance(value, list):
                result[key] = [
                    self._remove_default_fields(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tool definitions to Gemini format."""
        if not tools:
            return []

        converted = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                # Remove 'default' fields from parameters as Gemini doesn't support them
                parameters = self._remove_default_fields(func.get("parameters", {}))
                converted.append({
                    "function_declarations": [{
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "parameters": parameters,
                    }]
                })

        return converted

    def _convert_response(self, response: Any, usage_metadata: Optional[Any] = None) -> Dict[str, Any]:
        """Convert Gemini response to our standard format."""
        content = ""
        tool_calls = []

        # Extract content from response
        if hasattr(response, "text"):
            content = response.text
        elif hasattr(response, "parts"):
            for part in response.parts:
                if hasattr(part, "text"):
                    content += part.text
                elif hasattr(part, "function_call"):
                    # Handle function call
                    fc = part.function_call
                    tool_calls.append({
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args)),
                        }
                    })

        result_message = {
            "role": "assistant",
            "content": content,
        }

        if tool_calls:
            result_message["tool_calls"] = tool_calls

        # Extract usage information
        usage = {"prompt": 0, "completion": 0, "total": 0}
        if usage_metadata:
            usage["prompt"] = getattr(usage_metadata, "prompt_token_count", 0)
            usage["completion"] = getattr(usage_metadata, "candidates_token_count", 0)
            usage["total"] = getattr(usage_metadata, "total_token_count", 0)

        return {
            "message": result_message,
            "done": True,
            "usage": usage,
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request to Gemini."""
        genai = self._get_client()
        debug_logger = get_logger()

        # Default to Gemini 2.0 Flash
        model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

        # Convert messages to Gemini format
        system_instruction, converted_messages = self._convert_messages(messages)

        # Build generation config
        generation_config = {
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
            "top_p": float(os.getenv("GEMINI_TOP_P", "0.9")),
            "top_k": int(os.getenv("GEMINI_TOP_K", "40")),
            "max_output_tokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
        }

        # Create model instance
        model_kwargs = {
            "model_name": model_name,
            "generation_config": generation_config,
        }

        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        # Add tools if provided and supported
        if tools and supports_tools:
            gemini_tools = self._convert_tools(tools)
            if gemini_tools:
                model_kwargs["tools"] = gemini_tools

        # Log request
        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

        try:
            model = genai.GenerativeModel(**model_kwargs)

            # Generate response
            response = model.generate_content(converted_messages)

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
        **kwargs
    ) -> Dict[str, Any]:
        """Stream chat responses from Gemini."""
        genai = self._get_client()
        debug_logger = get_logger()

        model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

        system_instruction, converted_messages = self._convert_messages(messages)

        generation_config = {
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
            "top_p": float(os.getenv("GEMINI_TOP_P", "0.9")),
            "top_k": int(os.getenv("GEMINI_TOP_K", "40")),
            "max_output_tokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192")),
        }

        model_kwargs = {
            "model_name": model_name,
            "generation_config": generation_config,
        }

        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        if tools and supports_tools:
            gemini_tools = self._convert_tools(tools)
            if gemini_tools:
                model_kwargs["tools"] = gemini_tools

        debug_logger.log_llm_request(model_name, messages, tools if tools and supports_tools else None)

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

                # Extract text from chunk
                if hasattr(chunk, "text"):
                    text = chunk.text
                    accumulated_content += text
                    if on_chunk:
                        on_chunk(text)
                elif hasattr(chunk, "parts"):
                    for part in chunk.parts:
                        if hasattr(part, "text"):
                            accumulated_content += part.text
                            if on_chunk:
                                on_chunk(part.text)
                        elif hasattr(part, "function_call"):
                            fc = part.function_call
                            accumulated_tool_calls.append({
                                "function": {
                                    "name": fc.name,
                                    "arguments": json.dumps(dict(fc.args)),
                                }
                            })

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
