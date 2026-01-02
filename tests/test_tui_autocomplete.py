"""Unit tests for TUI slash command autocomplete."""

import pytest

import rev.terminal.tui as tui


def test_autocomplete_single_match(monkeypatch):
    monkeypatch.setattr(
        tui,
        "_get_command_suggestions",
        lambda: ["/help", "/status", "/set"],
    )
    new_buf, matches = tui.autocomplete_slash_command("/he")
    assert new_buf == "/help "
    assert matches == ["/help"]


def test_autocomplete_multiple_matches(monkeypatch):
    monkeypatch.setattr(
        tui,
        "_get_command_suggestions",
        lambda: ["/set", "/status", "/save"],
    )
    new_buf, matches = tui.autocomplete_slash_command("/s")
    assert new_buf == "/s"  # common prefix does not advance beyond input
    assert set(matches) == {"/set", "/status", "/save"}


def test_autocomplete_common_prefix_extension(monkeypatch):
    monkeypatch.setattr(
        tui,
        "_get_command_suggestions",
        lambda: ["/model", "/mode"],
    )
    new_buf, matches = tui.autocomplete_slash_command("/mo")
    assert new_buf == "/mode"  # common prefix extends to /mode
    assert set(matches) == {"/model", "/mode"}


def test_autocomplete_non_command(monkeypatch):
    monkeypatch.setattr(
        tui,
        "_get_command_suggestions",
        lambda: ["/help"],
    )
    new_buf, matches = tui.autocomplete_slash_command("npm")
    assert new_buf == "npm"
    assert matches == []
