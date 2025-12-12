#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM (Language Model) client for rev using Ollama."""

import os
import json
import signal
import threading
import time
import random
from typing import Dict, Any, List, Optional, Tuple

import requests

from rev import config
from rev.cache import LLMResponseCache, get_llm_cache
from rev.debug_logger import get_logger


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
) -> Dict[str, Any]:
    """Send chat request to Ollama.

    Note: Ollama's tool/function calling support varies by model and version.
    This implementation sends tools in OpenAI format but gracefully falls back
    if the model doesn't support them.

    For cloud models (ending with -cloud), this handles authentication flow.
    """
    # Setup signal handlers for interrupt handling
    _setup_signal_handlers()

    # Clear any previous interrupt flags
    _interrupt_requested.clear()

    # Enforce token limits to avoid exceeding provider constraints
    trimmed_messages, original_tokens, trimmed_tokens, was_truncated = _enforce_token_limit(
        messages,
        config.MAX_LLM_TOKENS_PER_RUN,
    )

    prompt_tokens_estimate = trimmed_tokens

    if was_truncated:
        print(
            f"⚠️  Context trimmed from ~{original_tokens:,} to ~{trimmed_tokens:,} tokens "
            f"(limit {config.MAX_LLM_TOKENS_PER_RUN:,})."
        )

    messages = trimmed_messages
    messages, _appended_continue = _ensure_last_user_or_tool(messages)

    model_name = model or config.OLLAMA_MODEL
    supports_tools = config.DEFAULT_SUPPORTS_TOOLS if supports_tools is None else supports_tools

    # Get the LLM cache
    llm_cache = get_llm_cache() or LLMResponseCache()

    tools_provided = tools is not None and supports_tools

    # Try to get cached response first (include model in cache key)
    cached_response = llm_cache.get_response(messages, tools if tools_provided else None, model_name)
    if cached_response is not None:
        if OLLAMA_DEBUG:
            print("[DEBUG] Using cached LLM response")

        cached_response.setdefault("usage", _token_usage_tracker.snapshot())

        # Log cache hit
        debug_logger = get_logger()
        debug_logger.log_llm_response(model_name, cached_response, cached=True)

        return cached_response

    # All models (including cloud models) use the local Ollama instance
    # The local Ollama instance automatically proxies cloud model requests
    base_url = config.OLLAMA_BASE_URL
    url = f"{base_url}/api/chat"

    # Notify user if using a cloud model
    is_cloud_model = model_name.endswith("-cloud")
    if is_cloud_model and (OLLAMA_DEBUG or not hasattr(ollama_chat, '_cloud_model_notified')):
        print(f"ℹ️  Using cloud model: {model_name} (proxied through local Ollama)")
        ollama_chat._cloud_model_notified = True

    # Build base payload
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False
    }

    # Try with tools first if provided (including an empty array to force tools mode)
    if tools_provided:
        payload["mode"] = "tools"
        payload["tools"] = tools or []

    # Log the LLM request
    debug_logger = get_logger()
    debug_logger.log_llm_request(model_name, messages, tools if tools_provided else None)

    if OLLAMA_DEBUG:
        print(f"[DEBUG] Ollama request to {url}")
        print(f"[DEBUG] Model: {model_name}")
        print(f"[DEBUG] Messages: {json.dumps(messages, indent=2)}")
        if tools_provided:
            print(f"[DEBUG] Tools: {len(tools or [])} tools provided")
        elif tools is not None and not supports_tools:
            print(f"[DEBUG] Tools suppressed (supports_tools=False) for model {model_name}")

    # Retry with configurable limits and backoff
    max_retries, retry_forever, retry_backoff, max_backoff, timeout_cap = _get_retry_config()
    base_timeout = 600  # 10 minutes

    # Track if we've already prompted for auth in this call
    auth_prompted = False

    def _sleep_before_retry(reason: str):
        """Sleep with capped backoff before a retry attempt."""
        delay = min(max_backoff, retry_backoff * (attempt + 1))
        if delay > 0:
            debug_logger.log("llm", "LLM_RETRY_DELAY", {
                "reason": reason,
                "attempt": attempt + 1,
                "delay_seconds": delay,
            }, "INFO")
            if OLLAMA_DEBUG:
                print(f"[DEBUG] Sleeping {delay}s before retry ({reason})...")
            time.sleep(delay)
        return delay

    for attempt in range(max_retries):
        timeout = base_timeout * min(attempt + 1, timeout_cap)  # 600, 1200, 1800 (capped)

        if attempt > 0:
            debug_logger.log("llm", "LLM_RETRY", {
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "timeout_seconds": timeout,
                "timeout_minutes": timeout // 60
            }, "INFO")

        if OLLAMA_DEBUG and attempt > 0:
            print(f"[DEBUG] Retry attempt {attempt + 1}/{max_retries} with timeout {timeout}s ({timeout // 60}m)")

        try:
            resp = _make_request_interruptible(url, payload, timeout)

            if OLLAMA_DEBUG:
                print(f"[DEBUG] Response status: {resp.status_code}")
                print(f"[DEBUG] Response: {resp.text[:500]}")

            # Handle 401 Unauthorized for cloud models
            if resp.status_code == 401:
                debug_logger.log("llm", "AUTH_REQUIRED", {
                    "status_code": 401,
                    "model": model_name
                }, "WARNING")

                try:
                    error_data = resp.json()
                    signin_url = error_data.get("signin_url")

                    if signin_url and not auth_prompted:
                        auth_prompted = True
                        debug_logger.log("llm", "AUTH_PROMPT", {
                            "signin_url": signin_url
                        }, "INFO")

                        print("\n" + "=" * 60)
                        print("OLLAMA CLOUD AUTHENTICATION REQUIRED")
                        print("=" * 60)
                        print(f"\nModel '{model_name}' requires authentication.")
                        print(f"\nTo authenticate:")
                        print(f"1. Visit this URL in your browser:")
                        print(f"   {signin_url}")
                        print(f"\n2. Sign in with your Ollama account")
                        print(f"3. Authorize this device")
                        print("\n" + "=" * 60)

                        # Wait for user to authenticate
                        try:
                            input("\nPress Enter after completing authentication, or Ctrl+C to cancel...")
                        except KeyboardInterrupt:
                            debug_logger.log("llm", "AUTH_CANCELLED", {}, "WARNING")
                            return {"error": "Authentication cancelled by user"}

                        # Retry the request after authentication
                        print("\nRetrying request...")
                        debug_logger.log("llm", "AUTH_RETRY", {}, "INFO")
                        continue
                    else:
                        # If we've already prompted or no signin_url, return error
                        return {"error": f"Ollama API error: {resp.status_code} {resp.reason} - {resp.text}"}

                except json.JSONDecodeError:
                    return {"error": f"Ollama API error: {resp.status_code} {resp.reason}"}

            # If we get a 400 and we sent tools, try again without tools
            if resp.status_code == 400 and tools_provided:
                if OLLAMA_DEBUG:
                    print("[DEBUG] Got 400 with tools, retrying without tools...")

                # Retry without tools
                payload_no_tools = {
                    "model": model_name,
                    "messages": messages,
                    "stream": False
                }
                resp = _make_request_interruptible(url, payload_no_tools, timeout)

            resp.raise_for_status()
            response = resp.json()

            completion_tokens = _estimate_message_tokens(response.get("message", {}))
            _token_usage_tracker.record(prompt_tokens_estimate, completion_tokens)
            response["usage"] = {
                "prompt": prompt_tokens_estimate,
                "completion": completion_tokens,
                "total": prompt_tokens_estimate + completion_tokens,
            }

            # Log successful response
            debug_logger.log_llm_response(model_name, response, cached=False)

            # Cache the successful response (include model in cache key)
            llm_cache.set_response(messages, response, tools if tools_provided else None, model_name)

            return response

        except KeyboardInterrupt:
            # Don't catch keyboard interrupts - let them propagate
            debug_logger.log("llm", "REQUEST_CANCELLED", {}, "WARNING")
            print("\n\nRequest cancelled by user (Ctrl+C)")
            raise

        except requests.exceptions.Timeout as e:
            debug_logger.log("llm", "TIMEOUT", {
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "timeout_seconds": timeout,
                "will_retry": attempt < max_retries - 1
            }, "WARNING")

            if attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Request timed out after {timeout}s, will retry with longer timeout...")
                _sleep_before_retry("timeout")
                continue  # Retry with longer timeout
            else:
                error_msg = f"Ollama API timeout after {max_retries} attempts (final timeout: {timeout}s)"
                debug_logger.log("llm", "TIMEOUT_FINAL", {"error": error_msg}, "ERROR")
                return {"error": error_msg}

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = f" - {resp.text}"
            except Exception:
                pass  # resp.text may not be available

            # Log HTTP error
            debug_logger.log("llm", "HTTP_ERROR", {
                "status_code": resp.status_code if 'resp' in locals() else None,
                "error": str(e),
                "error_detail": error_detail[:200],
                "attempt": attempt + 1,
                "will_retry": resp.status_code >= 500 and attempt < max_retries - 1 if 'resp' in locals() else False
            }, "ERROR")

            # For retryable HTTP errors (5xx server errors), continue to retry
            if 'resp' in locals() and resp.status_code >= 500 and attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] HTTP {resp.status_code} error, will retry (attempt {attempt + 1}/{max_retries})...")
                _sleep_before_retry("http_error")
                continue

            # For non-retryable errors or final attempt, return the error
            return {"error": f"Ollama API error: {e}{error_detail}"}

        except requests.exceptions.RequestException as e:
            # Log request exception
            debug_logger.log("llm", "REQUEST_EXCEPTION", {
                "error": str(e),
                "error_type": type(e).__name__,
                "attempt": attempt + 1,
                "will_retry": attempt < max_retries - 1
            }, "ERROR")

            # Network-related errors (connection errors, etc.) should be retried
            if attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Request error: {e}, will retry (attempt {attempt + 1}/{max_retries})...")
                _sleep_before_retry("request_exception")
                continue
            return {"error": f"Ollama API error: {e}"}

        except Exception as e:
            # Log unexpected error
            debug_logger.log("llm", "UNEXPECTED_ERROR", {
                "error": str(e),
                "error_type": type(e).__name__
            }, "ERROR")

            # For unexpected errors, don't retry
            return {"error": f"Ollama API error: {e}"}
