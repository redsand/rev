#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM (Language Model) client for rev with multi-provider support."""

import os
import json
import signal
import threading
import time
import random
import re
from typing import Dict, Any, List, Optional, Tuple

import requests

from rev import config
from rev.cache import LLMResponseCache, get_llm_cache
from rev.debug_logger import get_logger
from rev.llm.provider_factory import get_provider, get_provider_for_model
from rev.llm.tool_call_parser import parse_tool_calls_from_text


# Debug mode - set to True to see API requests/responses
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"

# Simple heuristic: average of ~3 characters per token for planning-sized prompts
# (intentionally conservative to avoid exceeding provider limits)
_CHARS_PER_TOKEN_ESTIMATE = 3

# Keep requests well below the provider cap to avoid hard failures when the
# heuristic underestimates token usage.
_TOKEN_BUDGET_MULTIPLIER = 0.9


class _TokenUsageTracker:
    """Lightweight in-memory tracker for estimated token usage."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def record(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += max(0, int(prompt))
        self.completion_tokens += max(0, int(completion))

    def reset(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def snapshot(self) -> Dict[str, int]:
        prompt = self.prompt_tokens
        completion = self.completion_tokens
        return {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
        }


_token_usage_tracker = _TokenUsageTracker()

# Cache per provider+model: None (unknown), True (supported), False (unsupported)
_THINKING_SUPPORT: Dict[str, Optional[bool]] = {}

_THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>", flags=re.IGNORECASE | re.DOTALL)
_ANALYSIS_BLOCK_RE = re.compile(r"<analysis>(.*?)</analysis>", flags=re.IGNORECASE | re.DOTALL)


def reset_thinking_capabilities() -> None:
    """Reset in-memory thinking capability cache (primarily for tests)."""
    _THINKING_SUPPORT.clear()


def _extract_thinking(text: str) -> Tuple[str, Optional[str]]:
    """Extract provider-emitted reasoning blocks and return (cleaned_text, thinking_raw)."""
    if not isinstance(text, str) or not text:
        return text, None

    thinking_parts: list[str] = []

    def _collect(match: re.Match) -> str:
        content = match.group(1) if match.groups() else ""
        if content:
            thinking_parts.append(content.strip())
        return ""

    cleaned = _THINK_BLOCK_RE.sub(_collect, text)
    cleaned = _ANALYSIS_BLOCK_RE.sub(_collect, cleaned)
    # Strip stray standalone <think> or </think> tags that were emitted without a full block
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).lstrip("\n")
    thinking_raw = "\n\n".join(thinking_parts) if thinking_parts else None
    return cleaned, thinking_raw


def _sanitize_response_content(response: Dict[str, Any]) -> Dict[str, Any]:
    """Strip chain-of-thought blocks and recover tool calls from assistant text when absent."""
    if not isinstance(response, dict):
        return response

    msg = response.get("message")
    if not isinstance(msg, dict):
        return response

    response = dict(response)
    msg = dict(msg)

    content = msg.get("content", "")
    thinking_raw = None
    if isinstance(content, str):
        content, thinking_raw = _extract_thinking(content)
    else:
        content = str(content) if content is not None else ""

    tool_calls = msg.get("tool_calls") or []

    # Attempt to recover tool calls from text when native tool_calls are missing.
    if content and not tool_calls:
        recovered, cleaned, errors = parse_tool_calls_from_text(content)
        if recovered:
            tool_calls = recovered
            content = cleaned
            response["tool_call_recovered"] = True
        if errors:
            response["tool_call_recovery_errors"] = errors

    msg["content"] = content
    if thinking_raw:
        # Preserve reasoning/thought tokens for downstream visibility and next requests
        msg["thinking"] = thinking_raw
        response["thinking_raw"] = thinking_raw
    if tool_calls:
        msg["tool_calls"] = tool_calls

    response["message"] = msg
    return response


def _thinking_cache_key(provider: Any, model: str) -> str:
    name = getattr(provider, "name", provider.__class__.__name__)
    return f"{name}:{model}"


def _provider_can_try_thinking(provider: Any) -> bool:
    # Avoid "thinking" for OpenAI until explicitly supported; it causes param errors on most models.
    return False


def _is_thinking_param_error(response: Dict[str, Any]) -> bool:
    """Detect errors that indicate an unsupported "thinking" parameter."""
    if not isinstance(response, dict):
        return False
    error = response.get("error")
    if not isinstance(error, str):
        return False
    lowered = error.lower()
    if "thinking" not in lowered:
        return False
    return any(
        token in lowered
        for token in (
            "unknown field",
            "unexpected keyword",
            "unexpected parameter",
            "unrecognized parameter",
            "invalid parameter",
            "not allowed",
            "unsupported",
        )
    )


def _call_with_auto_thinking(
    *,
    provider: Any,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    model_name: str,
    supports_tools: bool,
    **kwargs,
) -> Dict[str, Any]:
    """Call provider.chat with thinking enabled on first attempt, disable on failure."""
    if getattr(config, "LLM_THINKING_MODE", "auto") == "off":
        return provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **kwargs)
    if not _provider_can_try_thinking(provider):
        return provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **kwargs)

    key = _thinking_cache_key(provider, model_name)
    state = _THINKING_SUPPORT.get(key)
    thinking_kwargs = {"thinking": {"type": "enabled"}}
    thinking_kwargs.update(kwargs)  # Merge kwargs with thinking args

    # Known supported
    if state is True:
        response = provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **thinking_kwargs)
        if _is_thinking_param_error(response):
            _THINKING_SUPPORT[key] = False
            fallback = provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **kwargs)
            if isinstance(fallback, dict) and "error" not in fallback:
                return fallback
        return response
    # Known unsupported
    if state is False:
        return provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **kwargs)

    # Unknown: try thinking once, then retry without on failure.
    response = provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **thinking_kwargs)
    if isinstance(response, dict) and "error" not in response:
        _THINKING_SUPPORT[key] = True
        return response

    if _is_thinking_param_error(response):
        _THINKING_SUPPORT[key] = False

    fallback = provider.chat(messages=messages, tools=tools, model=model_name, supports_tools=supports_tools, **kwargs)
    if isinstance(fallback, dict) and "error" not in fallback:
        _THINKING_SUPPORT[key] = False
        return fallback

    # If both failed, leave state unknown so we can retry later.
    return response


def _call_stream_with_auto_thinking(
    *,
    provider: Any,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    model_name: str,
    supports_tools: bool,
    on_chunk: Optional[callable],
    check_interrupt: Optional[callable],
    check_user_messages: Optional[callable],
    **kwargs,
) -> Dict[str, Any]:
    if getattr(config, "LLM_THINKING_MODE", "auto") == "off":
        return provider.chat_stream(
            messages=messages,
            tools=tools,
            model=model_name,
            supports_tools=supports_tools,
            on_chunk=on_chunk,
            check_interrupt=check_interrupt,
            check_user_messages=check_user_messages,
            **kwargs,
        )
    if not _provider_can_try_thinking(provider):
        return provider.chat_stream(
            messages=messages,
            tools=tools,
            model=model_name,
            supports_tools=supports_tools,
            on_chunk=on_chunk,
            check_interrupt=check_interrupt,
            check_user_messages=check_user_messages,
            **kwargs,
        )

    key = _thinking_cache_key(provider, model_name)
    state = _THINKING_SUPPORT.get(key)
    thinking_kwargs = {"thinking": {"type": "enabled"}}
    thinking_kwargs.update(kwargs)

    if state is True:
        response = provider.chat_stream(
            messages=messages,
            tools=tools,
            model=model_name,
            supports_tools=supports_tools,
            on_chunk=on_chunk,
            check_interrupt=check_interrupt,
            check_user_messages=check_user_messages,
            **thinking_kwargs,
        )
        if _is_thinking_param_error(response):
            _THINKING_SUPPORT[key] = False
            fallback = provider.chat_stream(
                messages=messages,
                tools=tools,
                model=model_name,
                supports_tools=supports_tools,
                on_chunk=on_chunk,
                check_interrupt=check_interrupt,
                check_user_messages=check_user_messages,
                **kwargs,
            )
            if isinstance(fallback, dict) and "error" not in fallback:
                return fallback
        return response
    if state is False:
        return provider.chat_stream(
            messages=messages,
            tools=tools,
            model=model_name,
            supports_tools=supports_tools,
            on_chunk=on_chunk,
            check_interrupt=check_interrupt,
            check_user_messages=check_user_messages,
            **kwargs,
        )

    response = provider.chat_stream(
        messages=messages,
        tools=tools,
        model=model_name,
        supports_tools=supports_tools,
        on_chunk=on_chunk,
        check_interrupt=check_interrupt,
        check_user_messages=check_user_messages,
        **thinking_kwargs,
    )
    if isinstance(response, dict) and "error" not in response:
        _THINKING_SUPPORT[key] = True
        return response

    if _is_thinking_param_error(response):
        _THINKING_SUPPORT[key] = False

    fallback = provider.chat_stream(
        messages=messages,
        tools=tools,
        model=model_name,
        supports_tools=supports_tools,
        on_chunk=on_chunk,
        check_interrupt=check_interrupt,
        check_user_messages=check_user_messages,
        **kwargs,
    )
    if isinstance(fallback, dict) and "error" not in fallback:
        _THINKING_SUPPORT[key] = False
        return fallback
    return response

# Retry configuration (can be overridden via environment variables)
def _get_retry_config():
    """Get retry/backoff configuration from environment variables.

    Semantics:
    - OLLAMA_MAX_RETRIES:
        * 0 = retry forever for retryable errors (5xx, timeouts, connection errors)
        * >0 = max attempts (including the first)
    - OLLAMA_RETRY_FOREVER=1 forces retry-forever regardless of OLLAMA_MAX_RETRIES
    """
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

    # If we're not retrying forever, ensure at least 1 attempt
    if not retry_forever:
        max_retries = max(1, max_retries)

    return max_retries, retry_forever, backoff_seconds, max_backoff_seconds, timeout_multiplier_cap



def get_token_usage() -> Dict[str, int]:
    """Return a snapshot of estimated token usage for the current session."""

    return _token_usage_tracker.snapshot()


def reset_token_usage() -> None:
    """Reset the token usage tracker (mainly for tests)."""

    _token_usage_tracker.reset()


# Global flag for interrupt handling
_interrupt_requested = threading.Event()


def _signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C)."""
    _interrupt_requested.set()
    raise KeyboardInterrupt


