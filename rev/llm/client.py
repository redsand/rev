#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM (Language Model) client for rev using Ollama."""

import os
import json
import signal
import threading
from typing import Dict, Any, List, Optional

import requests

from rev import config
from rev.cache import get_llm_cache


# Debug mode - set to True to see API requests/responses
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"


# Global flag for interrupt handling
_interrupt_requested = threading.Event()


def _signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C)."""
    _interrupt_requested.set()
    raise KeyboardInterrupt


def _setup_signal_handlers():
    """Setup signal handlers for cross-platform interrupt handling."""
    # Set up SIGINT handler (Ctrl+C)
    signal.signal(signal.SIGINT, _signal_handler)


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


def ollama_chat(messages: List[Dict[str, str]], tools: List[Dict] = None) -> Dict[str, Any]:
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

    # Get the LLM cache
    llm_cache = get_llm_cache()

    # Try to get cached response first
    cached_response = llm_cache.get_response(messages, tools)
    if cached_response is not None:
        if OLLAMA_DEBUG:
            print("[DEBUG] Using cached LLM response")
        return cached_response

    # All models (including cloud models) use the local Ollama instance
    # The local Ollama instance automatically proxies cloud model requests
    base_url = config.OLLAMA_BASE_URL
    url = f"{base_url}/api/chat"

    # Notify user if using a cloud model
    is_cloud_model = config.OLLAMA_MODEL.endswith("-cloud")
    if is_cloud_model and (OLLAMA_DEBUG or not hasattr(ollama_chat, '_cloud_model_notified')):
        print(f"ℹ️  Using cloud model: {config.OLLAMA_MODEL} (proxied through local Ollama)")
        ollama_chat._cloud_model_notified = True

    # Build base payload
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False
    }

    # Try with tools first if provided
    if tools:
        payload["tools"] = tools

    if OLLAMA_DEBUG:
        print(f"[DEBUG] Ollama request to {url}")
        print(f"[DEBUG] Model: {config.OLLAMA_MODEL}")
        print(f"[DEBUG] Messages: {json.dumps(messages, indent=2)}")
        if tools:
            print(f"[DEBUG] Tools: {len(tools)} tools provided")

    # Retry with increasing timeouts: 10m, 20m, 30m
    max_retries = 3
    base_timeout = 600  # 10 minutes

    # Track if we've already prompted for auth in this call
    auth_prompted = False

    for attempt in range(max_retries):
        timeout = base_timeout * (attempt + 1)  # 600, 1200, 1800

        if OLLAMA_DEBUG and attempt > 0:
            print(f"[DEBUG] Retry attempt {attempt + 1}/{max_retries} with timeout {timeout}s ({timeout // 60}m)")

        try:
            resp = _make_request_interruptible(url, payload, timeout)

            if OLLAMA_DEBUG:
                print(f"[DEBUG] Response status: {resp.status_code}")
                print(f"[DEBUG] Response: {resp.text[:500]}")

            # Handle 401 Unauthorized for cloud models
            if resp.status_code == 401:
                try:
                    error_data = resp.json()
                    signin_url = error_data.get("signin_url")

                    if signin_url and not auth_prompted:
                        auth_prompted = True
                        print("\n" + "=" * 60)
                        print("OLLAMA CLOUD AUTHENTICATION REQUIRED")
                        print("=" * 60)
                        print(f"\nModel '{config.OLLAMA_MODEL}' requires authentication.")
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
                            return {"error": "Authentication cancelled by user"}

                        # Retry the request after authentication
                        print("\nRetrying request...")
                        continue
                    else:
                        # If we've already prompted or no signin_url, return error
                        return {"error": f"Ollama API error: {resp.status_code} {resp.reason} - {resp.text}"}

                except json.JSONDecodeError:
                    return {"error": f"Ollama API error: {resp.status_code} {resp.reason}"}

            # If we get a 400 and we sent tools, try again without tools
            if resp.status_code == 400 and tools:
                if OLLAMA_DEBUG:
                    print("[DEBUG] Got 400 with tools, retrying without tools...")

                # Retry without tools
                payload_no_tools = {
                    "model": config.OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False
                }
                resp = _make_request_interruptible(url, payload_no_tools, timeout)

            resp.raise_for_status()
            response = resp.json()

            # Cache the successful response
            llm_cache.set_response(messages, response, tools)

            return response

        except KeyboardInterrupt:
            # Don't catch keyboard interrupts - let them propagate
            print("\n\nRequest cancelled by user (Ctrl+C)")
            raise

        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Request timed out after {timeout}s, will retry with longer timeout...")
                continue  # Retry with longer timeout
            else:
                return {"error": f"Ollama API timeout after {max_retries} attempts (final timeout: {timeout}s)"}

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = f" - {resp.text}"
            except:
                pass
            return {"error": f"Ollama API error: {e}{error_detail}"}

        except Exception as e:
            return {"error": f"Ollama API error: {e}"}
