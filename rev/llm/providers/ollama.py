"""Ollama LLM provider implementation."""

import os
import json
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from rev import config
from rev.cache import LLMResponseCache, get_llm_cache
from rev.debug_logger import get_logger
from .base import LLMProvider, ErrorClass, ProviderError, RetryConfig


# Debug mode
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"

# Token estimation constants
_CHARS_PER_TOKEN_ESTIMATE = 3
_TOKEN_BUDGET_MULTIPLIER = 0.9

# Global flag for interrupt handling
_interrupt_requested = threading.Event()


def _signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C)."""
    _interrupt_requested.set()
    raise KeyboardInterrupt


def _setup_signal_handlers():
    """Setup signal handlers for cross-platform interrupt handling."""
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _signal_handler)


def _stringify_content(content: Any) -> str:
    """Convert LLM message content to a string for estimation purposes."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _estimate_message_tokens(message: Dict[str, Any]) -> int:
    """Roughly estimate token usage for a single message."""
    text = _stringify_content(message.get("content", ""))

    # Include thinking content if present (common in reasoning models)
    if "thinking" in message:
        text += "\n" + str(message["thinking"])

    # Include tool calls if present
    if "tool_calls" in message:
        for tool_call in message["tool_calls"]:
            func = tool_call.get("function", {})
            text += "\n" + str(func.get("name", ""))
            text += "\n" + str(func.get("arguments", ""))

    return max(0, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def _truncate_message_content(message: Dict[str, Any], remaining_tokens: int) -> Tuple[Dict[str, Any], int]:
    """Trim message content to fit within the remaining token budget."""
    if remaining_tokens <= 0:
        return {**message, "content": ""}, 0

    original_text = _stringify_content(message.get("content", ""))
    max_chars = max(0, remaining_tokens * _CHARS_PER_TOKEN_ESTIMATE)

    if len(original_text) <= max_chars:
        return message, _estimate_message_tokens(message)

    suffix = "\n...[truncated to fit token limit]..."
    trimmed_text = original_text[: max(0, max_chars - len(suffix))] + suffix
    truncated_message = {**message, "content": trimmed_text}
    return truncated_message, _estimate_message_tokens(truncated_message)


def _ensure_last_user_or_tool(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """Ollama's /api/chat expects the last message role to be 'user' or 'tool'."""
    if not messages:
        return messages, False

    last_role = (messages[-1] or {}).get("role")
    if last_role in {"user", "tool"}:
        return messages, False

    fixed = list(messages)
    fixed.append({"role": "user", "content": "Continue."})
    return fixed, True


def _enforce_token_limit(messages: List[Dict[str, Any]], max_tokens: int) -> Tuple[List[Dict[str, Any]], int, int, bool]:
    """Ensure messages stay within the configured token limit."""
    effective_max_tokens = int(max_tokens * _TOKEN_BUDGET_MULTIPLIER)

    if max_tokens <= 0:
        return [], 0, 0, True

    original_tokens = sum(_estimate_message_tokens(m) for m in messages)
    if original_tokens <= effective_max_tokens:
        return messages, original_tokens, original_tokens, False

    # Always keep system messages first
    system_messages = [m for m in messages if m.get("role") == "system"]
    other_messages = [m for m in messages if m.get("role") != "system"]

    truncated_messages: List[Dict[str, Any]] = []
    token_tally = 0
    truncated = False

    # Reserve budget for recent messages
    reserved_recent = max(1, effective_max_tokens // 10)
    system_budget = max(0, effective_max_tokens - reserved_recent)
    remaining_tokens = system_budget

    # Add system messages
    for msg in system_messages:
        msg_tokens = _estimate_message_tokens(msg)
        allowed_tokens = max(0, system_budget - token_tally)
        if msg_tokens > allowed_tokens:
            msg, msg_tokens = _truncate_message_content(msg, allowed_tokens)
            truncated = True
            msg_tokens = min(msg_tokens, allowed_tokens)
        truncated_messages.append(msg)
        token_tally += msg_tokens
        remaining_tokens = max(0, effective_max_tokens - token_tally)

    # Add most recent non-system messages
    preserved: List[Dict[str, Any]] = []
    for msg in reversed(other_messages):
        if remaining_tokens <= 0:
            truncated = True
            break

        msg_tokens = _estimate_message_tokens(msg)
        if msg_tokens > remaining_tokens:
            msg, msg_tokens = _truncate_message_content(msg, remaining_tokens)
            truncated = True
            msg_tokens = min(msg_tokens, remaining_tokens)
        preserved.append(msg)
        token_tally += msg_tokens
        remaining_tokens = max(0, remaining_tokens - msg_tokens)

    preserved.reverse()
    truncated_messages.extend(preserved)

    return truncated_messages, original_tokens, token_tally, truncated


def _make_request_interruptible(url, json_payload, timeout):
    """Make an HTTP request that can be interrupted by Ctrl+C."""
    result = {"response": None, "error": None}

    def do_request():
        try:
            result["response"] = requests.post(url, json=json_payload, timeout=timeout)
        except Exception as e:
            result["error"] = e

    request_thread = threading.Thread(target=do_request, daemon=True)
    request_thread.start()

    while request_thread.is_alive():
        request_thread.join(timeout=0.5)
        if _interrupt_requested.is_set():
            raise KeyboardInterrupt("Request cancelled by user (Ctrl+C)")

    if result["error"]:
        raise result["error"]

    return result["response"]


class OllamaProvider(LLMProvider):
    """Ollama LLM provider."""

    def __init__(self):
        super().__init__()
        self.name = "ollama"
        self.base_url = config.OLLAMA_BASE_URL

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        supports_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request to Ollama."""
        _setup_signal_handlers()
        _interrupt_requested.clear()

        # Token limit enforcement
        trimmed_messages, original_tokens, trimmed_tokens, was_truncated = _enforce_token_limit(
            messages,
            config.MAX_LLM_TOKENS_PER_RUN,
        )

        prompt_tokens_estimate = trimmed_tokens

        if was_truncated:
            print(
                f"  Context trimmed from ~{original_tokens:,} to ~{trimmed_tokens:,} tokens "
                f"(limit {config.MAX_LLM_TOKENS_PER_RUN:,})."
            )

        messages = trimmed_messages
        messages, _appended_continue = _ensure_last_user_or_tool(messages)

        model_name = model or config.OLLAMA_MODEL
        supports_tools = config.DEFAULT_SUPPORTS_TOOLS if supports_tools is None else supports_tools
        if tools:
            supports_tools = True

        # Get cache
        llm_cache = get_llm_cache() or LLMResponseCache()
        tools_provided = tools is not None

        # Check cache
        cached_response = llm_cache.get_response(messages, tools if tools_provided else None, model_name)
        if cached_response is not None:
            if OLLAMA_DEBUG:
                print("[DEBUG] Using cached LLM response")
            cached_response.setdefault("usage", {"prompt": 0, "completion": 0, "total": 0})
            debug_logger = get_logger()
            debug_logger.log_llm_response(model_name, cached_response, cached=True)
            return cached_response

        # Build request
        url = f"{self.base_url}/api/chat"
        is_cloud_model = model_name.endswith("-cloud") or model_name.endswith(":cloud")

        if is_cloud_model and OLLAMA_DEBUG and not hasattr(self, '_cloud_model_notified'):
            print(f"ℹ️  Using cloud model: {model_name} (proxied through local Ollama)")
            self._cloud_model_notified = True

        # Extract options from kwargs or use defaults
        options = {
            "temperature": kwargs.get("temperature", config.OLLAMA_TEMPERATURE),
            "num_ctx": kwargs.get("num_ctx", config.OLLAMA_NUM_CTX),
            "top_p": kwargs.get("top_p", config.OLLAMA_TOP_P),
            "top_k": kwargs.get("top_k", config.OLLAMA_TOP_K),
        }
        explicit_tool_choice = kwargs.pop("tool_choice", None)

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": options
        }

        if "format" in kwargs and kwargs["format"] is not None:
            payload["format"] = kwargs["format"]

        # CRITICAL FIX: Use standard OpenAI-compatible tools format
        # Ollama supports tools field directly without "mode": "tools"
        if tools_provided:
            payload["tools"] = tools or []
            # CRITICAL: Force tool use when tools are provided (like OpenAI/Anthropic)
            # This prevents models from returning text instead of calling tools
            # Some Ollama models support "required", others use "auto"
            # Using "auto" is safer and works across more models, but allow explicit override.
            if supports_tools and tools:
                payload["tool_choice"] = explicit_tool_choice or "auto"

        # Log request
        debug_logger = get_logger()
        debug_logger.log_llm_request(model_name, messages, tools if tools_provided else None)

        if OLLAMA_DEBUG:
            print(f"[DEBUG] Ollama request to {url}")
            print(f"[DEBUG] Model: {model_name}")

        # Retry logic
        max_retries, retry_forever, retry_backoff, max_backoff, timeout_cap = self._get_retry_config()
        base_timeout = 600
        max_attempts = max_retries if max_retries > 0 else 1
        auth_prompted = False

        attempt = 0
        while attempt < max_attempts or retry_forever:
            timeout = base_timeout * min(attempt + 1, timeout_cap)

            try:
                resp = _make_request_interruptible(url, payload, timeout)

                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Response status: {resp.status_code}")

                # Some Ollama-compatible proxies expose an OpenAI-compatible endpoint only.
                # If /api/chat is missing, fall back to /v1/chat/completions.
                if resp.status_code == 404:
                    v1_url = f"{self.base_url}/v1/chat/completions"
                    v1_payload = {
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                        "temperature": options.get("temperature", config.OLLAMA_TEMPERATURE),
                        "top_p": options.get("top_p", config.OLLAMA_TOP_P),
                    }
                    try:
                        v1_resp = _make_request_interruptible(v1_url, v1_payload, timeout)
                        v1_resp.raise_for_status()
                        v1_data = v1_resp.json()
                        # Normalize OpenAI-style response into our standard format.
                        msg = (
                            (v1_data.get("choices") or [{}])[0].get("message")
                            if isinstance(v1_data, dict)
                            else None
                        ) or {}
                        normalized = {"message": msg}
                        completion_tokens = _estimate_message_tokens(normalized.get("message", {}))
                        normalized["usage"] = {
                            "prompt": prompt_tokens_estimate,
                            "completion": completion_tokens,
                            "total": prompt_tokens_estimate + completion_tokens,
                        }
                        debug_logger.log_llm_response(model_name, normalized, cached=False)
                        llm_cache.set_response(messages, normalized, tools if tools_provided else None, model_name)
                        return normalized
                    except Exception as exc:
                        # Preserve original error context if fallback fails.
                        if OLLAMA_DEBUG:
                            print(f"[DEBUG] /v1/chat/completions fallback failed: {exc}")

                # Handle 401 for cloud models
                if resp.status_code == 401:
                    try:
                        error_data = resp.json()
                        signin_url = error_data.get("signin_url")

                        if signin_url and not auth_prompted:
                            auth_prompted = True
                            print("\n" + "=" * 60)
                            print("OLLAMA CLOUD AUTHENTICATION REQUIRED")
                            print("=" * 60)
                            print(f"\nModel '{model_name}' requires authentication.")
                            print(f"\n1. Visit: {signin_url}")
                            print(f"2. Sign in with your Ollama account")
                            print(f"3. Authorize this device\n")
                            print("=" * 60)

                            try:
                                input("\nPress Enter after authentication, or Ctrl+C to cancel...")
                            except KeyboardInterrupt:
                                return {"error": "Authentication cancelled by user"}

                            print("\nRetrying request...")
                            continue
                        else:
                            return {"error": f"Ollama API error: {resp.status_code} {resp.reason}"}
                    except json.JSONDecodeError:
                        return {"error": f"Ollama API error: {resp.status_code} {resp.reason}"}

                # Try safer fallbacks if the model rejects tool_choice/tool payloads
                if resp.status_code == 400 and tools_provided:
                    # 1) If explicit tool_choice was set, downshift to auto (keep tools)
                    if explicit_tool_choice and payload.get("tool_choice"):
                        payload_auto = payload.copy()
                        payload_auto["tool_choice"] = "auto"
                        try:
                            resp_auto = _make_request_interruptible(url, payload_auto, timeout)
                            if OLLAMA_DEBUG:
                                print("[DEBUG] Got 400 with explicit tool_choice, retrying with tool_choice=auto...")
                                print(f"[DEBUG] Response status: {resp_auto.status_code}")
                            if resp_auto.status_code < 400:
                                resp = resp_auto
                                payload = payload_auto
                        except Exception as exc:
                            if OLLAMA_DEBUG:
                                print(f"[DEBUG] Exception with tool_choice=auto fallback: {exc}")

                    # 2) Remove tool_choice entirely (keep tools)
                    if resp.status_code == 400 and "tool_choice" in payload:
                        if OLLAMA_DEBUG:
                            print("[DEBUG] Got 400 with tool_choice, retrying without tool_choice...")
                        payload_no_choice = payload.copy()
                        payload_no_choice.pop("tool_choice", None)
                        try:
                            resp_no_choice = _make_request_interruptible(url, payload_no_choice, timeout)
                            if resp_no_choice.status_code < 400:
                                resp = resp_no_choice
                                payload = payload_no_choice
                            else:
                                resp = resp_no_choice
                        except Exception as exc:
                            if OLLAMA_DEBUG:
                                print(f"[DEBUG] Exception with tool_choice removal: {exc}")

                    # 3) Last resort: drop tools entirely
                    if resp.status_code == 400:
                        if OLLAMA_DEBUG:
                            print("[DEBUG] Got 400 with tools, retrying without tools...")
                        payload_no_tools = {
                            "model": model_name,
                            "messages": messages,
                            "stream": False,
                            "options": payload.get("options", {})
                        }
                        try:
                            resp_no_tools = _make_request_interruptible(url, payload_no_tools, timeout)
                            if resp_no_tools.status_code < 400:
                                resp = resp_no_tools
                                payload = payload_no_tools
                                tools_provided = False
                            else:
                                resp = resp_no_tools
                        except Exception as exc:
                            if OLLAMA_DEBUG:
                                print(f"[DEBUG] Exception with no-tools fallback: {exc}")

                resp.raise_for_status()
                response = resp.json()

                # Use provider usage stats if available (Ollama uses prompt_eval_count/eval_count)
                if "prompt_eval_count" in response and "eval_count" in response:
                    response["usage"] = {
                        "prompt": response["prompt_eval_count"],
                        "completion": response["eval_count"],
                        "total": response["prompt_eval_count"] + response["eval_count"],
                    }
                elif "usage" not in response:
                    # Fallback to estimation
                    completion_tokens = _estimate_message_tokens(response.get("message", {}))
                    response["usage"] = {
                        "prompt": prompt_tokens_estimate,
                        "completion": completion_tokens,
                        "total": prompt_tokens_estimate + completion_tokens,
                    }

                debug_logger.log_llm_response(model_name, response, cached=False)
                llm_cache.set_response(messages, response, tools if tools_provided else None, model_name)

                return response

            except KeyboardInterrupt:
                print("\n\nRequest cancelled by user (Ctrl+C)")
                raise

            except requests.exceptions.Timeout:
                should_retry = retry_forever or attempt < max_attempts - 1
                if should_retry:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Ollama API timeout after {attempt + 1} attempts"}

            except requests.exceptions.HTTPError as e:
                status_code = resp.status_code if 'resp' in locals() else None
                retryable_http = status_code is not None and status_code >= 500
                should_retry = retryable_http and (retry_forever or attempt < max_attempts - 1)
                if should_retry:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Ollama API error: {e}"}

            except requests.exceptions.RequestException as e:
                should_retry = retry_forever or attempt < max_attempts - 1
                if should_retry:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Ollama API error: {e}"}

            except Exception as e:
                if retry_forever:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Ollama API error: {e}"}

            attempt += 1

        return {"error": f"Ollama API retries exhausted after {attempt} attempt(s)"}

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
        """Stream chat responses from Ollama."""
        _setup_signal_handlers()
        _interrupt_requested.clear()

        # Token limit enforcement
        trimmed_messages, original_tokens, trimmed_tokens, was_truncated = _enforce_token_limit(
            messages,
            config.MAX_LLM_TOKENS_PER_RUN,
        )

        prompt_tokens_estimate = trimmed_tokens

        if was_truncated:
            print(
                f"  Context trimmed from ~{original_tokens:,} to ~{trimmed_tokens:,} tokens "
                f"(limit {config.MAX_LLM_TOKENS_PER_RUN:,})."
            )

        messages = trimmed_messages
        messages, _appended_continue = _ensure_last_user_or_tool(messages)

        model_name = model or config.OLLAMA_MODEL
        supports_tools = config.DEFAULT_SUPPORTS_TOOLS if supports_tools is None else supports_tools
        if tools:
            supports_tools = True
        tools_provided = tools is not None

        url = f"{self.base_url}/api/chat"
        is_cloud_model = model_name.endswith("-cloud") or model_name.endswith(":cloud")

        if is_cloud_model and OLLAMA_DEBUG and not hasattr(self, '_cloud_model_notified'):
            print(f"ℹ️  Using cloud model: {model_name} (proxied through local Ollama)")
            self._cloud_model_notified = True

        # Extract options from kwargs or use defaults
        options = {
            "temperature": kwargs.get("temperature", config.OLLAMA_TEMPERATURE),
            "num_ctx": kwargs.get("num_ctx", config.OLLAMA_NUM_CTX),
            "top_p": kwargs.get("top_p", config.OLLAMA_TOP_P),
            "top_k": kwargs.get("top_k", config.OLLAMA_TOP_K),
        }

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "options": options
        }

        # CRITICAL FIX: Use standard OpenAI-compatible tools format
        # Ollama supports tools field directly without "mode": "tools"
        if tools_provided:
            payload["tools"] = tools or []
            # Force tool use when tools are provided
            if supports_tools and tools:
                payload["tool_choice"] = "auto"

        debug_logger = get_logger()
        debug_logger.log_llm_request(model_name, messages, tools if tools_provided else None)

        max_retries, retry_forever, retry_backoff, max_backoff, timeout_cap = self._get_retry_config()
        base_timeout = 600
        max_attempts = max_retries if max_retries > 0 else 1

        attempt = 0
        while attempt < max_attempts or retry_forever:
            timeout = base_timeout * min(attempt + 1, timeout_cap)

            try:
                response = requests.post(url, json=payload, timeout=timeout, stream=True)

                if response.status_code == 400 and tools_provided:
                    # Try removing tool_choice first, then tools
                    if "tool_choice" in payload:
                        payload_no_choice = payload.copy()
                        payload_no_choice.pop("tool_choice", None)
                        try:
                            response = requests.post(url, json=payload_no_choice, timeout=timeout, stream=True)
                            if response.status_code == 200:
                                payload = payload_no_choice
                        except Exception:
                            pass

                    # If still failing, try without tools
                    if response.status_code == 400:
                        payload_no_tools = {
                            "model": model_name,
                            "messages": messages,
                            "stream": True,
                            "options": payload.get("options", {})
                        }
                        response = requests.post(url, json=payload_no_tools, timeout=timeout, stream=True)

                response.raise_for_status()

                # Accumulate streaming response
                accumulated_content = ""
                accumulated_tool_calls = []
                final_message = {}

                for line in response.iter_lines():
                    if _interrupt_requested.is_set():
                        raise KeyboardInterrupt("Request cancelled by user")

                    if check_interrupt and check_interrupt():
                        raise KeyboardInterrupt("Execution interrupted")

                    if check_user_messages:
                        check_user_messages()

                    if not line:
                        continue

                    try:
                        chunk_data = json.loads(line)

                        if "error" in chunk_data:
                            return {"error": chunk_data["error"]}

                        msg = chunk_data.get("message", {})
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])

                        if content:
                            accumulated_content += content
                            if on_chunk:
                                on_chunk(content)

                        if tool_calls:
                            accumulated_tool_calls.extend(tool_calls)

                        if chunk_data.get("done", False):
                            final_message = {
                                "role": "assistant",
                                "content": accumulated_content,
                            }
                            if accumulated_tool_calls:
                                final_message["tool_calls"] = accumulated_tool_calls
                            break

                    except json.JSONDecodeError:
                        continue

                # Build complete response
                completion_tokens = _estimate_message_tokens(final_message)

                result = {
                    "message": final_message,
                    "done": True,
                    "usage": {
                        "prompt": prompt_tokens_estimate,
                        "completion": completion_tokens,
                        "total": prompt_tokens_estimate + completion_tokens,
                    }
                }

                debug_logger.log_llm_response(model_name, result, cached=False)
                return result

            except KeyboardInterrupt:
                if on_chunk:
                    on_chunk("\n[Cancelled]")
                raise

            except requests.exceptions.Timeout:
                should_retry = retry_forever or attempt < max_attempts - 1
                if should_retry:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Streaming timeout after {attempt + 1} attempts"}

            except requests.exceptions.RequestException as e:
                should_retry = retry_forever or attempt < max_attempts - 1
                if should_retry:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Streaming error: {e}"}

            except Exception as e:
                if retry_forever:
                    self._sleep_before_retry(retry_backoff, max_backoff, attempt)
                    attempt += 1
                    continue
                return {"error": f"Streaming error: {e}"}

            attempt += 1

        return {"error": f"Streaming retries exhausted after {attempt} attempt(s)"}

    def supports_tool_calling(self, model: str) -> bool:
        """Check if model supports tool calling.

        Based on Ollama documentation, models with "tools" pill support function calling.
        Includes both local and cloud models (e.g., model-name:cloud).
        """
        # Strip version/tag info for matching (e.g., "model:cloud" -> "model")
        model_lower = model.lower()
        model_base = model_lower.split(':')[0]

        # Cloud models typically support tools
        if ':cloud' in model_lower or '-cloud' in model_lower:
            return True

        # Known tool-capable model families
        tool_capable_prefixes = [
            # Llama family
            "llama3.1", "llama3.2", "llama-3.1", "llama-3.2",
            # Mistral family
            "mistral", "mixtral", "devstral",
            # Qwen family
            "qwen2.5", "qwen-2.5", "qwen3", "qwen-3",
            # Command family
            "command-r", "commandr",
            # DeepSeek family
            "deepseek", "deep-seek",
            # GLM family
            "glm-4", "glm4",
            # Gemini family
            "gemini-2", "gemini-3", "gemini2", "gemini3",
            # Other tool-capable models
            "granite", "phi3", "phi-3",
            "cogito", "kimi", "nemotron",
            "gpt-oss", "rnj"
        ]

        return any(model_base.startswith(prefix) for prefix in tool_capable_prefixes)

    def validate_config(self) -> bool:
        """Validate Ollama configuration."""
        try:
            # Simple check: try to reach Ollama
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_model_list(self) -> List[str]:
        """Get list of available Ollama models."""
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception:
            return []

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens for messages using character-based estimation.

        Args:
            messages: List of message dicts

        Returns:
            Estimated token count
        """
        total_tokens = 0
        for message in messages:
            total_tokens += _estimate_message_tokens(message)
        return total_tokens

    def classify_error(self, error: Exception) -> ProviderError:
        """Classify an error into standard ErrorClass.

        Args:
            error: The exception that occurred

        Returns:
            ProviderError with classification
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Check for specific error types
        if isinstance(error, requests.exceptions.Timeout) or "timeout" in error_str:
            return ProviderError(
                error_class=ErrorClass.TIMEOUT,
                message=str(error),
                retryable=True,
                original_error=error
            )

        if isinstance(error, requests.exceptions.ConnectionError) or "connection" in error_str:
            return ProviderError(
                error_class=ErrorClass.NETWORK_ERROR,
                message=str(error),
                retryable=True,
                original_error=error
            )

        if "rate limit" in error_str or "too many requests" in error_str or "429" in error_str:
            return ProviderError(
                error_class=ErrorClass.RATE_LIMIT,
                message=str(error),
                retryable=True,
                retry_after=60.0,  # Default 60s for rate limits
                original_error=error
            )

        if "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            return ProviderError(
                error_class=ErrorClass.AUTH_ERROR,
                message=str(error),
                retryable=False,
                original_error=error
            )

        if "404" in error_str or "not found" in error_str:
            return ProviderError(
                error_class=ErrorClass.MODEL_NOT_FOUND,
                message=str(error),
                retryable=False,
                original_error=error
            )

        if "400" in error_str or "invalid" in error_str or "bad request" in error_str:
            return ProviderError(
                error_class=ErrorClass.INVALID_REQUEST,
                message=str(error),
                retryable=False,
                original_error=error
            )

        if "context length" in error_str or "too long" in error_str:
            return ProviderError(
                error_class=ErrorClass.CONTEXT_LENGTH_EXCEEDED,
                message=str(error),
                retryable=False,
                original_error=error
            )

        if any(code in error_str for code in ["500", "502", "503", "504"]) or "server error" in error_str:
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
        """Get retry configuration for Ollama.

        Returns:
            RetryConfig with Ollama-specific settings
        """
        max_retries, _, backoff, max_backoff, _ = self._get_retry_config()

        return RetryConfig(
            max_retries=max_retries if max_retries > 0 else 3,  # Default to 3 if infinite
            base_backoff=backoff,
            max_backoff=max_backoff,
            exponential=True,
            retry_on=[
                ErrorClass.RATE_LIMIT,
                ErrorClass.TIMEOUT,
                ErrorClass.SERVER_ERROR,
                ErrorClass.NETWORK_ERROR,
            ]
        )

    def _get_retry_config(self):
        """Get retry/backoff configuration from environment variables."""
        raw = os.getenv("OLLAMA_MAX_RETRIES", "0").strip().lower()
        retry_forever_env = os.getenv("OLLAMA_RETRY_FOREVER", "0").strip() == "1"

        max_retries = 0
        if raw in {"inf", "infinite", "forever"}:
            max_retries = 0
        else:
            try:
                max_retries = int(raw)
            except Exception:
                max_retries = 0

        retry_forever = retry_forever_env or max_retries <= 0

        backoff_seconds = max(0.0, float(os.getenv("OLLAMA_RETRY_BACKOFF_SECONDS", "2.0")))
        max_backoff_seconds = max(0.0, float(os.getenv("OLLAMA_RETRY_BACKOFF_MAX_SECONDS", "30.0")))
        timeout_multiplier_cap = max(1, int(os.getenv("OLLAMA_TIMEOUT_MAX_MULTIPLIER", "3")))

        if not retry_forever:
            max_retries = max(1, max_retries)

        return max_retries, retry_forever, backoff_seconds, max_backoff_seconds, timeout_multiplier_cap

    def _sleep_before_retry(self, retry_backoff, max_backoff, attempt):
        """Sleep with capped backoff before retry."""
        delay = min(max_backoff, retry_backoff * (attempt + 1))
        if delay > 0:
            if OLLAMA_DEBUG:
                print(f"[DEBUG] Sleeping {delay}s before retry...")
            time.sleep(delay)
