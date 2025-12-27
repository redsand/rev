import json
from types import SimpleNamespace

from rev.ide import api_server as api_mod


def test_handle_analyze_clones_request(monkeypatch):
    class DummyRouter:
        def add_post(self, *_args, **_kwargs):
            return None

        def add_get(self, *_args, **_kwargs):
            return None

        def add_delete(self, *_args, **_kwargs):
            return None

    class DummyApp:
        def __init__(self):
            self.router = DummyRouter()
            self.on_startup = []
            self.on_cleanup = []

    class DummyRequest:
        def __init__(self, payload):
            self._read_bytes = None
            self._payload = payload

        async def json(self):
            return self._payload

        def clone(self):
            return DummyRequest(self._payload)

    monkeypatch.setattr(api_mod, "AIOHTTP_AVAILABLE", True)
    monkeypatch.setattr(api_mod, "web", SimpleNamespace(Application=DummyApp))

    server = api_mod.RevAPIServer(config=api_mod.rev_config)

    captured = {}

    async def fake_submit(task, task_id=None):
        captured["task"] = task
        return {"status": "ok"}

    monkeypatch.setattr(server, "_submit_task", fake_submit)

    request = DummyRequest({"file_path": "src/app.py"})
    result = api_mod.asyncio.run(server.handle_analyze(request))

    assert result["status"] == "ok"
    assert "Analyze the code in src/app.py" in captured["task"]
