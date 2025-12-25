import asyncio
import os
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
            self.on_startup = []
            self.on_cleanup = []

    monkeypatch.setattr(api_mod, "AIOHTTP_AVAILABLE", True)
    monkeypatch.setattr(api_mod, "web", SimpleNamespace(Application=DummyApp))
    monkeypatch.setattr(api_mod.rev_config, "EXECUTION_MODE", "linear")
    monkeypatch.setenv("REV_EXECUTION_MODE", "linear")

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
    assert captured["config"].context_guard_interactive is False
    assert api_mod.rev_config.EXECUTION_MODE == "sub-agent"
    assert os.environ["REV_EXECUTION_MODE"] == "sub-agent"


def test_lsp_server_get_orchestrator_uses_project_root(monkeypatch) -> None:
    class DummyLanguageServer:
        def __init__(self, _name, _version):
            return None

    monkeypatch.setattr(lsp_mod, "LSP_AVAILABLE", True)
    monkeypatch.setattr(lsp_mod, "LanguageServer", DummyLanguageServer)
    monkeypatch.setattr(lsp_mod.RevLSPServer, "_setup_handlers", lambda self: None)
    monkeypatch.setattr(lsp_mod.rev_config, "EXECUTION_MODE", "linear")
    monkeypatch.setenv("REV_EXECUTION_MODE", "linear")

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
    assert captured["config"].context_guard_interactive is False
    assert lsp_mod.rev_config.EXECUTION_MODE == "sub-agent"
    assert os.environ["REV_EXECUTION_MODE"] == "sub-agent"
