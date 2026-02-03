#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Artifact persistence helpers (safe by default).

Stores large tool outputs on disk while redacting sensitive values.
Writes are atomic and filenames are collision-proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Set

from rev import config
from rev.execution.redaction import redact_sensitive, REDACTION_RULES_VERSION


SCHEMA_VERSION = "tool_output@1"


_COUNTER_LOCK = threading.Lock()
_COUNTER = 0


@dataclass(frozen=True)
class ArtifactRef:
    path: Path

    def as_posix(self) -> str:
        try:
            return self.path.relative_to(config.ROOT).as_posix()
        except Exception:
            return str(self.path).replace("\\", "/")


def _iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_stamp_for_filename() -> str:
    # Filename-friendly and sortable.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _next_counter() -> int:
    global _COUNTER
    with _COUNTER_LOCK:
        _COUNTER += 1
        return _COUNTER


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:
        payload = str(value).encode("utf-8", errors="replace")
    return _sha256_bytes(payload)


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _max_tool_outputs_to_keep() -> int:
    """Return retention limit for tool output artifacts (default=20)."""
    try:
        env_value = os.getenv("REV_TOOL_OUTPUTS_MAX_KEEP", "").strip()
        if env_value:
            return max(1, int(env_value))
    except Exception:
        pass
    return 20


def _session_from_filename(path: Path) -> Optional[str]:
    """Extract session_id token from the artifact filename if present."""
    try:
        parts = path.stem.split("_")
        # Filename format: stamp_counter_pid_session_task_tool.json
        if len(parts) >= 6:
            return parts[3]
    except Exception:
        return None
    return None


def _prune_old_tool_outputs(max_keep: int, keep_sessions: Optional[Set[str]] = None) -> None:
    """Prune old tool output artifacts, preserving newest + protected sessions."""
    try:
        files = sorted(
            config.TOOL_OUTPUTS_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return

    keep_sessions = keep_sessions or set()
    protected: Set[Path] = set()
    for path in files:
        session = _session_from_filename(path)
        if session and session in keep_sessions:
            protected.add(path)
            # Only the newest artifact per keep_session should be protected
            keep_sessions.remove(session)
        if not keep_sessions:
            break

    allow_remaining = max_keep - len(protected)
    if allow_remaining < 0:
        allow_remaining = 0

    kept_remaining = 0
    for path in files:
        if path in protected:
            continue
        if kept_remaining < allow_remaining:
            kept_remaining += 1
            continue
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue


def _tool_allowlisted_payload(tool: str, raw_output: str) -> Tuple[Any, str]:
    """Return (payload, content_type) to store based on tool allowlisting."""

    tool_lower = (tool or "").lower()

    # Prefer structured storage for shell/test tools.
    if tool_lower in {"run_cmd", "run_tests"}:
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                allow = {
                    "rc": parsed.get("rc"),
                    "stdout": parsed.get("stdout", ""),
                    "stderr": parsed.get("stderr", ""),
                }
                return allow, "application/json"
        except Exception:
            # Fall back to plain text.
            return raw_output, "text/plain"

    # Default: store the raw output string.
    return raw_output, "text/plain"


def write_tool_output_artifact(
    *,
    tool: str,
    args: Dict[str, Any],
    output: str,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    step_id: Optional[int] = None,
    agent_name: Optional[str] = None,
    truncated: bool = False,
) -> Tuple[ArtifactRef, Dict[str, Any]]:
    """Persist tool output to `.rev/artifacts/tool_outputs` with redaction + metadata."""

    config.TOOL_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    stamp = _safe_stamp_for_filename()
    created_at = _iso_utc()
    counter = _next_counter()
    pid = os.getpid()
    tool_safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (tool or "tool"))[:64] or "tool"
    sid_safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (session_id or "session"))[:64] or "session"
    tid_safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(task_id or "task"))[:64] or "task"

    filename = f"{stamp}_{counter:06d}_{pid}_{sid_safe}_{tid_safe}_{tool_safe}.json"
    final_path = config.TOOL_OUTPUTS_DIR / filename
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")

    # Allowlist storage shape for certain tools.
    allow_payload, content_type = _tool_allowlisted_payload(tool, output)

    # Redact before persisting.
    redacted_payload, redacted_changed = redact_sensitive(allow_payload)

    # Compute digests (safe even for raw; hashes only).
    tool_args_digest = _sha256_json(args)
    output_digest_raw = _sha256_bytes(output.encode("utf-8", errors="replace"))
    output_digest_redacted = _sha256_json(redacted_payload)

    # Estimate size/lines based on raw string where possible.
    raw_bytes = len(output.encode("utf-8", errors="replace"))
    raw_lines = _line_count(output)

    artifact: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "tool": tool,
        "agent_name": agent_name,
        "session_id": session_id,
        "task_id": task_id,
        "step_id": step_id,
        "tool_args": args,
        "tool_args_digest": tool_args_digest,
        "content_type": content_type,
        "output": redacted_payload,
        "redacted": bool(redacted_changed),
        "redaction_rules_version": REDACTION_RULES_VERSION,
        "output_digest_raw": output_digest_raw,
        "output_digest_redacted": output_digest_redacted,
        "truncated": bool(truncated),
        "byte_len": raw_bytes,
        "line_count": raw_lines,
    }

    # Atomic write: tmp -> fsync -> replace
    tmp_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8", errors="replace")
    try:
        with open(tmp_path, "rb") as f:
            os.fsync(f.fileno())
    except Exception:
        pass
    os.replace(tmp_path, final_path)

    # Enforce retention: keep newest N artifacts, always preserving current session.
    try:
        keep_sessions = {session_id} if session_id else set()
        _prune_old_tool_outputs(_max_tool_outputs_to_keep(), keep_sessions=keep_sessions)
    except Exception:
        pass

    ref = ArtifactRef(path=final_path)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "redacted": bool(redacted_changed),
        "redaction_rules_version": REDACTION_RULES_VERSION,
        "tool_args_digest": tool_args_digest,
        "output_digest_raw": output_digest_raw,
        "output_digest_redacted": output_digest_redacted,
        "byte_len": raw_bytes,
        "line_count": raw_lines,
        "truncated": bool(truncated),
        "content_type": content_type,
        "created_at": created_at,
    }
    return ref, meta
