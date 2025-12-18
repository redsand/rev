#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable project memory for Rev (.rev/memory/project_summary.md).

Write rules (keep memory trustworthy):
- write when a task completes
- write when a failure mode is diagnosed
- write when a convention/decision is introduced
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from rev import config


_SECTION_ORDER = [
    "What This Repo Is",
    "Current Architecture",
    "Known Failure Modes + Fixes",
    "Conventions",
    "Recently Changed Files",
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def _ensure_dirs() -> None:
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _default_memory_template() -> str:
    return (
        "# Project Memory (Rev)\n"
        "\n"
        "This file is maintained automatically by Rev.\n"
        "It is intentionally concise and operational.\n"
        "\n"
        "## What This Repo Is\n"
        "- Rev: agentic CI/CD + refactoring assistant focused on safe, verifiable changes.\n"
        "\n"
        "## Current Architecture\n"
        "- Execution modes: linear executor and sub-agent orchestrator.\n"
        "- WorkspaceResolver: canonical path validation for tools/verifiers.\n"
        "- ContextBuilder: Select pipeline (code/docs/tools/memory) with tool retrieval.\n"
        "- Artifacts: tool outputs persisted under `.rev/artifacts/` (redacted).\n"
        "- CompressionPolicy: centralized tool-output compression knobs.\n"
        "\n"
        "## Known Failure Modes + Fixes\n"
        "- (none recorded)\n"
        "\n"
        "## Conventions\n"
        "- Prefer package exports (`__init__.py`) over mass explicit imports.\n"
        "- Don’t re-run tests unless something changed; prefer smoke imports for import-only validation.\n"
        "\n"
        "## Recently Changed Files\n"
        "- (none recorded)\n"
    )


def ensure_project_memory_file(path: Optional[Path] = None) -> Path:
    _ensure_dirs()
    target = path or config.PROJECT_MEMORY_FILE
    if not target.exists():
        target.write_text(_default_memory_template(), encoding="utf-8")
    return target


def _parse_sections(md: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    lines = (md or "").splitlines()
    for line in lines:
        m = re.match(r"^##\s+(.*)\s*$", line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append(line)
    return sections


def _render_sections(sections: Dict[str, List[str]]) -> str:
    parts = ["# Project Memory (Rev)", "", "This file is maintained automatically by Rev.", "It is intentionally concise and operational.", ""]
    for name in _SECTION_ORDER:
        parts.append(f"## {name}")
        body = sections.get(name) or ["- (none recorded)"]
        # Trim excessive blank lines
        while body and body[0] == "":
            body = body[1:]
        while body and body[-1] == "":
            body = body[:-1]
        parts.extend(body if body else ["- (none recorded)"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _dedupe_keep_recent(lines: List[str], *, max_items: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for line in lines:
        key = line.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out[:max_items]


def record_recent_changes(
    *,
    files_created: List[str],
    files_modified: List[str],
    files_deleted: List[str],
    stamp: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    """Update the 'Recently Changed Files' section with a compact entry."""

    target = ensure_project_memory_file(path)
    md = target.read_text(encoding="utf-8", errors="replace")
    sections = _parse_sections(md)

    stamp = stamp or _utc_stamp()
    entry_lines = [f"- {stamp}"]
    if files_created:
        entry_lines.append(f"  - created: {', '.join(files_created[-10:])}")
    if files_modified:
        entry_lines.append(f"  - modified: {', '.join(files_modified[-10:])}")
    if files_deleted:
        entry_lines.append(f"  - deleted: {', '.join(files_deleted[-10:])}")

    existing = sections.get("Recently Changed Files") or []
    # Drop placeholder
    existing = [l for l in existing if "(none recorded)" not in l]
    merged = entry_lines + [""] + existing
    # Keep the first ~30 lines (roughly last 5-8 events).
    sections["Recently Changed Files"] = merged[:30]

    target.write_text(_render_sections(sections), encoding="utf-8")


def record_failure_mode(
    *,
    title: str,
    symptom: str,
    fix: str,
    evidence_ref: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    target = ensure_project_memory_file(path)
    md = target.read_text(encoding="utf-8", errors="replace")
    sections = _parse_sections(md)

    existing = sections.get("Known Failure Modes + Fixes") or []
    existing = [l for l in existing if "(none recorded)" not in l]

    stamp = _utc_stamp()
    lines = [
        f"- {title} ({stamp})",
        f"  - symptom: {symptom}",
        f"  - fix: {fix}",
    ]
    if evidence_ref:
        lines.append(f"  - evidence: {evidence_ref}")

    # Dedupe by title prefix.
    if any(l.strip().startswith(f"- {title} ") for l in existing):
        return

    merged = lines + [""] + existing
    sections["Known Failure Modes + Fixes"] = _dedupe_keep_recent(merged, max_items=60)
    target.write_text(_render_sections(sections), encoding="utf-8")


def maybe_record_known_failure_from_error(
    *,
    error_text: str,
    evidence_ref: Optional[str] = None,
    path: Optional[Path] = None,
) -> bool:
    """Heuristic: if an error matches a known failure signature, record it once."""

    text = (error_text or "").lower()
    if "outside allowed workspace roots" in text or "add an allowed root via '/add-dir" in text:
        record_failure_mode(
            title="Workspace path outside allowed roots",
            symptom="Tools/verifiers reject a path as outside the workspace",
            fix="Run rev from the target repo root or use `/add-dir <path>` to allowlist the directory.",
            evidence_ref=evidence_ref,
            path=path,
        )
        return True

    if "could not determine file path to verify" in text:
        record_failure_mode(
            title="Verification cannot determine file path",
            symptom="Verifier reports it cannot determine the file path to verify",
            fix="Ensure tool metadata includes `path_abs/path_rel` and verifier uses tool args fallback.",
            evidence_ref=evidence_ref,
            path=path,
        )
        return True

    return False

