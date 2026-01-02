import rev.agents.code_writer as cw


def test_read_file_content_allows_empty(monkeypatch):
    """Empty file contents should be treated as readable (return empty string, not None)."""
    calls = []

    def fake_execute_registry_tool(name, args):
        calls.append((name, args))
        return ""  # simulate empty file content

    monkeypatch.setattr(cw, "execute_registry_tool", fake_execute_registry_tool)

    result = cw._read_file_content_for_edit("src/App.vue")

    assert result == ""
    assert calls and calls[0][0] == "read_file"
