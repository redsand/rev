#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Redaction helpers for persisted artifacts.

Artifacts are a truth store; redact sensitive values by default.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Tuple, Union


REDACTION_RULES_VERSION = 1


_TOKEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI-style keys
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk-[REDACTED]"),
    # GitHub personal access tokens
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "ghp_[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github_pat_[REDACTED]"),
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[REDACTED]"),
    # Generic bearer tokens / auth headers
    (re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[A-Za-z0-9._-]{10,}"), "Authorization: Bearer [REDACTED]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{10,}"), "Bearer [REDACTED]"),
    # Common env-style assignments
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*=\s*['\"]?[^'\"\s]{6,}"), r"\1=[REDACTED]"),
]


def redact_sensitive_text(text: str) -> Tuple[str, bool]:
    """Return (redacted_text, changed)."""

    if not text:
        return text, False

    changed = False
    out = text
    for pattern, replacement in _TOKEN_PATTERNS:
        new_out, n = pattern.subn(replacement, out)
        if n:
            changed = True
            out = new_out
    return out, changed


def redact_sensitive(value: Union[str, Dict[str, Any], Any]) -> Tuple[Any, bool]:
    """Redact sensitive data in str or JSON-like dict/list payloads."""

    if isinstance(value, str):
        return redact_sensitive_text(value)

    if isinstance(value, dict):
        changed = False
        out: Dict[str, Any] = {}
        for k, v in value.items():
            red_v, did = redact_sensitive(v)
            changed = changed or did
            out[k] = red_v
        return out, changed

    if isinstance(value, list):
        changed = False
        out_list = []
        for item in value:
            red_item, did = redact_sensitive(item)
            changed = changed or did
            out_list.append(red_item)
        return out_list, changed

    # Fallback: try JSON roundtrip for simple types
    try:
        dumped = json.dumps(value)
        red, did = redact_sensitive_text(dumped)
        return json.loads(red), did
    except Exception:
        return value, False

