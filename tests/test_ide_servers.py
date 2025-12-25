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


def test_api_server_sets_workspace_from_cwd(monkeypatch) -> None:
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

    called = {}

    def fake_set_workspace_root(path, allow_external=False):
        called["root"] = path
        called["allow_external"] = allow_external

    def fake_chdir(path):
        called["cwd"] = path

    monkeypatch.setattr(api_mod.rev_config, "set_workspace_root", fake_set_workspace_root)
    monkeypatch.setattr(api_mod.os, "chdir", fake_chdir)

    server = api_mod.RevAPIServer(config=api_mod.rev_config)
    server.orchestrator = object()
    server._workspace_root = None
    root = Path.cwd().resolve()
    server._maybe_set_workspace(str(root), None)

    assert called["root"] == root
    assert called["allow_external"] is True
    assert called["cwd"] == str(root)
    assert server.orchestrator is None


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
    server._workspace_root = None
    orchestrator = asyncio.run(server._get_orchestrator())

    assert isinstance(orchestrator, DummyOrchestrator)
    assert captured["project_root"] == Path.cwd()
    assert captured["config"].context_guard_interactive is False
    assert lsp_mod.rev_config.EXECUTION_MODE == "sub-agent"
    assert os.environ["REV_EXECUTION_MODE"] == "sub-agent"


def test_lsp_server_sets_workspace_from_file(monkeypatch) -> None:
    class DummyLanguageServer:
        def __init__(self, _name, _version):
            return None

    monkeypatch.setattr(lsp_mod, "LSP_AVAILABLE", True)
    monkeypatch.setattr(lsp_mod, "LanguageServer", DummyLanguageServer)
    monkeypatch.setattr(lsp_mod.RevLSPServer, "_setup_handlers", lambda self: None)

    called = {}

    def fake_set_workspace_root(path, allow_external=False):
        called["root"] = path
        called["allow_external"] = allow_external

    def fake_chdir(path):
        called["cwd"] = path

    monkeypatch.setattr(lsp_mod.rev_config, "set_workspace_root", fake_set_workspace_root)
    monkeypatch.setattr(lsp_mod.os, "chdir", fake_chdir)

    server = lsp_mod.RevLSPServer(config=lsp_mod.rev_config)
    server._workspace_root = None
    root = Path.cwd().resolve()
    file_path = root / "app.py"
    server._maybe_set_workspace(str(file_path))

    assert called["root"] == root
    assert called["allow_external"] is True
    assert called["cwd"] == str(root)
    assert server.orchestrator is None


def test_api_server_request_shutdown_cancels_tasks(monkeypatch) -> None:
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

    called = {}

    def fake_interrupt(value: bool):
        called["interrupt"] = value

    monkeypatch.setattr("rev.config.set_escape_interrupt", fake_interrupt)

    server = api_mod.RevAPIServer(config=api_mod.rev_config)

    class DummyTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    dummy = DummyTask()
    server.active_tasks["task_1"] = {"status": "running"}
    server._task_futures["task_1"] = dummy

    server._request_shutdown("test")

    assert called["interrupt"] is True
    assert server.active_tasks["task_1"]["status"] == "cancelled"
    assert dummy.cancelled is True


def test_lsp_server_request_shutdown_cancels_tasks(monkeypatch) -> None:
    class DummyLanguageServer:
        def __init__(self, _name, _version):
            self.shutdown_called = False
            self.stop_called = False

        def shutdown(self):
            self.shutdown_called = True

        def stop(self):
            self.stop_called = True

    monkeypatch.setattr(lsp_mod, "LSP_AVAILABLE", True)
    monkeypatch.setattr(lsp_mod, "LanguageServer", DummyLanguageServer)
    monkeypatch.setattr(lsp_mod.RevLSPServer, "_setup_handlers", lambda self: None)

    called = {}

    def fake_interrupt(value: bool):
        called["interrupt"] = value

    monkeypatch.setattr("rev.config.set_escape_interrupt", fake_interrupt)

    server = lsp_mod.RevLSPServer(config=lsp_mod.rev_config)

    class DummyTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    dummy = DummyTask()
    server._running_tasks.add(dummy)

    server._request_shutdown("test")

    assert called["interrupt"] is True
    assert dummy.cancelled is True
    assert server.server.shutdown_called is True
    assert server.server.stop_called is True
