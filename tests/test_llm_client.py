"""Tests for the Ollama client token safeguards and retry behavior."""

import os
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import rev.llm.client as client
from rev.llm.client import (
    _CHARS_PER_TOKEN_ESTIMATE,
    _enforce_token_limit,
    get_token_usage,
    reset_token_usage,
)


def _make_response(status_code, payload=None, text="", reason="Server Error"):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.reason = reason
    response.json.return_value = payload or {}

    def raise_for_status():
        if status_code >= 400:
            raise client.requests.exceptions.HTTPError(f"{status_code} error")

    response.raise_for_status = raise_for_status
    return response


def test_enforce_token_limit_truncates_and_preserves_system_message():
    # 200 characters is roughly 67 tokens with the 3 chars/token heuristic
    system_message = {"role": "system", "content": "s" * 200}
    user_message = {"role": "user", "content": "u" * 200}
    assistant_message = {"role": "assistant", "content": "a" * 200}

    # Limit to 60 tokens (~240 characters) so trimming is required after system message
    trimmed, original_tokens, trimmed_tokens, truncated = _enforce_token_limit(
        [system_message, user_message, assistant_message],
        max_tokens=60,
    )

    assert truncated is True
    assert trimmed[0]["role"] == "system"
    assert len(trimmed) == 2  # System + most recent non-system message
    assert "truncated to fit token limit" in trimmed[1]["content"]
    assert trimmed_tokens <= int(60 * client._TOKEN_BUDGET_MULTIPLIER)


def test_enforce_token_limit_keeps_messages_when_under_budget():
    messages = [
        {"role": "system", "content": "Keep me"},
        {"role": "user", "content": "short"},
    ]

    trimmed, original_tokens, trimmed_tokens, truncated = _enforce_token_limit(
        messages,
        max_tokens=1_000 // _CHARS_PER_TOKEN_ESTIMATE,
    )

    assert truncated is False
    assert trimmed == messages
    assert original_tokens == trimmed_tokens


@patch("rev.llm.client.requests.post")
def test_records_token_usage_on_success(mock_post):
    reset_token_usage()

    messages = [{"role": "user", "content": "hello world"}]
    mock_post.return_value = _make_response(
        200, payload={"message": {"content": "short reply", "tool_calls": []}}
    )

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    result = client.ollama_chat(messages)

    usage = get_token_usage()
    assert usage["prompt"] > 0
    assert usage["completion"] > 0
    assert usage["total"] == usage["prompt"] + usage["completion"]
    assert result["usage"]["total"] == usage["total"]


@patch("rev.llm.client.time.sleep")
def test_retries_server_errors_with_backoff(mock_sleep, monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "5")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_SECONDS", "0.1")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_MAX_SECONDS", "1")

    messages = [{"role": "user", "content": "retry server error"}]
    responses = [
        _make_response(500, text="internal error"),
        _make_response(502, text="bad gateway"),
        _make_response(200, payload={"message": {"content": "ok", "tool_calls": []}}),
    ]

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    with patch("rev.llm.client.requests.post", side_effect=responses) as mock_post:
        result = client.ollama_chat(messages)

    assert result["message"]["content"] == "ok"
    assert mock_post.call_count == 3
    assert mock_sleep.call_count >= 2


@patch("rev.llm.client.time.sleep")
def test_returns_error_after_exhausting_retries(mock_sleep, monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "4")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_SECONDS", "0.05")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_MAX_SECONDS", "0.1")

    messages = [{"role": "user", "content": "retry exhaustion"}]
    responses = [_make_response(500, text="fail")] * 4

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    with patch("rev.llm.client.requests.post", side_effect=responses) as mock_post:
        result = client.ollama_chat(messages)

    assert "error" in result
    assert mock_post.call_count == 4
    assert mock_sleep.call_count == 3


@patch("rev.llm.client.requests.post")
def test_sends_tools_in_standard_format(mock_post):
    """Test that tools are sent in OpenAI-compatible format (not 'mode: tools')."""
    messages = [{"role": "user", "content": "test"}]
    mock_post.return_value = _make_response(
        200,
        payload={"message": {"content": "ok", "tool_calls": []}},
    )

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    result = client.ollama_chat(messages, tools=[])

    assert result["message"]["content"] == "ok"
    assert mock_post.call_count == 1

    payload = mock_post.call_args.kwargs["json"]
    # CRITICAL: Should use standard OpenAI format, not "mode": "tools"
    assert "mode" not in payload, "Should not use non-standard 'mode' parameter"
    assert payload["tools"] == []


@patch("rev.llm.client.time.sleep")
@patch("rev.llm.client.requests.post")
def test_max_retries_zero_still_makes_a_call(mock_post, mock_sleep, monkeypatch):
    """When OLLAMA_MAX_RETRIES=0, we still make at least one attempt and return a response."""
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "0")
    monkeypatch.delenv("OLLAMA_RETRY_FOREVER", raising=False)

    messages = [{"role": "user", "content": "hello"}]
    mock_post.return_value = _make_response(
        200, payload={"message": {"content": "ok", "tool_calls": []}}
    )

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    result = client.ollama_chat(messages)

    assert result["message"]["content"] == "ok"
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()


@patch("rev.llm.client.time.sleep")
def test_retry_forever_retries_retryable_errors_until_success(mock_sleep, monkeypatch):
    """With retry_forever enabled, retryable HTTP 5xx errors keep retrying until success."""
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "0")
    monkeypatch.setenv("OLLAMA_RETRY_FOREVER", "1")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_MAX_SECONDS", "0.02")

    messages = [{"role": "user", "content": "keep trying"}]
    responses = [
        _make_response(500, text="fail"),
        _make_response(502, text="fail again"),
        _make_response(200, payload={"message": {"content": "ok", "tool_calls": []}}),
    ]

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    with patch("rev.llm.client.requests.post", side_effect=responses) as mock_post:
        result = client.ollama_chat(messages)

    assert result["message"]["content"] == "ok"
    assert mock_post.call_count == 3
    assert mock_sleep.call_count >= 2


@patch("rev.llm.client.time.sleep")
def test_retry_forever_does_not_spin_on_non_retryable(mock_sleep, monkeypatch):
    """retry_forever should not loop forever on non-retryable (e.g., 400) errors."""
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "0")
    monkeypatch.setenv("OLLAMA_RETRY_FOREVER", "1")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("OLLAMA_RETRY_BACKOFF_MAX_SECONDS", "0.02")

    messages = [{"role": "user", "content": "bad request"}]
    responses = [_make_response(400, text="bad request")]

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    with patch("rev.llm.client.requests.post", side_effect=responses) as mock_post:
        result = client.ollama_chat(messages)

    assert "error" in result
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()


@patch("rev.llm.client.requests.post")
def test_ollama_chat_passes_temperature(mock_post):
    messages = [{"role": "user", "content": "test temp"}]
    mock_post.return_value = _make_response(
        200,
        payload={"message": {"content": "ok", "tool_calls": []}},
    )

    cache = client.get_llm_cache()
    if cache:
        cache.clear()

    # Pass temperature
    result = client.ollama_chat(messages, temperature=0.5)

    assert result["message"]["content"] == "ok"
    assert mock_post.call_count == 1

    payload = mock_post.call_args.kwargs["json"]
    assert payload["options"]["temperature"] == 0.5
