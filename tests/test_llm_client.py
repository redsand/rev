"""Tests for the Ollama client retry and backoff behavior."""

from unittest.mock import Mock, patch

import rev.llm.client as client


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