def _setup_signal_handlers():
    """Setup signal handlers for cross-platform interrupt handling."""
    # Only set up signal handlers in the main thread
    # signal.signal() can only be called from the main thread
    if threading.current_thread() is threading.main_thread():
        # Set up SIGINT handler (Ctrl+C)
        signal.signal(signal.SIGINT, _signal_handler)


def _stringify_content(content: Any) -> str:
    """Convert LLM message content to a string for estimation purposes."""

    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        # Some chat providers support multi-part content; flatten any text fields
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
    """Ollama's /api/chat expects the last message role to be 'user' or 'tool'.

    In multi-turn loops it's easy to end up with the last role == 'assistant', which
    Ollama rejects with a 400. To keep the loop going, we append a tiny user turn.

   Returns: (messages, appended)
    """
    if not messages:
        return messages, False

    last_role = (messages[-1] or {}).get("role")
    if last_role in {"user", "tool"}:
        return messages, False

    fixed = list(messages)
    fixed.append({"role": "user", "content": "Continue."})
    return fixed, True

def _enforce_token_limit(messages: List[Dict[str, Any]], max_tokens: int) -> Tuple[List[Dict[str, Any]], int, int, bool]:
    """Ensure messages stay within the configured token limit.

    Returns the possibly trimmed messages, the estimated tokens before/after,
    and whether any truncation occurred.
    """

    # Add a generous safety margin because the character-per-token heuristic can
    # underestimate usage for shorter tokens. This keeps us well below the
    # provider's hard cap and prevents request failures before they happen.
    effective_max_tokens = int(max_tokens * _TOKEN_BUDGET_MULTIPLIER)

    if max_tokens <= 0:
        return [], 0, 0, True

    original_tokens = sum(_estimate_message_tokens(m) for m in messages)
    if original_tokens <= effective_max_tokens:
        return messages, original_tokens, original_tokens, False

    # Always keep system messages first to preserve instructions
    system_messages = [m for m in messages if m.get("role") == "system"]
    other_messages = [m for m in messages if m.get("role") != "system"]

    truncated_messages: List[Dict[str, Any]] = []
    remaining_tokens = effective_max_tokens
    token_tally = 0
    truncated = False

    # Reserve a small slice of the budget for the most recent non-system
    # messages so we never lose the user's latest intent entirely.
    reserved_recent = max(1, effective_max_tokens // 10)
    system_budget = max(0, effective_max_tokens - reserved_recent)
    remaining_tokens = system_budget

    # Add system messages in order, truncating if needed
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

    # Add most recent non-system messages until budget is exhausted
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

    trimmed_tokens = token_tally
    return truncated_messages, original_tokens, trimmed_tokens, truncated


def _make_request_interruptible(url, json_payload, timeout):
    """
    Make an HTTP request that can be interrupted by Ctrl+C on Windows.

    Uses threading to make the blocking request interruptible by checking
    the interrupt flag periodically.
    """
    result = {"response": None, "error": None}

    def do_request():
        try:
            result["response"] = requests.post(url, json=json_payload, timeout=timeout)
        except Exception as e:
            result["error"] = e

    # Start request in background thread
    request_thread = threading.Thread(target=do_request, daemon=True)
    request_thread.start()

    # Wait for request to complete, checking for interrupts every 0.5 seconds
    while request_thread.is_alive():
        request_thread.join(timeout=0.5)

        # Check if interrupt was requested
        if _interrupt_requested.is_set():
            # Request was cancelled
            raise KeyboardInterrupt("Request cancelled by user (Ctrl+C)")

    # Check if an error occurred in the request thread
    if result["error"]:
        raise result["error"]

    return result["response"]


def ollama_chat(
    messages: List[Dict[str, str]],
    tools: List[Dict] = None,
    model: Optional[str] = None,
    supports_tools: Optional[bool] = None,
    tool_choice: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Send chat request to LLM using the appropriate provider.

    This function now supports multiple providers (Ollama, OpenAI, Anthropic, Gemini)
    and automatically routes to the correct provider based on the model name or
    configuration.

    For backward compatibility, this function defaults to Ollama if no provider
    is specified. The provider can be explicitly set via REV_LLM_PROVIDER env var
    or auto-detected from the model name (e.g., gpt-4 -> OpenAI, claude-3 -> Anthropic).

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        tools: Optional list of tool definitions in OpenAI format
        model: Model name (provider will be auto-detected from name)
        supports_tools: Whether the model supports tool calling
        **kwargs: Additional arguments to pass to the provider (e.g. temperature)

    Returns:
        Dict with 'message' and 'usage' keys, or 'error' key if failed
    """
    # Prefer explicit model, then execution model, then legacy OLLAMA_MODEL
    model_name = model or getattr(config, "EXECUTION_MODEL", None) or config.OLLAMA_MODEL
    supports_tools = config.DEFAULT_SUPPORTS_TOOLS if supports_tools is None else supports_tools

    # DIAGNOSTIC LOGGING
    tools_count_before = len(tools) if tools else 0
    supports_tools_before = supports_tools

    # Always attempt tool-calling when tools are supplied, even if the model is uncertain.
    if tools:
        supports_tools = True

    # CRITICAL FIX: Treat empty list same as None - both mean "no tools provided"
    # This ensures the safety net activates for empty lists too
    if tools is not None and len(tools) == 0:
        tools = None

    # Safety net: if model supports tools but caller passed none/empty, populate with full registry.
    if supports_tools and not tools:
        try:
            from rev.tools.registry import get_available_tools  # local import to avoid circular dependency
            tools = get_available_tools()
            supports_tools = True
        except Exception:
            tools = tools or []

    # DIAGNOSTIC LOGGING
    tools_count_after = len(tools) if tools else 0
    if tools_count_after == 0 and (supports_tools or tools_count_before > 0):
        # print(f"  [LLM_CLIENT] WARNING: Calling LLM with 0 tools! supports_tools_before={supports_tools_before}, supports_tools_after={supports_tools}, tools_count_before={tools_count_before}, tools_count_after={tools_count_after}")
        pass
    elif tools_count_before != tools_count_after:
        # print(f"  [LLM_CLIENT] Tools auto-populated: {tools_count_before} -> {tools_count_after}")
        pass

    # Allow callers to explicitly control tool_choice (e.g., force "required" for write tasks)
    if tool_choice:
        kwargs["tool_choice"] = tool_choice

    # Get cache for checking/storing responses
    llm_cache = get_llm_cache() or LLMResponseCache()
    tools_provided = tools is not None

    debug_logger = get_logger()
    try:
        debug_logger.set_trace_context({
            "llm_provider": config.LLM_PROVIDER,
            "supports_tools": supports_tools,
            "tools_provided": bool(tools),
            "tools_count": len(tools) if tools else 0,
            "tools_names": [t.get("function", {}).get("name") for t in (tools or []) if isinstance(t, dict)],
        })
    except Exception:
        pass
    if getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False):
        try:
            tool_names = [t.get("function", {}).get("name") for t in (tools or []) if isinstance(t, dict)]
            debug_logger.log_llm_transcript(
                model=model_name,
                messages=messages,
                response={"pending": True},
                tools=tools,
                extra={
                    "supports_tools": supports_tools,
                    "tools_count": len(tools) if tools else 0,
                    "tools_provided": bool(tools),
                    "tools_names": tool_names,
                },
            )
        except Exception:
            pass

    # Check cache first (include model in cache key)
    cached_response = llm_cache.get_response(messages, tools if tools_provided else None, model_name)
    if cached_response is not None:
        if OLLAMA_DEBUG:
            print("[DEBUG] Using cached LLM response")
        cached_response.setdefault("usage", _token_usage_tracker.snapshot())
        debug_logger.log_llm_response(model_name, cached_response, cached=True)
        return cached_response

    # Get the appropriate provider for the model
    try:
        # Force provider if user selected one; this prevents auto-detection from
        # falling back to Ollama when model names are ambiguous (e.g., o4-mini).
        override_provider = config.LLM_PROVIDER or None
        provider = get_provider_for_model(model_name, override_provider=override_provider)
        # DEBUG: Log provider selection
        if OLLAMA_DEBUG:
            print(f"[DEBUG] ollama_chat: model={model_name}, provider={provider.__class__.__name__}")
    except ValueError as e:
        return {"error": f"Provider error: {e}"}

    # Make the request through the provider
    response = _call_with_auto_thinking(
        provider=provider,
        messages=messages,
        tools=tools,
        model_name=model_name,
        supports_tools=supports_tools,
        **kwargs
    )

    # Persist full transcript (raw response) when tracing is enabled
    if getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False):
        try:
            debug_logger.log_llm_transcript(model=model_name, messages=messages, response=response, tools=tools)
        except Exception:
            pass

    response = _sanitize_response_content(response)

    # Track token usage if successful
    if "usage" in response and "error" not in response:
        _token_usage_tracker.record(
            response["usage"].get("prompt", 0),
            response["usage"].get("completion", 0)
        )

        # Cache successful response
        llm_cache.set_response(messages, response, tools if tools_provided else None, model_name)

    return response


def ollama_chat_stream(
    messages: List[Dict[str, str]],
    tools: List[Dict] = None,
    model: Optional[str] = None,
    supports_tools: Optional[bool] = None,
    on_chunk: Optional[callable] = None,
    check_interrupt: Optional[callable] = None,
    check_user_messages: Optional[callable] = None,
    **kwargs
) -> Dict[str, Any]:
    """Stream chat responses from LLM with real-time output.

    This function now supports multiple providers (Ollama, OpenAI, Anthropic, Gemini)
    and automatically routes to the correct provider based on the model name or
    configuration.

    Args:
        messages: Chat messages in OpenAI format
        tools: Optional list of tool definitions
        model: Model name (provider will be auto-detected from name)
        supports_tools: Whether the model supports tool calling
        on_chunk: Callback called with each text chunk as it arrives
        check_interrupt: Callback to check if execution should be interrupted
        check_user_messages: Callback to check for and inject user messages
        **kwargs: Additional arguments to pass to the provider (e.g. temperature)

    Returns:
        Complete response dict (same format as ollama_chat)
    """
    model_name = model or config.OLLAMA_MODEL
    supports_tools = config.DEFAULT_SUPPORTS_TOOLS if supports_tools is None else supports_tools

    # Get the appropriate provider for the model
    try:
        # If the primary provider is ollama, we route everything to it to avoid
        # warnings about missing API keys for auto-detected cloud models.
        override_provider = None
        if config.LLM_PROVIDER == "ollama":
            override_provider = "ollama"
        elif config.LLM_PROVIDER not in {"gemini", "openai", "anthropic"}:
            override_provider = config.LLM_PROVIDER

        provider = get_provider_for_model(model_name, override_provider=override_provider)
    except ValueError as e:
        return {"error": f"Provider error: {e}"}

    response = _call_stream_with_auto_thinking(
        provider=provider,
        messages=messages,
        tools=tools,
        model_name=model_name,
        supports_tools=supports_tools,
        on_chunk=on_chunk,
        check_interrupt=check_interrupt,
        check_user_messages=check_user_messages,
        **kwargs
    )
    response = _sanitize_response_content(response)

    # Track token usage if successful
    if "usage" in response and "error" not in response:
        _token_usage_tracker.record(
            response["usage"].get("prompt", 0),
            response["usage"].get("completion", 0)
        )

    return response
