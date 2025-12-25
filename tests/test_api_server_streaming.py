from types import SimpleNamespace

from rev.ide import api_server as api_mod


def test_api_server_stream_output_broadcast(monkeypatch) -> None:
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

    monkeypatch.setattr(api_mod, "AIOHTTP_AVAILABLE", True)
    monkeypatch.setattr(api_mod, "web", SimpleNamespace(Application=DummyApp))

    server = api_mod.RevAPIServer(config=api_mod.rev_config)

    captured = {}

    def fake_schedule(payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(server, "_schedule_ws_broadcast", fake_schedule)

    server._handle_stream_output("stdout", "hello")

    assert captured["payload"]["type"] == "log"
    assert captured["payload"]["stream"] == "stdout"
    assert captured["payload"]["message"] == "hello"
