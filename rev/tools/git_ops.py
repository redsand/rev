#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Git operations tools for rev."""

import json
import os
import pathlib
import re
import shlex
import subprocess
import tempfile
from typing import Optional, Iterable, Tuple, Dict, Any

# Patches larger than this many characters often hit context limits in agent prompts
# or produce opaque failures. When we detect a patch above this size that still
# fails validation, we return a hint encouraging the caller to split the change
# into smaller chunks.
_LARGE_PATCH_HINT_THRESHOLD = 120_000

from rev import config
from rev.debug_logger import prune_old_logs
from rev.tools.utils import quote_cmd_arg
from rev.llm.client import ollama_chat
from rev.tools.command_runner import run_command_safe, run_command_background, list_background_processes, kill_background_process

# Backward compatibility for tests
ROOT = config.ROOT

_DEFAULT_RUN_CMD_TIMEOUT = 120
_DEFAULT_RUN_TESTS_TIMEOUT = 600
_LLM_TIMEOUT_ANALYSIS_MIN_SECONDS = 120
_LLM_TIMEOUT_ANALYSIS_MAX_SECONDS = 3600
_LLM_TIMEOUT_OUTPUT_LIMIT = 2000

_TIMEOUT_ANALYSIS_SYSTEM_PROMPT = (
    "You are a command-timeout triage assistant. "
    "Decide if a timed-out command is likely long-running (should rerun with a longer timeout) "
    "or stuck in non-terminating watch/server mode (should stop). "
    "Return ONLY JSON with: decision ('rerun' or 'stop'), suggested_timeout_seconds (int, "
    "only if decision='rerun'), mode ('long_running' or 'watch' or 'unknown'), reason, "
    "and suggested_command (string, optional) if a different command should be run instead."
)


# ========== Helper Function ==========

