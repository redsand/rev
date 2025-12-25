import asyncio
from pathlib import Path
from types import SimpleNamespace

from rev.ide import api_server as api_mod
from rev.ide import lsp_server as lsp_mod


def test_api_server_get_orchestrator_uses_project_root(monkeypatch) -> None:
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

    monkeypatch.setattr(api_mod, "AIOHTTP_AVAILABLE", True)
    monkeypatch.setattr(api_mod, "web", SimpleNamespace(Application=DummyApp))

    captured = {}

    class DummyOrchestrator:
        def __init__(self, project_root, config=None):
            captured["project_root"] = project_root
            captured["config"] = config

    monkeypatch.setattr(api_mod, "Orchestrator", DummyOrchestrator)

    server = api_mod.RevAPIServer(config=api_mod.rev_config)
    orchestrator = asyncio.run(server._get_orchestrator())

    assert isinstance(orchestrator, DummyOrchestrator)
    assert captured["project_root"] == Path.cwd()


def test_lsp_server_get_orchestrator_uses_project_root(monkeypatch) -> None:
    class DummyLanguageServer:
        def __init__(self, _name, _version):
            return None

    monkeypatch.setattr(lsp_mod, "LSP_AVAILABLE", True)
    monkeypatch.setattr(lsp_mod, "LanguageServer", DummyLanguageServer)
    monkeypatch.setattr(lsp_mod.RevLSPServer, "_setup_handlers", lambda self: None)

    captured = {}

    class DummyOrchestrator:
        def __init__(self, project_root, config=None):
            captured["project_root"] = project_root
            captured["config"] = config

    monkeypatch.setattr(lsp_mod, "Orchestrator", DummyOrchestrator)

    server = lsp_mod.RevLSPServer(config=lsp_mod.rev_config)
    orchestrator = asyncio.run(server._get_orchestrator())

    assert isinstance(orchestrator, DummyOrchestrator)
    assert captured["project_root"] == Path.cwd()
