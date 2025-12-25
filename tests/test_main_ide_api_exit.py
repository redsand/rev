"""Ensure IDE API mode exits cleanly after server start."""

import sys

import pytest


def test_ide_api_exits_after_server_start(monkeypatch):
    import rev.main as main
    import rev.ide.api_server as api_server

    class DummyServer:
        def __init__(self, config=None):
            self.config = config

        def start(self, host=None, port=None):
            return None

    monkeypatch.setattr(api_server, "RevAPIServer", DummyServer)
    monkeypatch.setattr(sys, "argv", ["rev", "--ide-api"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