def _run_shell(cmd: str | list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command (DEPRECATED - use command_runner module instead).

    This function is maintained for backward compatibility only.
    New code should use rev.tools.command_runner.run_command_safe()
    """
    from rev.tools.command_runner import run_command_safe

    try:
        result = run_command_safe(cmd, timeout=timeout, check_interrupt=False)

        # Return a CompletedProcess object for compatibility
        if result.get("blocked"):
            # Command was blocked for security reasons
            error_msg = result.get('error', 'security violation')
            return subprocess.CompletedProcess(
                args=str(cmd),
                returncode=-1,
                stdout="",
                stderr=f"BLOCKED: {error_msg}"
            )

        rc = result.get("rc")
        if rc is None:
            rc = -1
            
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        
        # If we have an internal error message but no stderr, surface it
        internal_error = result.get("error")
        if internal_error and not stderr:
            stderr = f"INTERNAL ERROR: {internal_error}"

        return subprocess.CompletedProcess(
            args=str(cmd),
            returncode=rc,
            stdout=stdout,
            stderr=stderr
        )
    except OSError as exc:
        # On Windows low-memory/paging-file failures (e.g., WinError 1455), return a CompletedProcess-like
        # object so callers can surface a clear message instead of crashing.
        return subprocess.CompletedProcess(
            args=str(cmd),
            returncode=1,
            stdout="",
            stderr=str(exc),
        )


def _create_log_file(prefix: str) -> pathlib.Path:
    """Create a log file inside .rev/logs for streaming command output."""

    log_dir = config.LOGS_DIR
    log_dir.mkdir(exist_ok=True, parents=True)

    fd, path_str = tempfile.mkstemp(prefix=prefix, suffix=".log", dir=log_dir)
    os.close(fd)
    prune_old_logs(log_dir, config.LOG_RETENTION_LIMIT)
    return pathlib.Path(path_str)


def _tail_file(path: pathlib.Path, limit: int) -> str:
    """Read the last ``limit`` characters from ``path`` without loading the file."""

    if limit <= 0 or not path.exists():
        return ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size > limit:
            handle.seek(size - limit)
        else:
            handle.seek(0)
        return handle.read()


def _truncate_text(value: str, limit: int) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[-limit:]


def _parse_timeout_decision(content: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    text = content.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _extract_test_path_from_command(cmd_text: str) -> Optional[str]:
    if not cmd_text:
        return None
    matches = re.findall(r"([A-Za-z0-9_./\\\\-]+\\.(?:test|spec)\\.[A-Za-z0-9]+)", cmd_text)
    if not matches:
        return None
    return max(matches, key=len)


def _normalize_timeout_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    decision_raw = str(payload.get("decision") or payload.get("action") or payload.get("status") or "").strip().lower()
    mode_raw = str(payload.get("mode") or payload.get("classification") or payload.get("category") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    suggested_command_raw = (
        payload.get("suggested_command")
        or payload.get("suggested_cmd")
        or payload.get("alternate_command")
        or payload.get("rerun_command")
    )
    suggested_command = None
    if isinstance(suggested_command_raw, (str, list)):
        suggested_command = suggested_command_raw

    decision = decision_raw
    if decision in {"retry", "rerun", "continue", "extend"}:
        decision = "rerun"
    if decision in {"stop", "cancel", "abort", "halt", "watch", "wait"}:
        decision = "stop"

    if decision not in {"rerun", "stop"}:
        if mode_raw in {"watch", "non_terminating", "non-terminating", "server"}:
            decision = "stop"
        elif mode_raw in {"long_running", "long-running"}:
            decision = "rerun"

    suggested = (
        payload.get("suggested_timeout_seconds")
        or payload.get("suggested_timeout")
        or payload.get("timeout_seconds")
        or payload.get("timeout")
    )
    suggested_timeout: Optional[int] = None
    try:
        if suggested is not None:
            suggested_timeout = int(suggested)
    except Exception:
        suggested_timeout = None

    return {
        "decision": decision if decision in {"rerun", "stop"} else "stop",
        "suggested_timeout_seconds": suggested_timeout,
        "mode": mode_raw or "unknown",
        "reason": reason,
        "suggested_command": suggested_command,
    }


def _detect_watch_mode(output: str) -> bool:
    if not output:
        return False
    lowered = output.lower()
    watch_markers = (
        "watching for file changes",
        "waiting for file changes",
        "press q to quit",
        "press h to show help",
        "dev server running",
        "localhost:",
        "127.0.0.1:",
        "waiting for changes",
        "ready in",
        "watch mode",
        "listening on",
    )
    return any(marker in lowered for marker in watch_markers)


def _suggest_non_watch_command(cmd_text: str) -> Optional[str]:
    if not cmd_text:
        return None
    lowered = cmd_text.lower()
    if "vitest" not in lowered:
        return None
    if " vitest run" in lowered or "vitest --run" in lowered:
        return None
    test_path = _extract_test_path_from_command(cmd_text)
    if test_path:
        return f"npx vitest run {test_path}"
    return "npx vitest run"


def _clamp_timeout(value: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except Exception:
        return minimum


def _analyze_timeout_with_llm(
    cmd_text: str,
    timeout: int,
    stdout_tail: str,
    stderr_tail: str,
) -> Optional[Dict[str, Any]]:
    user_prompt = (
        f"Command: {cmd_text}\n"
        f"TimeoutSeconds: {timeout}\n"
        "StdoutTail:\n"
        f"{stdout_tail}\n"
        "StderrTail:\n"
        f"{stderr_tail}\n"
        "If output suggests watch/server mode or waiting for file changes, choose decision='stop'. "
        "If output suggests active tests/builds that just need more time, choose decision='rerun' "
        "and provide suggested_timeout_seconds. "
        "If a different command should be run instead (for example, a non-watch test command), "
        "include suggested_command."
    )
    response = ollama_chat(
        [
            {"role": "system", "content": _TIMEOUT_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tools=None,
        model=config.EXECUTION_MODEL,
        supports_tools=False,
        temperature=0.2,
    )
    if not response or "error" in response:
        return None
    content = response.get("message", {}).get("content", "")
    payload = _parse_timeout_decision(content)
    if not payload:
        return None
    return _normalize_timeout_decision(payload)


def _maybe_retry_timeout(
    cmd: str | list[str],
    timeout: int,
    cwd: Optional[pathlib.Path],
    result: Dict[str, Any],
    *,
    is_tests: bool = False,
) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result
    if not (result.get("timed_out") or result.get("timeout")):
        return result
    if timeout < _LLM_TIMEOUT_ANALYSIS_MIN_SECONDS:
        return result

    cmd_text = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
    stdout_tail = _truncate_text(result.get("stdout", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
    stderr_tail = _truncate_text(result.get("stderr", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
    combined_output = f"{stdout_tail}\n{stderr_tail}".strip()

    decision = _analyze_timeout_with_llm(cmd_text, timeout, stdout_tail, stderr_tail)
    decision_source = "llm"
    if not decision:
        decision_source = "heuristic"
        if _detect_watch_mode(combined_output):
            suggested_command = _suggest_non_watch_command(cmd_text)
            decision = {
                "decision": "stop",
                "mode": "watch",
                "reason": "output indicates watch/server mode",
                "suggested_command": suggested_command,
            }
        else:
            decision = {
                "decision": "rerun",
                "mode": "unknown",
                "reason": "no watch-mode indicators; retrying with extended timeout",
            }

    normalized = dict(result)
    normalized["timeout_decision"] = {**decision, "source": decision_source, "stdout_tail": stdout_tail, "stderr_tail": stderr_tail}
    normalized["timeout_initial"] = {
        "timeout_seconds": timeout,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "cmd": cmd_text,
        "cwd": str(cwd) if cwd else None,
    }

    # For tests: avoid blindly re-running with larger timeouts. Surface the suggestion instead.
    if is_tests and decision.get("decision") == "rerun":
        normalized["blocked"] = True
        normalized["reason"] = decision.get("reason") or "Test command timed out"
        normalized["timeout_decision"] = {**decision, "source": decision_source, "stdout_tail": stdout_tail, "stderr_tail": stderr_tail}
        normalized["timeout_initial"] = {
            "timeout_seconds": timeout,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "cmd": cmd_text,
            "cwd": str(cwd) if cwd else None,
        }
        # Flag that a remediation is required; orchestrator/verification can inject a fix task.
        normalized["needs_fix"] = True
        return normalized

    if decision.get("decision") != "rerun":
        normalized["blocked"] = True
        if decision.get("reason"):
            normalized["reason"] = decision.get("reason")
        return normalized

    suggested = decision.get("suggested_timeout_seconds")
    if suggested is None:
        suggested = timeout * 2

    rerun_timeout = _clamp_timeout(
        suggested,
        minimum=max(timeout + 30, _LLM_TIMEOUT_ANALYSIS_MIN_SECONDS),
        maximum=_LLM_TIMEOUT_ANALYSIS_MAX_SECONDS,
    )
    if rerun_timeout <= timeout:
        rerun_timeout = min(timeout * 2, _LLM_TIMEOUT_ANALYSIS_MAX_SECONDS)

    rerun_cmd = cmd
    suggested_command = decision.get("suggested_command")
    if isinstance(suggested_command, (str, list)) and suggested_command:
        rerun_cmd = suggested_command

    from rev.tools.command_runner import run_command_safe

    rerun_result = run_command_safe(
        rerun_cmd,
        timeout=rerun_timeout,
        cwd=cwd,
        capture_output=True,
        check_interrupt=True,
    )
    if isinstance(rerun_result, dict):
        rerun_result["timeout_retry"] = {
            "timeout_seconds": rerun_timeout,
            "is_tests": is_tests,
            "command": " ".join(rerun_cmd) if isinstance(rerun_cmd, list) else str(rerun_cmd),
        }
        rerun_result["timeout_decision"] = normalized.get("timeout_decision")
        rerun_result["timeout_initial"] = normalized.get("timeout_initial")
    return rerun_result if isinstance(rerun_result, dict) else normalized


def _working_tree_snapshot() -> str:


    """Return a lightweight snapshot of working tree changes.





    We use ``git status --porcelain`` so we can detect when an apply operation


    reports success but does not actually modify the tree (for example, when an


    empty or already-applied patch slips through).


    """


    if not is_git_repo():


        return ""





    proc = _run_shell("git status --porcelain")


    return proc.stdout


def _extract_patch_paths(lines: list[str]) -> set[str]:
    """Return the set of file paths referenced by a patch."""

    paths: set[str] = set()
    for line in lines:
        if not line.startswith(("+++ ", "--- ")):
            continue

        try:
            _, raw_path = line.split(" ", 1)
        except ValueError:
            continue

        raw_path = raw_path.strip()
        if raw_path in {"/dev/null", "dev/null", "a/dev/null", "b/dev/null"}:
            continue

        if raw_path.startswith(("a/", "b/")):
            raw_path = raw_path[2:]

        paths.add(raw_path)

    return paths


def _split_patch_into_chunks(patch: str) -> list[str]:
    """Split a multi-file patch into file-scoped chunks.

    We attempt to keep ``diff --git`` and header lines attached to each file so
    downstream apply calls have the necessary context. Chunks without both
    ``---`` and ``+++`` headers are ignored to avoid sending malformed diffs to
    the apply routines.
    """

    # Prefer diff --git boundaries when available; otherwise fall back to the
    # first --- header for simple patches.
    if "diff --git" in patch:
        parts = re.split(r"(?m)^diff --git ", patch)
        # ``re.split`` drops the delimiter; put it back.
        chunks = [f"diff --git {p}" for p in parts if p.strip()]
    else:
        chunks = re.split(r"(?m)(?=^--- )", patch)
        chunks = [c for c in chunks if c.strip()]

    formatted: list[str] = []
    for chunk in chunks:
        if "--- " not in chunk or "+++ " not in chunk:
            continue
        formatted.append(chunk if chunk.endswith("\n") else f"{chunk}\n")

    return formatted


def _retry_plan_message(chunk_count: int) -> str:
    """Return guidance for retrying a failed patch application.

    The message encourages callers to keep engaging the LLM until it delivers a
    workable patch and to split the change into smaller, sequentially applied
    chunks when necessary.
    """

    target_chunks = max(2, chunk_count)
    return (
        "Patch failed to apply cleanly. Ask the model to retry until it returns "
        "a valid diff, and if failures persist, split the update into "
        f"~{target_chunks} smaller chunk(s) (for example, by file) and apply them "
        "one at a time."
    )


def _snapshot_paths(paths: set[str]) -> dict[str, Optional[bytes]]:
    """Capture the current content for a set of files.

    Missing files are represented by ``None`` so we can detect creations and
    deletions in addition to modifications.
    """

    snapshot: dict[str, Optional[bytes]] = {}
    for path in paths:
        full_path = config.ROOT / path
        snapshot[path] = full_path.read_bytes() if full_path.exists() else None
    return snapshot


def _normalize_patch_text(patch: str) -> str:
    """Normalize non-standard whitespace that can break patch parsing."""
    # Standardize newline handling first
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")

    # Replace various Unicode whitespace characters with a standard space
    whitespace_pattern = re.compile(
        r'[\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000]'
    )
    normalized = whitespace_pattern.sub(' ', normalized)

    # Remove zero-width characters
    zero_width_pattern = re.compile(r'[\u200B-\u200D\uFEFF]')
    normalized = zero_width_pattern.sub('', normalized)

    return normalized


def _split_codex_hunks(lines: list[str]) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("@@"):
            if current:
                hunks.append(current)
                current = []
            continue
        if line.startswith("\\"):
            continue
        current.append(line)
    if current:
        hunks.append(current)
    return hunks


def _parse_codex_patch(patch: str) -> Tuple[Optional[list[dict]], Optional[str]]:
    lines = patch.splitlines()
    start_idx = None
    end_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == "*** Begin Patch":
            start_idx = idx + 1
            continue
        if line.strip() == "*** End Patch":
            end_idx = idx
            break

    if start_idx is None or end_idx is None or end_idx < start_idx:
        return None, "Invalid Codex patch: missing Begin/End markers"

    ops: list[dict] = []
    idx = start_idx
    while idx < end_idx:
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            idx += 1
            move_to = None
            if idx < end_idx and lines[idx].startswith("*** Move to: "):
                move_to = lines[idx][len("*** Move to: "):].strip()
                idx += 1
            hunk_lines: list[str] = []
            while idx < end_idx and not lines[idx].startswith("*** "):
                hunk_lines.append(lines[idx])
                idx += 1
            ops.append({
                "type": "update",
                "path": path,
                "move_to": move_to,
                "hunks": _split_codex_hunks(hunk_lines),
            })
            continue
        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            idx += 1
            content_lines: list[str] = []
            while idx < end_idx and not lines[idx].startswith("*** "):
                content_lines.append(lines[idx])
                idx += 1
            ops.append({"type": "add", "path": path, "lines": content_lines})
            continue
        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):].strip()
            idx += 1
            ops.append({"type": "delete", "path": path})
            continue
        return None, f"Invalid Codex patch line: {line}"

    return ops, None


def _find_subsequence(haystack: list[str], needle: list[str], start: int = 0) -> Optional[int]:
    if not needle:
        return start
    max_idx = len(haystack) - len(needle)
    for idx in range(start, max_idx + 1):
        if haystack[idx:idx + len(needle)] == needle:
            return idx
    return None


def _apply_codex_update(file_lines: list[str], hunks: list[list[str]]) -> Tuple[Optional[list[str]], Optional[str]]:
    cursor = 0
    for hunk in hunks:
        source: list[str] = []
        target: list[str] = []
        for line in hunk:
            if line == "":
                source.append("")
                target.append("")
                continue
            prefix = line[:1]
            body = line[1:]
            if prefix == " ":
                source.append(body)
                target.append(body)
            elif prefix == "-":
                source.append(body)
            elif prefix == "+":
                target.append(body)
            else:
                return None, f"Invalid hunk line: {line}"

        if not source:
            file_lines[cursor:cursor] = target
            cursor += len(target)
            continue

        match_idx = _find_subsequence(file_lines, source, start=cursor)
        if match_idx is None:
            return None, "Hunk context not found in target file"

        file_lines[match_idx:match_idx + len(source)] = target
        cursor = match_idx + len(target)

    return file_lines, None


def _apply_codex_patch(patch: str, dry_run: bool) -> dict:
    ops, error = _parse_codex_patch(patch)
    if error:
        return {
            "success": False,
            "rc": 1,
            "stdout": "",
            "stderr": "",
            "dry_run": dry_run,
            "phase": "check",
            "error": error,
        }

    touched_paths = set()
    for op in ops or []:
        path = op.get("path")
        if isinstance(path, str):
            touched_paths.add(path)
        move_to = op.get("move_to")
        if isinstance(move_to, str):
            touched_paths.add(move_to)

    def _resolve_path(path: str) -> Tuple[Optional[pathlib.Path], Optional[str]]:
        try:
            from rev.tools.workspace_resolver import resolve_workspace_path
            resolved = resolve_workspace_path(path, purpose="apply_patch")
            return resolved.abs_path, None
        except Exception as exc:
            return None, str(exc)

    for rel_path in touched_paths:
        full_path, err = _resolve_path(rel_path)
        if err:
            return {
                "success": False,
                "rc": 1,
                "stdout": "",
                "stderr": "",
                "dry_run": dry_run,
                "phase": "check",
                "error": err,
            }

    changed = False

    for op in ops or []:
        op_type = op.get("type")
        rel_path = op.get("path")
        if not isinstance(rel_path, str) or not rel_path:
            return {
                "success": False,
                "rc": 1,
                "stdout": "",
                "stderr": "",
                "dry_run": dry_run,
                "phase": "check",
                "error": "Missing file path in Codex patch",
            }

        full_path, err = _resolve_path(rel_path)
        if err:
            return {
                "success": False,
                "rc": 1,
                "stdout": "",
                "stderr": "",
                "dry_run": dry_run,
                "phase": "check",
                "error": err,
            }

        if op_type == "add":
            content_lines = op.get("lines", [])
            if not isinstance(content_lines, list):
                return {
                    "success": False,
                    "rc": 1,
                    "stdout": "",
                    "stderr": "",
                    "dry_run": dry_run,
                    "phase": "check",
                    "error": f"Invalid add file content for {rel_path}",
                }
            file_lines: list[str] = []
            for line in content_lines:
                if not isinstance(line, str):
                    return {
                        "success": False,
                        "rc": 1,
                        "stdout": "",
                        "stderr": "",
                        "dry_run": dry_run,
                        "phase": "check",
                        "error": f"Invalid add line for {rel_path}",
                    }
                if line == "":
                    file_lines.append("")
                elif line.startswith("+"):
                    file_lines.append(line[1:])
                else:
                    return {
                        "success": False,
                        "rc": 1,
                        "stdout": "",
                        "stderr": "",
                        "dry_run": dry_run,
                        "phase": "check",
                        "error": f"Invalid add line for {rel_path}: {line}",
                    }

            new_content = "\n".join(file_lines)
            if file_lines:
                new_content += "\n"
            existing = full_path.read_text(encoding="utf-8", errors="ignore") if full_path.exists() else None
            if existing == new_content:
                continue
            changed = True
            if dry_run:
                continue
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_content, encoding="utf-8")
            continue

        if op_type == "delete":
            if not full_path.exists():
                continue
            changed = True
            if dry_run:
                continue
            full_path.unlink()
            continue

        if op_type == "update":
            if not full_path.exists():
                return {
                    "success": False,
                    "rc": 1,
                    "stdout": "",
                    "stderr": "",
                    "dry_run": dry_run,
                    "phase": "check",
                    "error": f"File not found: {rel_path}",
                }
            original_text = full_path.read_text(encoding="utf-8", errors="ignore")
            file_lines = original_text.splitlines()
            ends_with_newline = original_text.endswith("\n")
            hunks = op.get("hunks", [])
            if not isinstance(hunks, list):
                return {
                    "success": False,
                    "rc": 1,
                    "stdout": "",
                    "stderr": "",
                    "dry_run": dry_run,
                    "phase": "check",
                    "error": f"Invalid hunks for {rel_path}",
                }
            updated_lines, err = _apply_codex_update(list(file_lines), hunks)
            if err:
                return {
                    "success": False,
                    "rc": 1,
                    "stdout": "",
                    "stderr": "",
                    "dry_run": dry_run,
                    "phase": "check",
                    "error": f"{rel_path}: {err}",
                }
            new_content = "\n".join(updated_lines)
            if ends_with_newline:
                new_content += "\n"
            if new_content != original_text:
                changed = True
                if not dry_run:
                    full_path.write_text(new_content, encoding="utf-8")

            move_to = op.get("move_to")
            if isinstance(move_to, str) and move_to.strip():
                dest_path, err = _resolve_path(move_to)
                if err:
                    return {
                        "success": False,
                        "rc": 1,
                        "stdout": "",
                        "stderr": "",
                        "dry_run": dry_run,
                        "phase": "check",
                        "error": err,
                    }
                if dest_path.exists():
                    dest_text = dest_path.read_text(encoding="utf-8", errors="ignore")
                    if dest_text != new_content:
                        return {
                            "success": False,
                            "rc": 1,
                            "stdout": "",
                            "stderr": "",
                            "dry_run": dry_run,
                            "phase": "check",
                            "error": f"Destination exists: {move_to}",
                        }
                changed = True
                if dry_run:
                    pass
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.replace(dest_path)
            continue

        return {
            "success": False,
            "rc": 1,
            "stdout": "",
            "stderr": "",
            "dry_run": dry_run,
            "phase": "check",
            "error": f"Unsupported Codex patch operation: {op_type}",
        }

    already_applied = not changed
    return {
        "success": True,
        "rc": 0,
        "stdout": "",
        "stderr": "",
        "dry_run": dry_run,
        "phase": "apply" if not dry_run else "check",
        "already_applied": already_applied,
    }


def is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    # Check for .git directory or file (worktree) first to avoid running subprocess unnecessarily
    if (config.ROOT / ".git").exists():
        return True
        
    # Fallback to git command for nested repos or complex setups
    proc = _run_shell("git rev-parse --is-inside-work-tree")
    return proc.returncode == 0


# ========== Core Git Operations ==========

def git_diff(pathspec: str = ".", staged: bool = False, context: int = 3) -> str:
    """Get git diff for pathspec."""
    if not is_git_repo():
        return json.dumps({"rc": 1, "diff": "", "stderr": "Not a git repository"})

    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(quote_cmd_arg(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})



def apply_patch(patch: str, dry_run: bool = False, *, _allow_chunking: bool = True) -> str:
    """Apply a unified diff patch with resilient validation.

    The previous implementation proved too brittle for the kinds of diffs that
    are produced in practice. This version mirrors common CLI workflows by
    validating with ``git apply --check`` first, falling back to a standard
    ``patch`` invocation, and only performing the apply step after validation
    succeeds. We also normalize problematic whitespace up front and provide
    clearer error reporting so callers can correct issues quickly.
    """

    normalized_patch = _normalize_patch_text(patch)
    if normalized_patch.lstrip().startswith("*** Begin Patch"):
        return json.dumps(_apply_codex_patch(normalized_patch, dry_run))
    if not normalized_patch.endswith("\n"):
        normalized_patch = f"{normalized_patch}\n"

    patch_size = len(normalized_patch)
    chunked_parts = _split_patch_into_chunks(normalized_patch)
    large_patch_hint: Optional[str] = None
    if patch_size > _LARGE_PATCH_HINT_THRESHOLD:
        large_patch_hint = (
            "Patch is quite large; consider splitting it by file or feature "
            "so apply_patch can work reliably. For very large diffs you can also "
            "apply them locally with 'git apply --reject' and commit the result."
        )

    def _has_malformed_hunks(lines: list[str]) -> bool:
        """Detect obvious malformed hunk lines (missing +/-/space prefixes)."""

        in_hunk = False
        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
                continue

            if in_hunk:
                if line.startswith("@@"):
                    continue
                if line.startswith("--- ") or line.startswith("+++ "):
                    in_hunk = False
                    continue
                if line.strip() and not line.startswith(("+", "-", " ", "\\")):
                    return True
        return False

    patch_lines = normalized_patch.splitlines()
    patch_paths = _extract_patch_paths(patch_lines)

    retry_plan = _retry_plan_message(len(chunked_parts))

    if _has_malformed_hunks(patch_lines):
        proc = subprocess.CompletedProcess("apply_patch", 1, "", "patch validation failed: unexpected hunk line")
        return json.dumps(
            {
                "success": False,
                "rc": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "dry_run": dry_run,
                "phase": "check",
                "error": "Patch failed basic validation",
            }
        )

    pre_status = _working_tree_snapshot()
    pre_contents = _snapshot_paths(patch_paths)

    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(normalized_patch)
        tf.flush()
        tfp = tf.name

    def _result(
        proc: subprocess.CompletedProcess,
        *,
        success: bool,
        already_applied: bool = False,
        phase: str,
        hint: Optional[str] = None,
        retry_plan: Optional[str] = None,
    ) -> str:
        stdout_tail = _truncate_text(proc.stdout or "", _LLM_TIMEOUT_OUTPUT_LIMIT)
        stderr_tail = _truncate_text(proc.stderr or "", _LLM_TIMEOUT_OUTPUT_LIMIT)
        result = {
            "success": success or already_applied,
            "rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "dry_run": dry_run,
            "phase": phase,
        }
        if already_applied:
            result["already_applied"] = True
        if not success and not already_applied:
            result["error"] = f"Patch failed to apply (exit code {proc.returncode})"
            if proc.stderr:
                result["error"] += f": {proc.stderr[:500]}"
            if hint:
                result["hint"] = hint
            if retry_plan:
                result["retry_plan"] = retry_plan
        return json.dumps(result)

    def _apply_patch_in_chunks(chunks: Iterable[str], dry_run: bool = False) -> Optional[str]:
        """Attempt to apply each file chunk independently."""
        if not chunks:
            return None

        for idx, chunk in enumerate(chunks, start=1):
            chunk_result = json.loads(apply_patch(chunk, dry_run=dry_run, _allow_chunking=False))
            if not chunk_result.get("success"):
                return json.dumps({
                    "success": False,
                    "rc": chunk_result.get("rc", 1),
                    "dry_run": dry_run,
                    "phase": "chunked",
                    "failed_chunk_index": idx,
                    "error": chunk_result.get("error", "Patch chunk failed to apply"),
                    "retry_plan": _retry_plan_message(len(chunked_parts)),
                })
        return json.dumps({"success": True, "phase": "chunked", "chunks_applied": len(chunked_parts)})

    try:
        strategies = [
            # runner, check_args, use_three_way, apply_override
            ("git", ["git", "apply", "--check", "--inaccurate-eof", "--whitespace=nowarn", "--ignore-whitespace", tfp], False, None),
            ("git", ["git", "apply", "--check", "--inaccurate-eof", "--whitespace=nowarn", "--ignore-whitespace", "-p0", tfp], False, ["git", "apply", "--inaccurate-eof", "--whitespace=nowarn", "--ignore-whitespace", "-p0", tfp]),
            ("git", ["git", "apply", "--check", "--inaccurate-eof", "--whitespace=nowarn", "--ignore-whitespace", "--3way", tfp], True, None),
            ("patch", ["patch", "--batch", "--forward", "--dry-run", "-p1", "-i", tfp], False, None),
            # More lenient patch attempts: ignore whitespace and different strip levels to salvage slightly misaligned diffs
            ("patch", ["patch", "--batch", "--forward", "--dry-run", "--ignore-whitespace", "-p1", "-i", tfp], False, ["patch", "--batch", "--forward", "--ignore-whitespace", "-p1", "-i", tfp]),
            ("patch", ["patch", "--batch", "--forward", "--dry-run", "--ignore-whitespace", "-p0", "-i", tfp], False, ["patch", "--batch", "--forward", "--ignore-whitespace", "-p0", "-i", tfp]),
        ]
        
        if not is_git_repo():
            # Skip git strategies if not a repo to avoid 'fatal: not a git repository'
            strategies = [s for s in strategies if s[0] != "git"]

        check_proc: Optional[subprocess.CompletedProcess] = None
        use_three_way = False
        apply_mode: Optional[str] = None
        apply_override: Optional[list[str]] = None
        
        errors = []

        for runner, check_args, use_three_way_flag, apply_override_args in strategies:
            check_proc = _run_shell(check_args)

            combined_output = (check_proc.stdout + check_proc.stderr).lower()
            if "patch already applied" in combined_output or "previously applied" in combined_output:
                return _result(check_proc, success=True, already_applied=True, phase="check")

            if check_proc.returncode == 0:
                use_three_way = use_three_way_flag
                apply_mode = runner
                apply_override = apply_override_args
                break
            else:
                if "command not found" in check_proc.stderr.lower() or "not recognized" in check_proc.stderr.lower():
                    # Don't clutter with "command not found" if we have other strategies
                    continue
                errors.append(f"{runner}: {check_proc.stderr.strip()}")
        else:
            if is_git_repo():
                reverse_proc = _run_shell(["git", "apply", "--check", "--reverse", "--inaccurate-eof", tfp])
                reverse_output = (reverse_proc.stdout + reverse_proc.stderr).lower()
                if reverse_proc.returncode == 0 or "reversed" in reverse_output:
                    return _result(reverse_proc, success=True, already_applied=True, phase="check")

            if _allow_chunking and not dry_run and len(chunked_parts) > 1:
                chunk_result = _apply_patch_in_chunks(chunked_parts, dry_run=dry_run)
                if chunk_result:
                    return chunk_result

            # If we reached here, all strategies failed.
            # Use the first git error as the primary one, as it's usually most relevant.
            primary_error = errors[0] if errors else "All patch strategies failed"
            if check_proc and check_proc.returncode == -1 and "INTERNAL ERROR" in check_proc.stderr:
                primary_error = check_proc.stderr

            return _result(
                check_proc,
                success=False,
                phase="check",
                hint=large_patch_hint,
                retry_plan=retry_plan,
            )

        if dry_run:
            return _result(check_proc, success=True, phase="check")

        if apply_mode == "git":
            apply_args = ["git", "apply", "--inaccurate-eof", "--whitespace=nowarn", "--ignore-whitespace"]
            if use_three_way:
                apply_args.append("--3way")
            apply_args.append(tfp)
            apply_proc = _run_shell(apply_args)
        else:
            if apply_override:
                apply_proc = _run_shell(apply_override)
            else:
                apply_proc = _run_shell(["patch", "--batch", "--forward", "-p1", "-i", tfp])

        if apply_proc.returncode == 0:
            post_status = _working_tree_snapshot()
            post_contents = _snapshot_paths(patch_paths)

            if patch_paths:
                tree_changed = pre_contents != post_contents
            else:
                tree_changed = pre_status != post_status

            if not tree_changed:
                return json.dumps(
                    {
                        "success": False,
                        "rc": apply_proc.returncode,
                        "stdout": apply_proc.stdout,
                        "stderr": apply_proc.stderr,
                        "dry_run": dry_run,
                        "phase": "apply",
                        "error": (
                            "Patch command reported success, but no working tree changes were detected. "
                            "The patch may already be applied, empty, or truncated; please verify the diff contents "
                            "and file paths."
                        ),
                        "hint": large_patch_hint,
                        "retry_plan": retry_plan,
                    }
                )
            
            # Invalidate cache for all affected files
            from rev.cache import get_file_cache
            file_cache = get_file_cache()
            if file_cache is not None:
                for path_str in patch_paths:
                    file_cache.invalidate_file(config.ROOT / path_str)

        if apply_proc.returncode != 0 and _allow_chunking and not dry_run and len(chunked_parts) > 1:
            chunk_result = _apply_patch_in_chunks(chunked_parts, dry_run=dry_run)
            if chunk_result:
                return chunk_result

        return _result(
            apply_proc,
            success=apply_proc.returncode == 0,
            phase="apply",
            hint=large_patch_hint if apply_proc.returncode != 0 else None,
            retry_plan=retry_plan if apply_proc.returncode != 0 else None,
        )
    finally:
        try:
            os.unlink(tfp)
        except FileNotFoundError:
            pass
        except Exception as e:
            import sys
            print(f"Warning: Failed to clean up temporary patch file {tfp}: {e}", file=sys.stderr)


def git_add(files: str = ".") -> str:
    """Add files to git staging area."""
    if not is_git_repo():
        return json.dumps({"success": False, "error": "Not a git repository"})

    try:
        result = _run_shell(f"git add {quote_cmd_arg(files)}")
        success = result.returncode == 0
        if not success:
            return json.dumps({
                "success": False,
                "error": f"git add failed: {result.stderr}",
                "returncode": result.returncode
            })
        return json.dumps({
            "success": True,
            "added": True,
            "files": files,
            "output": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"})


def git_commit(message: str, add_files: bool = False, files: str = ".") -> str:
    """Commit changes to git.

    Args:
        message: Commit message
        add_files: Whether to add files before committing (default: False)
        files: Files to add if add_files is True (default: ".")
    """
    if not is_git_repo():
        return json.dumps({"success": False, "error": "Not a git repository"})

    try:
        # Optionally add files first
        if add_files:
            add_result = _run_shell(f"git add {quote_cmd_arg(files)}")
            if add_result.returncode != 0:
                return json.dumps({"success": False, "error": f"git add failed: {add_result.stderr}"})

        # Commit
        commit_result = _run_shell(f"git commit -m {quote_cmd_arg(message)}")
        if commit_result.returncode != 0:
            return json.dumps({"success": False, "error": f"git commit failed: {commit_result.stderr}"})

        return json.dumps({
            "success": True,
            "committed": True,
            "message": message,
            "output": commit_result.stdout
        })
    except Exception as e:
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"})


def git_status() -> str:
    """Get git status."""
    if not is_git_repo():
        return json.dumps({"status": "", "returncode": 1, "error": "Not a git repository"})

    try:
        result = _run_shell("git status")
        return json.dumps({
            "status": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_log(count: int = 10, oneline: bool = False) -> str:
    """Get git log."""
    if not is_git_repo():
        return json.dumps({"log": "", "returncode": 1, "error": "Not a git repository"})

    try:
        cmd = f"git log -n {int(count)}"
        if oneline:
            cmd += " --oneline"
        result = _run_shell(cmd)
        return json.dumps({
            "log": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_branch(action: str = "list", branch_name: str = None) -> str:
    """Git branch operations (list, create, switch, current)."""
    if not is_git_repo():
        return json.dumps({"error": "Not a git repository"})

    try:
        if action == "list":
            result = _run_shell("git branch -a")
            return json.dumps({
                "action": "list",
                "branches": result.stdout,
                "returncode": result.returncode
            })
        elif action == "current":
            result = _run_shell("git branch --show-current")
            return json.dumps({
                "action": "current",
                "branch": result.stdout.strip(),
                "returncode": result.returncode
            })
        elif action == "create" and branch_name:
            result = _run_shell(f"git branch {quote_cmd_arg(branch_name)}")
            return json.dumps({
                "action": "create",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        elif action == "switch" and branch_name:
            result = _run_shell(f"git checkout {quote_cmd_arg(branch_name)}")
            return json.dumps({
                "action": "switch",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        else:
            return json.dumps({"error": f"Invalid action or missing branch_name: {action}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Additional Git Operations ==========

def run_cmd(cmd: str | list[str], timeout: int = _DEFAULT_RUN_CMD_TIMEOUT, cwd: Optional[pathlib.Path] = None, *, background: bool = False, env: Optional[dict] = None) -> str:
    """Run a shell command safely with security validation.

    Security:
        All commands are validated before execution. Shell metacharacters
        and non-allowlisted commands are rejected. No shell=True is used.

    Returns:
        JSON string with execution results
    """
    # Short-circuit repeated git clones to an existing destination
    try:
        if isinstance(cmd, str):
            tokens = shlex.split(cmd)
        else:
            tokens = cmd

        if len(tokens) >= 2 and tokens[0] == "git" and tokens[1] == "clone":
            # Identify destination directory if explicitly provided
            # git clone <url> [directory]
            # Ignore options/flags
            args = [t for t in tokens[2:] if not t.startswith("-")]
            dest: Optional[str] = None
            if len(args) >= 2:
                # directory was provided after url
                dest = args[1]
            elif len(args) == 1:
                # only url was provided, dest is basename of url
                url = args[0]
                dest = url.rstrip("/").split("/")[-1].replace(".git", "")

            if dest:
                dest_path = pathlib.Path(dest)
                if not dest_path.is_absolute():
                    # Use module-level ROOT to respect monkeypatching in tests
                    dest_path = ROOT / dest_path

                if dest_path.exists():
                    return json.dumps({
                        "skipped": True,
                        "reason": "destination already exists; skipping git clone",
                        "path": str(dest_path),
                        "cmd": cmd,
                        "rc": 0,
                    })
    except (ValueError, IndexError):
        # If parsing fails, let command_runner handle it
        pass

    # Use safe command runner
    if cwd is not None and not isinstance(cwd, pathlib.Path):
        cwd = pathlib.Path(cwd)

    if background:
        result = run_command_background(cmd, cwd=cwd, env=env)
        return json.dumps(result)

    result = run_command_safe(
        cmd,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        check_interrupt=True,
        env=env,
    )
    # Attach tails for visibility on failures/timeouts
    if result.get("rc", 0) != 0 or result.get("timeout") or result.get("timed_out"):
        result["stdout_tail"] = _truncate_text(result.get("stdout", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
        result["stderr_tail"] = _truncate_text(result.get("stderr", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
        if result.get("timeout") or result.get("timed_out"):
            result["error"] = result.get("error") or f"run_cmd timeout after {timeout}s"
            result["timeout_exceeded"] = True
    result = _maybe_retry_timeout(cmd, timeout, cwd, result, is_tests=False)
    return json.dumps(result)


def _detect_default_test_cmd(root: pathlib.Path) -> Optional[str]:
    """Guess a sensible test command when none is provided."""
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json as _json
            pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts") or {}
            if isinstance(scripts, dict) and "test" in scripts:
                return "npm test"
        except Exception:
            pass

    if (root / "pytest.ini").exists() or (root / "conftest.py").exists() or (root / "pyproject.toml").exists():
        return "pytest -q"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "pom.xml").exists():
        return "mvn test"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "./gradlew test"
    return None


def run_tests(cmd: Optional[str | list[str]] = None, timeout: int = _DEFAULT_RUN_TESTS_TIMEOUT, cwd: Optional[pathlib.Path] = None) -> str:
    """Run test suite safely with security validation.

    Security:
        All commands are validated before execution. Shell metacharacters
        and non-allowlisted commands are rejected. No shell=True is used.

    Returns:
        JSON string with execution results
    """
    from rev.tools.command_runner import run_command_safe

    if cwd is not None and not isinstance(cwd, pathlib.Path):
        cwd = pathlib.Path(cwd)

    resolved_cmd = cmd
    if not resolved_cmd or (isinstance(resolved_cmd, str) and not resolved_cmd.strip()):
        guessed = _detect_default_test_cmd(cwd or config.ROOT)
        if guessed:
            resolved_cmd = guessed
        else:
            return json.dumps({
                "rc": -1,
                "error": "run_tests requires a test command (e.g., 'npm test', 'pytest -q'); none provided and no default could be detected."
            })

    # Force non-interactive mode for npm test to avoid watch hangs
    env = os.environ.copy()
    cmd_text = resolved_cmd if isinstance(resolved_cmd, str) else " ".join(resolved_cmd)
    lowered = cmd_text.lower()
    if "npm test" in lowered or "npm run test" in lowered:
        env.setdefault("CI", "1")
        # If caller didn't specify extra args, add -- --watch=false to disable interactive watch
        if isinstance(resolved_cmd, list) and all(arg not in {"--watch", "--watch=false", "--watchAll", "--watchAll=false"} for arg in resolved_cmd):
            resolved_cmd = resolved_cmd + ["--", "--watch=false"]
        elif isinstance(resolved_cmd, str) and "--watch" not in resolved_cmd:
            resolved_cmd = f"{resolved_cmd} -- --watch=false"

    result = run_command_safe(
        resolved_cmd,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        check_interrupt=True,
        env=env,
    )

    # Attach tails for visibility on failures/timeouts
    if result.get("rc", 0) != 0 or result.get("timeout") or result.get("timed_out"):
        result["stdout_tail"] = _truncate_text(result.get("stdout", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
        result["stderr_tail"] = _truncate_text(result.get("stderr", ""), _LLM_TIMEOUT_OUTPUT_LIMIT)
        if result.get("timeout") or result.get("timed_out"):
            result["error"] = result.get("error") or f"run_tests timeout after {timeout}s"
            result["timeout_exceeded"] = True

    # Detect watch-mode hangs by inspecting output for common watch markers
    watch_markers = (
        "watch usage",
        "press w to show more",
        "press p to filter by a filename",
        "watch mode",
        "press q to quit",
        "waiting for file changes",
        "watching for file changes",
    )
    stdout_lower = (result.get("stdout") or "").lower()
    stderr_lower = (result.get("stderr") or "").lower()
    if any(marker in stdout_lower for marker in watch_markers) or any(marker in stderr_lower for marker in watch_markers):
        result["rc"] = -1
        result["error"] = "Test command appears to be running in watch/interactive mode; rerun with --watch=false or CI=1."

    result = _maybe_retry_timeout(resolved_cmd, timeout, cwd, result, is_tests=True)
    return json.dumps(result)


def _get_detailed_file_structure(root_path=None, max_depth: int = 2, max_files: int = 50):
    """Get detailed file structure for the repository.

    Args:
        root_path: Root directory to scan (defaults to repo root)
        max_depth: Maximum directory depth to scan
        max_files: Maximum number of files to list

    Returns:
        List of file info dicts with paths and types
    """
    if root_path is None:
        root_path = config.ROOT

    from rev.config import EXCLUDE_DIRS
    file_list = []

    def scan_dir(path, depth=0):
        if depth > max_depth or len(file_list) >= max_files:
            return

        try:
            for item in sorted(path.iterdir()):
                if item.name.startswith('.'):
                    continue
                if item.name in EXCLUDE_DIRS:
                    continue

                rel_path = str(item.relative_to(root_path))
                file_type = "directory" if item.is_dir() else "file"

                file_list.append({
                    "path": rel_path,
                    "type": file_type,
                    "depth": depth
                })

                if item.is_dir() and depth < max_depth:
                    scan_dir(item, depth + 1)
        except (PermissionError, OSError):
            pass

    scan_dir(root_path)
    return file_list


def get_repo_context(commits: int = 6) -> str:
    """Get repository context with detailed file structure."""
    from rev.cache import get_repo_cache

    # Try to get from cache first
    repo_cache = get_repo_cache()
    if repo_cache is not None:
        cached_context = repo_cache.get_context()
        if cached_context is not None:
            return cached_context

    # Generate context
    if is_git_repo():
        st = _run_shell("git status -s")
        lg = _run_shell(f"git log -n {int(commits)} --oneline")

        # If git commands failed (e.g., low memory / paging file error), surface a minimal context and skip crashing.
        if st.returncode != 0 or lg.returncode != 0:
            error_msg = st.stderr or lg.stderr or "git commands failed"
            return json.dumps({
                "status": st.stdout,
                "log": lg.stdout,
                "error": error_msg,
                "note": "git status/log unavailable (likely low memory); continuing with partial context",
            })
        
        status_out = st.stdout
        log_out = lg.stdout
    else:
        status_out = ""
        log_out = ""

    from rev.config import EXCLUDE_DIRS
    top = []
    for p in sorted(config.ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})

    # Include detailed file structure for better CodeWriterAgent context
    file_structure = _get_detailed_file_structure(max_depth=2, max_files=100)

    context = json.dumps({
        "status": status_out,
        "log": log_out,
        "top_level": top[:100],
        "file_structure": file_structure[:50],  # Include key files and directories
        "file_structure_note": "Key files in repository for reference when writing code"
    })

    # Cache it
    if repo_cache is not None:
        repo_cache.set_context(context)

    return context
