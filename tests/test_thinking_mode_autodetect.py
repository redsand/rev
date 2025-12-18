import rev.llm.client as llm_client


class _NoCache:
    def get_response(self, *args, **kwargs):
        return None

    def set_response(self, *args, **kwargs):
        return None


class _DummyOpenAIProvider:
    name = "openai"

    def __init__(self, supports_thinking: bool):
        self.supports_thinking = supports_thinking
        self.calls = []

    def chat(self, messages, tools=None, model=None, supports_tools=True, **kwargs):
        self.calls.append(("chat", dict(kwargs)))
        if "thinking" in kwargs and not self.supports_thinking:
            return {"error": "unknown field: thinking"}
        return {
            "message": {"role": "assistant", "content": "<think>secret</think>\nfinal"},
            "done": True,
            "usage": {"prompt": 1, "completion": 1, "total": 2},
        }

    def chat_stream(self, messages, tools=None, model=None, supports_tools=True, on_chunk=None, **kwargs):
        self.calls.append(("stream", dict(kwargs)))
        if "thinking" in kwargs and not self.supports_thinking:
            return {"error": "unknown field: thinking"}
        if on_chunk:
            on_chunk("<think>secret</think>\nfinal")
        return {
            "message": {"role": "assistant", "content": "<think>secret</think>\nfinal"},
            "done": True,
            "usage": {"prompt": 1, "completion": 1, "total": 2},
        }


def test_thinking_autodetect_disables_on_failure(monkeypatch):
    llm_client.reset_thinking_capabilities()
    monkeypatch.setattr(llm_client, "get_llm_cache", lambda: _NoCache())

    provider = _DummyOpenAIProvider(supports_thinking=False)
    monkeypatch.setattr(llm_client, "get_provider_for_model", lambda model: provider)

    old_mode = llm_client.config.LLM_THINKING_MODE
    try:
        llm_client.config.LLM_THINKING_MODE = "auto"
        messages = [{"role": "user", "content": "hi"}]

        resp1 = llm_client.ollama_chat(messages, model="deepseek-reasoner", tools=None, supports_tools=False)
        assert "error" not in resp1
        assert resp1["message"]["content"].strip() == "final"
        # First call: try with thinking, then fallback without thinking
        assert len(provider.calls) == 2
        assert "thinking" in provider.calls[0][1]
        assert "thinking" not in provider.calls[1][1]

        provider.calls.clear()
        resp2 = llm_client.ollama_chat(messages, model="deepseek-reasoner", tools=None, supports_tools=False)
        assert "error" not in resp2
        assert resp2["message"]["content"].strip() == "final"
        # Subsequent call should skip thinking
        assert len(provider.calls) == 1
        assert "thinking" not in provider.calls[0][1]
    finally:
        llm_client.config.LLM_THINKING_MODE = old_mode


def test_thinking_autodetect_keeps_enabled_on_success(monkeypatch):
    llm_client.reset_thinking_capabilities()
    monkeypatch.setattr(llm_client, "get_llm_cache", lambda: _NoCache())

    provider = _DummyOpenAIProvider(supports_thinking=True)
    monkeypatch.setattr(llm_client, "get_provider_for_model", lambda model: provider)

    old_mode = llm_client.config.LLM_THINKING_MODE
    try:
        llm_client.config.LLM_THINKING_MODE = "auto"
        messages = [{"role": "user", "content": "hi"}]

        resp1 = llm_client.ollama_chat(messages, model="deepseek-reasoner", tools=None, supports_tools=False)
        assert "error" not in resp1
        assert resp1["message"]["content"].strip() == "final"
        assert len(provider.calls) == 1
        assert "thinking" in provider.calls[0][1]

        provider.calls.clear()
        resp2 = llm_client.ollama_chat(messages, model="deepseek-reasoner", tools=None, supports_tools=False)
        assert "error" not in resp2
        assert resp2["message"]["content"].strip() == "final"
        assert len(provider.calls) == 1
        assert "thinking" in provider.calls[0][1]
    finally:
        llm_client.config.LLM_THINKING_MODE = old_mode

