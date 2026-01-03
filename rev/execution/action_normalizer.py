"""Normalize action type tokens (including fuzzy typos) to canonical actions.

Sub-agent mode relies on a lightweight planner that outputs tokens like:
  [REFACTOR] ...

Some models occasionally emit typos such as:
  [REFACRT], [REFRACTO], [REFAOCRT]

This module maps those to the closest canonical action safely.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, Optional


_EXACT_ALIASES: dict[str, str] = {
    # canonical shims
    "create": "add",
    "write": "add",
    "fix": "edit",
    "general": "refactor",
    "investigate": "research",
    # read-only synonyms
    "read": "read",
    "inspect": "read",
    "view": "read",
    "explain": "read",
    "list": "read",
    # file operation aliases
    "rename_file": "rename",
    "move_file": "move",
    "delete_file": "delete",
    "remove_file": "delete",
    "run_cmd": "run",
    "run_command": "run",
    "exec": "execute",
    # tool-shaped action tokens (map to canonical actions)
    "read_file": "read",
    "list_dir": "read",
    "list_directory": "read",
    "tree_view": "read",
    "search_code": "research",
    "get_repo_context": "read",
    "write_file": "add",
    "create_file": "add",
    "append_to_file": "edit",
    "replace_in_file": "edit",
    "apply_patch": "edit",
    "run_tests": "test",
    # meta/invalid action tokens seen in the wild
    "action": "analyze",
    "action_type": "analyze",
    "actionable_subtask": "analyze",
    # known refactor typos
    "refator": "refactor",
    "refracto": "refactor",
    "refacto": "refactor",
    "refctor": "refactor",
}


def _clean_token(token: str) -> str:
    # Keep alphanumerics only; collapse separators.
    token = (token or "").strip().lower()
    token = token.replace("\\", "/")
    token = re.sub(r"[^a-z0-9]+", "", token)
    return token


def normalize_action_type(
    raw_action: str,
    *,
    available_actions: Iterable[str],
    fuzzy: bool = True,
) -> str:
    """Return a canonical action type from a raw token."""

    raw = (raw_action or "").strip().lower()
    if not raw:
        return raw

    # Exact aliases first.
    if raw in _EXACT_ALIASES:
        return _EXACT_ALIASES[raw]

    actions = [a.strip().lower() for a in available_actions if isinstance(a, str) and a.strip()]
    if raw in actions:
        return raw

    if not fuzzy:
        return raw

    raw_clean = _clean_token(raw)
    if len(raw_clean) < 4:
        return raw

    best_action: Optional[str] = None
    best_ratio = 0.0
    for action in actions:
        action_clean = _clean_token(action)
        if not action_clean:
            continue
        # Heuristics to avoid ridiculous matches.
        if abs(len(action_clean) - len(raw_clean)) > 4:
            continue
        ratio = SequenceMatcher(None, raw_clean, action_clean).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_action = action

    if not best_action:
        return raw

    # Thresholding: accept high-confidence matches always, medium only if first char matches.
    if best_ratio >= 0.86:
        return best_action
    if best_ratio >= 0.74 and raw_clean[:1] == _clean_token(best_action)[:1]:
        return best_action

    return raw
