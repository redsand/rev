import importlib
import sys
import types


def test_lsp_imports_use_lsprotocol(monkeypatch) -> None:
    dummy_pygls = types.ModuleType("pygls")
    dummy_pygls_server = types.ModuleType("pygls.server")
    dummy_pygls_lsp = types.ModuleType("pygls.lsp")
    dummy_pygls_lsp_server = types.ModuleType("pygls.lsp.server")

    class DummyLanguageServer:
        def __init__(self, _name, _version):
            return None

    dummy_pygls_server.LanguageServer = DummyLanguageServer
    dummy_pygls_lsp_server.LanguageServer = DummyLanguageServer

    dummy_lsprotocol = types.ModuleType("lsprotocol")
    dummy_lsprotocol_types = types.ModuleType("lsprotocol.types")

    dummy_lsprotocol_types.TEXT_DOCUMENT_DID_OPEN = "textDocument/didOpen"
    dummy_lsprotocol_types.TEXT_DOCUMENT_DID_CHANGE = "textDocument/didChange"
    dummy_lsprotocol_types.TEXT_DOCUMENT_DID_SAVE = "textDocument/didSave"
    dummy_lsprotocol_types.TEXT_DOCUMENT_CODE_ACTION = "textDocument/codeAction"
    dummy_lsprotocol_types.TEXT_DOCUMENT_COMPLETION = "textDocument/completion"
    dummy_lsprotocol_types.WORKSPACE_EXECUTE_COMMAND = "workspace/executeCommand"

    class DummyType:
        pass

    for name in (
        "CodeAction",
        "CodeActionKind",
        "CodeActionParams",
        "Command",
        "CompletionItem",
        "CompletionList",
        "CompletionParams",
        "DidOpenTextDocumentParams",
        "DidChangeTextDocumentParams",
        "DidSaveTextDocumentParams",
        "ExecuteCommandParams",
        "Position",
        "Range",
        "TextEdit",
    ):
        setattr(dummy_lsprotocol_types, name, DummyType)

    monkeypatch.setitem(sys.modules, "pygls", dummy_pygls)
    monkeypatch.setitem(sys.modules, "pygls.server", dummy_pygls_server)
    monkeypatch.setitem(sys.modules, "pygls.lsp", dummy_pygls_lsp)
    monkeypatch.setitem(sys.modules, "pygls.lsp.server", dummy_pygls_lsp_server)
    monkeypatch.setitem(sys.modules, "lsprotocol", dummy_lsprotocol)
    monkeypatch.setitem(sys.modules, "lsprotocol.types", dummy_lsprotocol_types)
    sys.modules.pop("pygls.lsp.methods", None)
    sys.modules.pop("pygls.lsp.types", None)

    import rev.ide.lsp_server as lsp_server
    importlib.reload(lsp_server)

    assert lsp_server.LSP_AVAILABLE is True
