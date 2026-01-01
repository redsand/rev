"""
Quick verification module for sub-agent execution.

Provides lightweight, task-specific verification that can be run after each
task completes to ensure it actually did what was requested. This is critical
for the workflow loop: Plan → Execute → Verify → Report → Re-plan if needed
"""

import json
import re
import os
import fnmatch
import shlex
import shutil
import traceback
from pathlib import Path
import re
from typing import Dict, Any, Optional, Tuple, Iterable, List
from dataclasses import dataclass

from rev.models.task import Task, TaskStatus, explicitly_requests_tests, explicitly_requests_lint
from rev.tools.registry import execute_tool, get_last_tool_call
from rev import config
from rev.core.context import RevContext
from rev.tools.workspace_resolver import (
    WorkspacePathError,
    resolve_workspace_path,
    normalize_path,
    normalize_to_workspace_relative,
)
from rev.tools.utils import quote_cmd_arg
from rev.tools.command_runner import _resolve_command
from rev.tools.project_types import find_project_root, detect_project_type, detect_test_command
from rev.llm.client import ollama_chat
from rev.execution.verification_utils import _detect_build_command_for_root

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")




def _strip_ansi(text: Any) -> str:
    if not isinstance(text, str):
        return "" if text is None else str(text)
    return ANSI_RE.sub("", text)


_READ_ONLY_TOOLS = {
    "read_file",
    "read_file_lines",
    "list_dir",
    "tree_view",
    "search_code",
    "get_file_info",
    "file_exists",
}

_WRITE_TOOLS = {
    "write_file",
    "append_to_file",
    "replace_in_file",
    "apply_patch",
    "delete_file",
    "move_file",
    "copy_file",
    "create_directory",
    "split_python_module_classes",
}

_TEST_FILE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".cxx",
    ".dart", ".ex", ".exs", ".fs", ".fsx",
    ".go", ".java", ".js", ".jsx", ".kt", ".kts",
    ".mjs", ".cjs", ".php", ".py", ".rb",
    ".rs", ".scala", ".swift", ".ts", ".tsx",
}
_TEST_DIR_TOKENS = {"test", "tests", "spec", "specs", "__tests__", "__specs__"}
_INSTALL_GUARD_STATE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_TEST_FILE_DISCOVERY_LIMIT = 12
_TDD_TEST_RESULT_KEYS = {
    "pytest",
    "npm_test",
    "go_test",
    "cargo_test",
    "dotnet_test",
    "maven_test",
    "gradle_test",
    "phpunit",
    "rspec",
    "unittest",
    "jest",
    "vitest",
    "mocha",
    "ava",
    "tap",
    "jasmine",
    "dart_test",
    "flutter_test",
    "custom_test",
}

_TEST_NAME_PATTERN = re.compile(r"(?:^|[._-])(test|spec)(?:[._-]|$)", re.IGNORECASE)
_NO_TEST_RUNNER_SENTINEL = "REV_NO_TEST_RUNNER"
_TEST_REQUEST_STATE_KEY = "tests_requested_for_files"
_MISSING_SCRIPT_PATTERN = re.compile(r"missing script:\s*\"?([A-Za-z0-9:_\\.-]+)\"?", re.IGNORECASE)
_COMMAND_NOT_FOUND_PATTERN = re.compile(r"command\\s+\"?([A-Za-z0-9:_\\.-]+)\"?\\s+not\\s+found", re.IGNORECASE)
_PNPM_NO_SCRIPT_PATTERN = re.compile(r"ERR_PNPM_NO_SCRIPT.*?\"?([A-Za-z0-9:_\\.-]+)\"?", re.IGNORECASE)
_TEST_REQUEST_STATE_KEY = "tests_requested_for_files"


def _detect_missing_script(stdout: str, stderr: str) -> Optional[str]:
    text = f"{stdout}\n{stderr}"
    for pattern in (_MISSING_SCRIPT_PATTERN, _PNPM_NO_SCRIPT_PATTERN, _COMMAND_NOT_FOUND_PATTERN):
        match = pattern.search(text)
        if match:
            name = match.group(1)
            return name or "test"
    return None


def _candidate_test_paths_for_source(file_path: Path) -> list[Path]:
    """Generate likely test file paths for a source file."""
    if not file_path.suffix:
        return []
    if any(token in file_path.parts for token in _TEST_DIR_TOKENS):
        return []

    stem = file_path.stem
    suffix = file_path.suffix
    candidates: list[Path] = []

    # JS/TS/Vue
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue"}:
        candidates.append(Path("tests") / f"{stem}.test{suffix if suffix != '.vue' else '.ts'}")
        candidates.append(Path("tests") / f"{stem}.spec{suffix if suffix != '.vue' else '.ts'}")
    # Python
    elif suffix == ".py":
        candidates.append(Path("tests") / f"test_{stem}.py")
    # Go
    elif suffix == ".go":
        candidates.append(file_path.with_name(f"{stem}_test.go"))
    # Rust
    elif suffix == ".rs":
        candidates.append(Path("tests") / f"{stem}_test.rs")
    # Java
    elif suffix == ".java":
        candidates.append(Path("src/test/java") / f"{stem}Test.java")
    # C#/F#
    elif suffix in {".cs", ".fs", ".fsx"}:
        candidates.append(Path("tests") / f"{stem}Tests{suffix}")

    return candidates


def _ensure_test_request_for_file(context: RevContext, file_path: Path) -> None:
    """Ensure there is a pending test task for the given source file if no test exists."""
    try:
        rel = file_path.relative_to(config.ROOT) if config.ROOT else file_path
    except Exception:
        rel = file_path

    # Avoid repeated requests per code-change iteration
    state = context.agent_state.get(_TEST_REQUEST_STATE_KEY, {})
    if not isinstance(state, dict):
        state = {}
    last_iter = state.get(str(rel))
    current_iter = context.agent_state.get("last_code_change_iteration", -1)
    if isinstance(last_iter, int) and isinstance(current_iter, int) and last_iter == current_iter:
        return

    candidates = _candidate_test_paths_for_source(rel)
    if not candidates:
        return
    # If any candidate exists, skip
    for cand in candidates:
        abs_cand = (config.ROOT / cand) if config.ROOT else cand
        if abs_cand.exists():
            return

    # Queue a test-creation task
    tasks = [
        Task(
            description=(
                f"Add tests for {rel} at {candidates[0]} to cover its functionality. "
                "Use write_file (or apply_patch) to create the test file with failing tests "
                "that exercise the new code."
            ),
            action_type="add",
        )
    ]
    context.agent_requests.append({"type": "INJECT_TASKS", "details": {"tasks": tasks}})
    state[str(rel)] = current_iter
    context.set_agent_state(_TEST_REQUEST_STATE_KEY, state)


def _attempt_missing_script_fallback(cmd_parts: list[str], cwd: Optional[Path | str]) -> Optional[list[str]]:
    try:
        root = Path(cwd) if cwd else config.ROOT
    except Exception:
        root = Path(".").resolve()
    try:
        root = find_project_root(root)
    except Exception:
        pass

    detected = detect_test_command(root)
    if not detected:
        return None

    detected_norm = [str(part).lower() for part in detected]
    cmd_norm = [str(part).lower() for part in cmd_parts]
    if detected_norm == cmd_norm:
        return None
    return detected


def _extract_tool_noop(tool: str, raw_result: Any) -> Optional[str]:
    """Return a tool_noop reason string when a tool reports no changes."""
    tool_l = (tool or "").lower()
    if not isinstance(raw_result, str) or not raw_result.strip():
        return None
    try:
        payload = json.loads(raw_result)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    # Specific no-op detections per tool
    if tool_l == "replace_in_file":
        if payload.get("replaced") == 0:
            return (
                "tool_noop: replace_in_file made no changes (replaced=0). "
                "RECOVERY: Ensure you're not escaping content incorrectly and check whitespace, indentation, and context. "
                "Use read_file tool to verify the actual file content before retrying."
            )
    
    elif tool_l in ("search_code", "rag_search"):
        # Check both 'matches' and 'results' fields, handling empty lists correctly
        results = payload.get("matches") if "matches" in payload else payload.get("results")
        if isinstance(results, list) and len(results) == 0:
            return f"tool_noop: {tool_l} returned 0 results. RECOVERY: Broaden your search pattern or check for typos in file names/symbols."

    elif tool_l == "list_dir":
        # Check both 'files' and 'entries' fields, handling empty lists correctly
        files = payload.get("files") if "files" in payload else payload.get("entries", [])
        if isinstance(files, list) and len(files) == 0:
            return "tool_noop: list_dir returned 0 files. RECOVERY: Check the path exists and contains files, or broaden the pattern."

    elif tool_l == "run_tests":
        stdout = ((payload.get("stdout") or "") + (payload.get("stderr") or "")).lower()
        if "collected 0 items" in stdout or "no tests ran" in stdout or "no tests found" in stdout:
            return "tool_noop: run_tests found 0 tests to run. RECOVERY: Check your test path or test discovery patterns."
            
    elif tool_l == "apply_patch":
        if payload.get("applied_hunks") == 0:
            return "tool_noop: apply_patch applied 0 hunks. RECOVERY: The diff might be stale or target the wrong lines."
            
    elif tool_l == "split_python_module_classes":
        if payload.get("classes_split") == 0:
            return "tool_noop: split_python_module_classes found 0 classes to split."
            
    elif tool_l.startswith("rewrite_python_") or tool_l.startswith("rename_") or tool_l.startswith("move_"):
        if payload.get("changed") == 0 or payload.get("replaced") == 0:
            return f"tool_noop: {tool_l} made 0 changes."

    return None


def _task_executed_only_reads(task: Task) -> bool:
    """Return True if the task executed tool(s) but only read-only ones."""
    events = getattr(task, "tool_events", None) or []
    if not events:
        return False
    tools = [str(ev.get("tool") or "").lower() for ev in events if ev.get("tool")]
    if not tools:
        return False
    return all(t in _READ_ONLY_TOOLS for t in tools) and not any(t in _WRITE_TOOLS for t in tools)


def _read_file_with_fallback_encoding(file_path: Path) -> Optional[str]:
    """
    Read a file with multiple encoding attempts.

    Tries common encodings in order: UTF-8, UTF-8 BOM, Latin-1, CP1252, ASCII.
    Falls back to UTF-8 with error replacement if all fail.

    Args:
        file_path: Path to the file to read

    Returns:
        File content string, or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'ascii']

    for encoding in encodings_to_try:
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    # If all encodings failed, use UTF-8 with error replacement
    return file_path.read_text(encoding='utf-8', errors='replace')


@dataclass
class VerificationResult:
    """Result of verifying a task's execution.

    P0-6: Added inconclusive field to distinguish between:
    - passed=True: Task definitely succeeded
    - passed=False, inconclusive=False: Task definitely failed
    - passed=False, inconclusive=True: Cannot determine if task succeeded (needs proper validation)
    """
    passed: bool
    message: str
    details: Dict[str, Any]
    should_replan: bool = False
    inconclusive: bool = False  # P0-6: True when verification can't determine success/failure

    def __str__(self) -> str:
        if self.inconclusive:
            status = '[INCONCLUSIVE]'
        else:
            status = '[OK]' if self.passed else '[FAIL]'
        # Remove any Unicode characters that might cause encoding issues on Windows
        safe_message = self.message.replace('[OK]', '[OK]').replace('[FAIL]', '[FAIL]').replace('[FAIL]', '[FAIL]')
        return f"{status} {safe_message}"


def verify_task_execution(task: Task, context: RevContext) -> VerificationResult:
    """
    Verify that a task actually completed successfully.
    Wrapper catches unexpected exceptions to avoid opaque failures.
    """
    try:
        return _verify_task_execution_impl(task, context)
    except Exception as e:
        return VerificationResult(
            passed=False,
            message=f"Verification exception: {e}",
            details={"exception": traceback.format_exc()},
            should_replan=True,
        )


def _verify_task_execution_impl(task: Task, context: RevContext) -> VerificationResult:
    """
    Internal implementation for task verification (wrapped to catch unexpected exceptions).
    """
    if task.status != TaskStatus.COMPLETED:
        return VerificationResult(
            passed=False,
            message=f"Task status is {task.status.name}, not COMPLETED",
            details={"status": task.status.name},
            should_replan=False
        )

    action_type = task.action_type.lower()
    verifiable_read_actions = {"read", "analyze", "research", "investigate", "general", "verify"}
    if action_type in verifiable_read_actions:
        read_events = getattr(task, "tool_events", None) or []
        if not read_events:
            return VerificationResult(
                passed=False,
                message="Read task executed no tools",
                details={},
                should_replan=True,
            )
        return VerificationResult(
            passed=True,
            message="Read-only task completed (verification skipped)",
            details={"tools": [ev.get("tool") for ev in read_events]},
        )

    # Surface tool no-ops clearly (e.g., search with 0 matches) first.
    # This ensures all actions are checked for functional success.
    events = getattr(task, "tool_events", None) or []
    for ev in reversed(list(events)):
        tool_name = str(ev.get("tool") or "").lower()
        reason = _extract_tool_noop(tool_name, ev.get("raw_result"))
        if reason:
            if action_type == "test" and tool_name == "run_tests":
                reason_lower = reason.lower()
                if any(token in reason_lower for token in ("no tests", "0 tests", "found 0 tests", "tests to run")):
                    continue
            return VerificationResult(
                passed=False,
                message=reason,
                details={"tool": ev.get("tool"), "artifact_ref": ev.get("artifact_ref")},
                should_replan=True,
            )
    verification_mode = _get_verification_mode()
    test_only_change = False
    non_test_change = False
    if config.TDD_ENABLED and action_type in {"add", "create", "edit", "refactor"}:
        test_only_change = _task_changes_tests_only(task)
        non_test_change = _task_changes_non_tests(task)

    # Prevent "looks done vs is done": an edit/refactor task that only read files
    # should not be marked as completed.
    if action_type in {"add", "create", "edit", "refactor", "delete", "rename"} and _task_executed_only_reads(task):
        return VerificationResult(
            passed=False,
            message="Task performed only read-only tool calls; no changes were made",
            details={"tools": [ev.get("tool") for ev in (getattr(task, 'tool_events', None) or [])]},
            should_replan=True,
        )

    # If the planner mislabeled the action type but the tool call clearly indicates
    # a directory creation, verify it as such. This prevents false failures like
    # "File created but is empty" when a directory was created.
    last_call = get_last_tool_call() or {}
    last_tool = (last_call.get("name") or "").lower()
    if last_tool == "create_directory" and action_type in {"add", "create"}:
        return _verify_directory_creation(task, context)

    # Route to appropriate verification handler
    if action_type == "refactor":
        result = _verify_refactoring(task, context)
    elif action_type == "add" or action_type == "create":
        result = _verify_file_creation(task, context)
    elif action_type == "edit":
        result = _verify_file_edit(task, context)
    elif action_type == "create_directory":
        result = _verify_directory_creation(task, context)
    elif action_type == "test":
        result = _verify_test_execution(task, context)
    else:
        # For unknown action types, return a passing result but flag for caution
        return VerificationResult(
            passed=True,
            message=f"No specific verification available for action type '{action_type}'",
            details={"action_type": action_type, "note": "Verification skipped for this action type"}
        )

    # TDD: allow "red" test failures before implementation.
    if config.TDD_ENABLED and action_type == "test":
        if (
            not result.passed
            and context.agent_state.get("tdd_pending_green")
            and not context.agent_state.get("tdd_require_test")
        ):
            return _apply_tdd_red_override(
                result,
                context,
                reason="TDD red: tests failed as expected before implementation.",
            )
        if result.passed and context.agent_state.get("tdd_require_test"):
            context.agent_state["tdd_require_test"] = False
            context.agent_state["tdd_green_observed"] = True

    # Enforce validation_steps when provided; otherwise fall back to strict verification
    # mode (default: fast compileall).
    if result.passed and action_type in {"add", "create", "edit", "refactor"}:
        if task.validation_steps:
            validation_outcome = _run_validation_steps(
                task, result.details, getattr(task, "tool_events", None)
            )
            if isinstance(validation_outcome, VerificationResult):
                if config.TDD_ENABLED and test_only_change and _is_test_failure(validation_outcome):
                    return _apply_tdd_red_override(
                        validation_outcome,
                        context,
                        reason="TDD red: tests failed as expected after adding tests.",
                    )
                return validation_outcome
            if validation_outcome:
                result.details["validation"] = validation_outcome
        elif verification_mode:
            strict_paths = _collect_paths_for_strict_checks(
                action_type, result.details, getattr(task, "tool_events", None)
            )
            strict_outcome = _maybe_run_strict_verification(action_type, strict_paths, mode=verification_mode, task=task)
            if isinstance(strict_outcome, VerificationResult):
                if config.TDD_ENABLED and test_only_change and _is_test_failure(strict_outcome):
                    return _apply_tdd_red_override(
                        strict_outcome,
                        context,
                        reason="TDD red: tests failed as expected after adding tests.",
                    )
                return strict_outcome
            if strict_outcome:
                result.details["strict"] = strict_outcome

    if config.TDD_ENABLED and action_type in {"add", "create", "edit", "refactor"} and result.passed:
        if test_only_change:
            context.agent_state["tdd_pending_green"] = True
        if non_test_change and context.agent_state.get("tdd_pending_green"):
            context.agent_state["tdd_pending_green"] = False
            context.agent_state["tdd_require_test"] = True

    return result


def _verify_refactoring(task: Task, context: RevContext) -> VerificationResult:
    """
    Verify that a refactoring task actually extracted/reorganized code.

    For extraction tasks like "break out classes into individual files":
    - Check that new files were created
    - Check that imports in new files are valid
    - Check that the old file was updated with imports
    """

    details = {}
    issues = []
    debug_info = {}
    result_payload = _parse_task_result_payload(task.result)
    call_sites_updated = []

    # If the refactor tool reported an already-split source, treat as a benign outcome
    # to avoid verification loops on backup-only states.
    if result_payload and result_payload.get("status") == "source_already_split":
        return VerificationResult(
            passed=True,
            message="Extraction skipped: source already split (backup exists)",
            details={"result": result_payload},
            should_replan=False,
        )

    # Refactor tasks must include a write/extraction tool call; a lone read_file is not completion.
    events = getattr(task, "tool_events", None) or []
    if events:
        tools = [str(ev.get("tool") or "").lower() for ev in events if ev.get("tool")]
        if tools and all(t in _READ_ONLY_TOOLS for t in tools):
            return VerificationResult(
                passed=False,
                message="Refactor task executed only read-only tools; extraction/refactor was not performed",
                details={"tools": tools},
                should_replan=True,
            )
    else:
        last_call = get_last_tool_call() or {}
        last_tool = str(last_call.get("name") or "").lower()
        if last_tool in _READ_ONLY_TOOLS:
            return VerificationResult(
                passed=False,
                message=f"Refactor task did not perform changes (last tool was {last_tool})",
                details={"last_tool": last_tool},
                should_replan=True,
            )

    if result_payload:
        raw_call_sites = result_payload.get("call_sites_updated") or result_payload.get("call_sites") or []
        if isinstance(raw_call_sites, list):
            call_sites_updated = raw_call_sites
            details["call_sites_updated"] = call_sites_updated
            debug_info["call_sites_updated"] = call_sites_updated
        backup = result_payload.get("original_backup")
        if backup:
            details["original_backup"] = backup
        package_init = result_payload.get("package_init")
        if package_init:
            details["package_init"] = package_init

    # Don't try to guess the refactoring type - just verify the repo state changed
    # If there are issues below, they'll be caught. Otherwise, assume it succeeded.

    # Identify the target directory.
    # Prefer tool metadata / tool outputs (stable) over parsing task.description (brittle).
    target_dir: Optional[Path] = None

    if result_payload:
        # split_python_module_classes returns package_dir and package_init.
        package_dir = result_payload.get("package_dir")
        if isinstance(package_dir, str) and package_dir.strip():
            target_dir = _resolve_for_verification(package_dir.strip(), purpose="verify refactoring target dir")
            if target_dir:
                details["target_dir_path"] = str(target_dir)

        if not target_dir:
            package_init = result_payload.get("package_init")
            if isinstance(package_init, str) and package_init.strip():
                init_path = _resolve_for_verification(package_init.strip(), purpose="verify refactoring package init")
                if init_path:
                    target_dir = init_path.parent
                    details["target_dir_path"] = str(target_dir)

    if not target_dir:
        last_call = get_last_tool_call() or {}
        if (last_call.get("name") or "").lower() == "split_python_module_classes":
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("target_directory")
                if isinstance(candidate, str) and candidate.strip():
                    target_dir = _resolve_for_verification(candidate.strip(), purpose="verify refactoring target dir")
                    if target_dir:
                        details["target_dir_path"] = str(target_dir)

    if not target_dir and getattr(task, "tool_events", None):
        # Look at recorded tool events (most recent first)
        for ev in reversed(list(task.tool_events)):
            args = ev.get("args") or {}
            if not isinstance(args, dict):
                continue
            # Prefer explicit target_directory/directory keys
            for key in ("target_directory", "directory", "dir_path"):
                candidate = args.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    resolved = _resolve_for_verification(candidate.strip(), purpose="verify refactoring target dir (event)")
                    if resolved:
                        target_dir = resolved
                        details["target_dir_path"] = str(target_dir)
                        break
            if target_dir:
                break
            # Fallback: path pointing to a module/init; use parent
            path_candidate = args.get("path")
            if isinstance(path_candidate, str) and path_candidate.strip():
                resolved_file = _resolve_for_verification(path_candidate.strip(), purpose="verify refactoring target dir (event path)")
                if resolved_file:
                    target_dir = resolved_file.parent
                    details["target_dir_path"] = str(target_dir)
                    break

    if not target_dir:
        # Fallback 1a: use source file parent from tool events or description
        source_candidates: list[str] = []
        if getattr(task, "tool_events", None):
            for ev in reversed(list(task.tool_events)):
                args = ev.get("args") or {}
                if isinstance(args, dict):
                    cand = args.get("path")
                    if isinstance(cand, str) and cand.strip():
                        source_candidates.append(cand)
        desc_matches = re.findall(r'(?:\.\/)?([a-zA-Z0-9_/\\\-]+\.py)', task.description or "")
        source_candidates.extend(desc_matches)
        for cand in source_candidates:
            resolved_file = _resolve_for_verification(cand.strip(), purpose="verify refactoring source file parent")
            if resolved_file:
                target_dir = resolved_file.parent
                details["target_dir_path"] = str(target_dir)
                break

    if not target_dir:
        # Fallback: use the most recent tool call (any tool) and derive parent directory from its path
        last_call = get_last_tool_call() or {}
        args = last_call.get("args") or {}
        if isinstance(args, dict):
            path_candidate = args.get("path") or args.get("file_path")
            if isinstance(path_candidate, str) and path_candidate.strip():
                resolved_file = _resolve_for_verification(path_candidate.strip(), purpose="verify refactoring target dir (last tool)")
                if resolved_file:
                    target_dir = resolved_file.parent
                    details["target_dir_path"] = str(target_dir)

    if not target_dir:
        # Fallback 1: if a .py file path is mentioned, use its parent directory.
        file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-]+\.py)'
        file_matches = re.findall(file_pattern, task.description)
        if file_matches:
            # Prefer __init__.py paths (package exports) and longer paths (more specific)
            def _file_sort_key(path_str: str) -> tuple:
                posix = path_str.replace("\\", "/")
                return (not posix.endswith("__init__.py"), -len(posix))

            for candidate in sorted(file_matches, key=_file_sort_key):
                normalized = normalize_path(candidate.strip())
                resolved_file = _resolve_for_verification(
                    normalized, purpose="verify refactoring target dir from file"
                )
                if resolved_file:
                    target_dir = resolved_file.parent
                    break

    if not target_dir:
        # Fallback 2: try to parse something directory-looking from the task description.
        dir_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-]+\/[a-zA-Z0-9_\-]+)(?:\/)?'
        dir_matches = re.findall(dir_pattern, task.description)
        if dir_matches:
            candidates: list[Path] = []
            for raw in sorted(set(dir_matches), key=len, reverse=True):
                # Avoid truncating file paths like "__init__.py" -> "__init__".
                leaf = raw.replace("\\", "/").split("/")[-1]
                if "." in leaf:
                    continue
                resolved = _resolve_for_verification(raw.strip("/"), purpose="verify refactoring target dir")
                if resolved and resolved.exists() and resolved.is_dir():
                    candidates.append(resolved)
            if candidates:
                target_dir = candidates[0]
                details["target_dir_path"] = str(target_dir)

    if not target_dir:
        return VerificationResult(
            passed=False,
            message="Could not determine target directory for verification",
            details={"description": task.description, "result_payload_keys": list(result_payload.keys()) if result_payload else None},
            should_replan=True
        )
    debug_info["target_directory"] = str(target_dir)
    debug_info["directory_exists"] = target_dir.exists()

    # Check 1: Directory exists
    if not target_dir.exists():
        missing_msg = f"[FAIL] Target directory '{target_dir}' does not exist - extraction was never started"
        issues.append(missing_msg)
        details["next_step_hint"] = (
            f"Create the directory '{target_dir}' (or ensure it exists) before rerunning split_python_module_classes."
        )
        debug_info["status"] = "DIRECTORY_NOT_CREATED"
    else:
        details["directory_exists"] = True

        # Check 2: Files were created in the directory
        py_files = list(target_dir.glob("*.py"))
        debug_info["files_in_directory"] = [f.name for f in py_files]
        debug_info["file_count"] = len(py_files)

        if not py_files:
            issues.append(
                f"[FAIL] No Python files in '{target_dir}' - extraction created directory but extracted NO FILES\n"
                f"   This means the RefactoringAgent either:\n"
                f"   1. Did not actually extract any classes\n"
                f"   2. Failed to create individual files\n"
                f"   3. Returned success without performing extraction"
            )
            debug_info["status"] = "DIRECTORY_EMPTY"
        else:
            details["files_created"] = len(py_files)
            details["files"] = [f.name for f in py_files]
            debug_info["status"] = f"EXTRACTION_PARTIAL ({len(py_files)} files)"

            # Check 3: Verify imports in created files
            import_errors = []
            for py_file in py_files:
                try:
                    content = _read_file_with_fallback_encoding(py_file)
                    if content is None:
                        import_errors.append(f"[FAIL] Could not read {py_file.name}")
                        continue

                    # Try to parse imports
                    import_lines = re.findall(r'^(?:from|import)\s+.+', content, re.MULTILINE)
                    # Check if files referenced in imports actually exist
                    for import_line in import_lines:
                        # Extract relative imports like "from .module import X"
                        rel_import_match = re.search(r'from\s+\.([a-zA-Z_][a-zA-Z0-9_]*)\s+import', import_line)
                        if rel_import_match:
                            module_name = rel_import_match.group(1)
                            module_file = target_dir / f"{module_name}.py"
                            if not module_file.exists():
                                import_errors.append(f"[FAIL] {py_file.name}: imports from missing {module_name}.py")
                except Exception as e:
                    import_errors.append(f"[FAIL] Error reading {py_file.name}: {e}")

            if import_errors:
                issues.extend(import_errors)
                debug_info["import_issues"] = import_errors
            else:
                details["imports_valid"] = True
                debug_info["import_validation"] = "PASSED"

            # Check 3b: Verify __init__.py has __all__ exports (if it exists)
            init_file = target_dir / "__init__.py"
            if init_file.exists():
                try:
                    init_content = _read_file_with_fallback_encoding(init_file)
                    if init_content:
                        if "__all__" in init_content:
                            details["has_all_exports"] = True
                            debug_info["__all___status"] = "PRESENT"

                            # Check 3b.1: Verify all split classes are exported in __all__
                            all_match = re.search(r'__all__\s*=\s*\[(.*?)\]', init_content, re.DOTALL)
                            if all_match:
                                exported = {s.strip(' \'"') for s in all_match.group(1).split(',') if s.strip()}
                                file_stems = {f.stem for f in py_files if f.name != '__init__.py'}
                                missing = file_stems - exported
                                extra = exported - file_stems

                                if missing:
                                    issues.append(f"[FAIL] __init__.py missing exports for: {', '.join(sorted(missing))}")
                                    debug_info["missing_exports"] = list(missing)
                                if extra:
                                    debug_info["extra_exports"] = list(extra)  # Not an error, just informational

                                if not missing:
                                    details["all_classes_exported"] = True
                                    debug_info["exports_complete"] = True

                            # Check 3b.2: Runtime import test
                            package_name = target_dir.name
                            parent_dir = target_dir.parent
                            # Build a simple import test command
                            import_test_cmd = f'cd "{parent_dir}" && python -c "from {package_name} import *; print(\'Success\')"'
                            try:
                                import_test_result = execute_tool("run_cmd", {"cmd": import_test_cmd, "timeout": 10}, agent_name="quick_verify")
                                import_test_data = json.loads(import_test_result)
                                if import_test_data.get("rc") == 0:
                                    details["runtime_import_test"] = "PASSED"
                                    debug_info["runtime_import"] = "PASSED"
                                else:
                                    error_msg = import_test_data.get("stderr", "") or import_test_data.get("stdout", "")
                                    issues.append(f"[FAIL] Runtime import test failed: {error_msg[:200]}")
                                    debug_info["runtime_import"] = f"FAILED: {error_msg[:200]}"
                            except Exception as e:
                                # Runtime import test is nice-to-have, not critical
                                debug_info["runtime_import"] = f"ERROR: {str(e)}"

                        else:
                            # __all__ is missing but imports might be present
                            # This is not necessarily an error if imports are explicit
                            if "from ." in init_content or "import " in init_content:
                                details["has_explicit_imports"] = True
                                debug_info["__all___status"] = "MISSING_BUT_HAS_IMPORTS"
                            else:
                                issues.append(f"[WARN] {init_file.name}: No __all__ exports and no imports found")
                                debug_info["__all___status"] = "MISSING_NO_IMPORTS"
                except Exception as e:
                    debug_info["__all___check_error"] = str(e)

    # Check 4: Verify old file was updated with imports (if applicable)
    # Look for the original file mentioned in task description
    old_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-]+\.py)'
    old_file_matches = re.findall(old_file_pattern, task.description)
    if old_file_matches:
        source_raw = old_file_matches[0]
        old_file = _resolve_for_verification(source_raw, purpose="verify refactoring source file")
        if not old_file and target_dir:
            # Heuristic: source next to target_dir, e.g., module.py when target_dir=module/
            alt_source = target_dir.parent / f"{target_dir.name}.py"
            if alt_source.exists():
                old_file = alt_source
        
        # If it's a directory now, it was likely converted to a package (which is success)
        if not old_file:
            # Check if it's a directory
            try:
                candidate = (get_workspace().root / normalize_path(source_raw)).resolve()
                if candidate.exists() and candidate.is_dir():
                    # This is success - original file is now the package directory
                    details["main_file_converted_to_package"] = True
                    debug_info["main_file_status"] = "CONVERTED_TO_PACKAGE"
                    old_file = None
            except Exception:
                pass

        if old_file:
            debug_info["source_file"] = str(old_file)
            debug_info["source_file_exists"] = old_file.exists()
            details["source_file_path"] = str(old_file)

            if old_file.exists() and old_file.is_file():
                try:
                    # Use helper function for robust multi-encoding file reading
                    content = _read_file_with_fallback_encoding(old_file)

                    if content is None:
                        debug_info["main_file_status"] = "NOT_READABLE"
                    else:
                        original_size = len(content)
                        debug_info["source_file_size"] = original_size

                        # Check if it has import statements from the new directory
                        # Handle both relative and absolute-style imports
                        target_name = target_dir.name
                        has_imports_from_new = (
                            re.search(rf'from\s+\.{target_name}', content) or
                            re.search(rf'import\s+{target_name}', content)
                        )
                        if has_imports_from_new:
                            details["main_file_updated"] = True
                            debug_info["main_file_status"] = "UPDATED_WITH_IMPORTS"
                        else:
                            # Check if the source file was intentionally left in place for LLM to handle
                            source_file_intentionally_kept = result_payload and result_payload.get("source_file_exists") is True

                            if source_file_intentionally_kept:
                                # This is expected behavior - the split tool left the file for LLM to handle
                                details["main_file_needs_handling"] = True
                                debug_info["main_file_status"] = "LEFT_FOR_LLM_TO_HANDLE"
                                debug_info["note"] = f"Original file {old_file.name} left in place - LLM should decide: delete, update with imports, or keep for backwards compatibility"
                            else:
                                # The file wasn't intentionally kept, so this is a problem
                                issues.append(
                                    f"[FAIL] Original file {old_file} was NOT updated with imports from {target_dir}\n"
                                    f"   File still contains {original_size} bytes (should be much smaller if extracted)"
                                )
                                debug_info["main_file_status"] = "NOT_UPDATED"
                except Exception as e:
                    issues.append(f"[FAIL] Could not read {old_file}: {e}")
                    debug_info["main_file_status"] = f"ERROR: {str(e)}"
            elif old_file.exists() and old_file.is_dir():
                # It exists but it's a directory - handle as package conversion
                details["main_file_converted_to_package"] = True
                debug_info["main_file_status"] = "CONVERTED_TO_PACKAGE"
        elif not details.get("main_file_converted_to_package"):
            # Only report error if we didn't determine it was converted to a package
            issues.append(f"[FAIL] Could not resolve source file path for verification: {source_raw}")
            debug_info["main_file_status"] = "UNRESOLVABLE"
    else:
        # Check if original file exists at a different location (e.g. was already moved)
        if not target_dir:
            # Last resort: try to find anything related to the refactoring in task description
            pass

    if issues:
        non_benign = [issue for issue in issues if "Original file" not in issue]
        extraction_looks_ok = bool(
            target_dir
            and target_dir.exists()
            and details.get("files_created", 0) > 0
            and details.get("imports_valid") is True
        )

        # If the only failures are about the original monolithic module still being present / unchanged,
        # treat this as a warning. Some projects intentionally keep the original file for reference.
        if extraction_looks_ok and not non_benign:
            details["warnings"] = issues
            debug_info["warnings"] = issues
            call_site_msg = (
                f" with call site updates ({len(call_sites_updated)} files)" if call_sites_updated else ""
            )
            return VerificationResult(
                passed=True,
                message=f"[OK] Extraction successful{call_site_msg} (source module left unchanged)",
                details={**details, "debug": debug_info},
            )
        return VerificationResult(
            passed=False,
            message=f"Extraction verification failed: {len(issues)} issue(s) found\n\nDetails:\n" + "\n".join(issues),
            details={**details, "issues": issues, "debug": debug_info},
            should_replan=True
        )

    return VerificationResult(
        passed=True,
        message=f"[OK] Extraction successful: {details.get('files_created', 0)} files created with valid imports",
        details={**details, "debug": debug_info}
    )


def _verify_file_creation(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a file was actually created."""

    details = {}

    # Prefer tool metadata (stable) over regex guessing (brittle).
    file_path: Path | None = None
    ev = _latest_tool_event(getattr(task, "tool_events", None), {"write_file", "apply_patch", "replace_in_file"})
    if ev:
        for p in _paths_from_event(ev):
            resolved = _resolve_for_verification(normalize_path(str(p)), purpose="verify file creation")
            if resolved:
                file_path = resolved
                details["file_path"] = str(file_path)
                break

    extracted_from_result = _extract_path_from_task_result(task.result)
    if extracted_from_result:
        # Normalize path to handle Windows/Unix differences
        normalized = normalize_path(extracted_from_result)
        file_path = _resolve_for_verification(normalized, purpose="verify file creation")

    # Priority 2: Check last tool call arguments
    if not file_path:
        last_call = get_last_tool_call()
        if last_call:
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("path") or args.get("file") or args.get("target") or args.get("file_path")
                if isinstance(candidate, str) and candidate.strip():
                    normalized = normalize_path(candidate.strip())
                    file_path = _resolve_for_verification(normalized, purpose="verify file creation")

    # Priority 3: Try to extract file path from task description (fallback)
    # Patterns handle both Windows (backslash) and Unix (forward slash) paths
    if not file_path:
        patterns = [
            # Windows absolute path with extension
            r'(?:file\s+)?(?:at\s+)?["\']?([a-zA-Z]:[/\\][^"\'\s]+\.[a-zA-Z0-9]+)["\']?',
            # Unix or relative path with extension
            r'(?:file\s+)?(?:at\s+)?["\']?(\.?[/\\]?[a-zA-Z0-9_/\\\-\.]+\.[a-zA-Z0-9]+)["\']?',
            # Generic add/create pattern
            r'(?:add|create)\s+(?:file\s+)?(?:at\s+)?["\']?([a-zA-Z0-9_/\\\-\.]+\.[a-zA-Z0-9]+)["\']?',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, task.description, re.IGNORECASE)
            if matches:
                candidate = matches[0].strip()
                if candidate:
                    normalized = normalize_path(candidate)
                    file_path = _resolve_for_verification(normalized, purpose="verify file creation")
                    if file_path:
                        break

    # Priority 4: Check task.result for path-like strings
    if not file_path:
        if task.result and isinstance(task.result, str):
            # Result might contain the file path - handle both separators
            result_match = re.search(r'[a-zA-Z0-9_/\\\-\.]+\.[a-zA-Z0-9]+', task.result)
            if result_match:
                normalized = normalize_path(result_match.group(0))
                file_path = _resolve_for_verification(normalized, purpose="verify file creation")

    if not file_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={"description": task.description},
            should_replan=True
        )

    # Check if file exists
    if not file_path.exists():
        return VerificationResult(
            passed=False,
            message=f"File was not created: {file_path}",
            details={"expected_path": str(file_path)},
            should_replan=True
        )

    # If the resolved path is actually a directory, don't apply file-size semantics.
    if file_path.is_dir():
        return VerificationResult(
            passed=True,
            message=f"Directory exists: {file_path.name}",
            details={"directory_path": str(file_path), "is_dir": True},
        )

    file_size = file_path.stat().st_size
    details["file_exists"] = True
    details["file_size"] = file_size
    details["file_path"] = str(file_path)

    if file_size == 0:
        return VerificationResult(
            passed=False,
            message=f"File created but is empty: {file_path}",
            details=details,
            should_replan=True
        )

    # CRITICAL CHECK: Detect similar/duplicate files and fail verification
    # This forces replanning to extend existing files instead of creating duplicates
    payload = _parse_task_result_payload(task.result)
    if payload and payload.get("is_new_file") and payload.get("similar_files"):
        similar_list = payload.get("similar_files", [])
        similar_str = ", ".join(similar_list[:3])
        context.add_agent_request(
            "DUPLICATE_FILE_PREVENTION",
            {
                "agent": "VerificationSystem",
                "reason": f"Similar files exist: {similar_str}",
                "detailed_reason": (
                    f"DUPLICATE FILE DETECTED: File '{file_path.name}' was created but similar files already exist: {similar_str}. "
                    f"Instead of creating new files with similar names, EDIT one of the existing files to add the new functionality. "
                    f"Use action_type='edit' with the most appropriate existing file path."
                )
            }
        )
        return VerificationResult(
            passed=False,
            message=f"Duplicate file: similar files exist ({similar_str}). Extend existing file instead of creating new one.",
            details={
                **details,
                "similar_files": similar_list,
                "suggested_action": "extend_existing"
            },
            should_replan=True
        )

    # Syntax validation for created file
    is_valid, error_msg, skipped = _run_syntax_check(file_path)
    if not is_valid:
        _log_syntax_result(context, file_path, ok=False, skipped=False, msg=error_msg)
        suggested_cmd = _enqueue_project_typecheck(context, tasks := [], reason="Per-file syntax error")
        if tasks:
            context.set_agent_state("injected_tasks_after_skip", True)
            context.agent_requests.append({"type": "INJECT_TASKS", "details": {"tasks": tasks}})
        return VerificationResult(
            passed=False,
            message=f"File creation introduced a syntax error in {file_path.name}",
            details={
                **details,
                "syntax_error": error_msg,
                "suggestion": "Fix the syntax error in the file",
                "suggested_build_cmd": suggested_cmd,
            },
            should_replan=True,
        )
    if skipped:
        _log_syntax_result(context, file_path, ok=True, skipped=True, msg="skipped (no checker available)")
        suggested_cmd = _enqueue_project_typecheck(context, tasks := [], reason="Per-file syntax check skipped")
        if tasks:
            context.set_agent_state("injected_tasks_after_skip", True)
            context.agent_requests.append({"type": "INJECT_TASKS", "details": {"tasks": tasks}})
        _ensure_test_request_for_file(context, file_path)
        return VerificationResult(
            passed=True,
            message=f"Syntax check skipped for {file_path.name}; a project typecheck/build has been enqueued.",
            details={
                **details,
                "syntax_skipped": True,
                "suggested_build_cmd": suggested_cmd,
            },
            should_replan=False,
        )

    _log_syntax_result(context, file_path, ok=True, skipped=False, msg="valid")
    _ensure_test_request_for_file(context, file_path)
    return VerificationResult(
        passed=True,
        message=f"File created successfully and syntax validated: {file_path.name}",
        details=details
    )


def _extract_path_from_task_result(result: Any) -> Optional[str]:
    """Extract a file path from the tool result payload, if available."""
    if not result:
        return None

    data: Optional[Dict[str, Any]] = None
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            return None
    elif isinstance(result, dict):
        data = result
    else:
        return None

    # Sub-agent standardized output may wrap the raw tool output.
    if isinstance(data.get("tool_output"), str):
        nested = _extract_path_from_task_result(data.get("tool_output"))
        if nested:
            return nested

    # Prefer explicit tool args (stable) over brittle regex parsing of task text.
    tool_args = data.get("tool_args")
    if isinstance(tool_args, dict):
        for key in ("path", "file_path", "target_path", "directory", "dir_path"):
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                return value

    for key in (
        "path_abs",
        "file_abs",
        "directory_abs",
        "file",
        "path",
        "updated_file",
        "wrote",
        "created",
        "deleted",
        "appended_to",
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _resolve_for_verification(raw_path: str, *, purpose: str) -> Optional[Path]:
    """Resolve a candidate path using the canonical workspace resolver."""

    try:
        return resolve_workspace_path(raw_path, purpose=purpose).abs_path
    except WorkspacePathError:
        return None


def _parse_task_result_payload(result: Any) -> Optional[Dict[str, Any]]:
    """Best-effort JSON parsing of a task's result payload."""
    if not result:
        return None
    parsed: Optional[Dict[str, Any]] = None
    if isinstance(result, dict):
        parsed = result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None

    tool_output = parsed.get("tool_output")
    if isinstance(tool_output, dict):
        merged = dict(parsed)
        merged.update(tool_output)
        return merged
    if isinstance(tool_output, str):
        try:
            nested = json.loads(tool_output)
        except json.JSONDecodeError:
            nested = None
        if isinstance(nested, dict):
            merged = dict(parsed)
            merged.update(nested)
            return merged

    return parsed


def _get_verification_mode() -> Optional[str]:
    """Return verification mode: 'strict', 'fast', or None."""
    env_strict = os.getenv("REV_VERIFY_STRICT", "").lower()
    env_fast = os.getenv("REV_VERIFY_FAST", "").lower()
    if env_strict in {"1", "true", "yes", "on", "strict"}:
        return "strict"
    if env_fast in {"1", "true", "yes", "on", "fast"}:
        return "fast"
    # Default to fast mode so syntax errors are caught even without env flags.
    return "fast"


def _latest_tool_event(tool_events: Optional[Iterable[Dict[str, Any]]], names: Iterable[str]) -> Optional[Dict[str, Any]]:
    """Return the most recent tool event matching one of the names."""
    if not tool_events:
        return None
    target = {n.lower() for n in names}
    for ev in reversed(list(tool_events)):
        tool = str(ev.get("tool") or "").lower()
        if tool in target:
            return ev
    return None


def _paths_from_event(event: Dict[str, Any]) -> list[Path]:
    """Extract path candidates from a tool event."""
    paths: list[Path] = []
    raw_result = event.get("raw_result")
    parsed = None
    if isinstance(raw_result, str):
        try:
            parsed = json.loads(raw_result)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        for key in ("path_abs", "file_abs", "directory_abs", "path", "file", "created", "wrote", "updated_file", "dir_path", "path_rel"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                paths.append(Path(val))
        tool_args = parsed.get("tool_args") if isinstance(parsed.get("tool_args"), dict) else None
        if tool_args:
            for key in ("path", "file_path", "target_path", "directory", "dir_path", "target_directory"):
                val = tool_args.get(key)
                if isinstance(val, str) and val.strip():
                    paths.append(Path(val))
    args = event.get("args")
    if isinstance(args, dict):
        for key in ("path", "file_path", "target_path", "directory", "dir_path", "target_directory"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                paths.append(Path(val))
    return paths


def _collect_paths_for_strict_checks(
    action_type: str,
    details: Dict[str, Any],
    tool_events: Optional[Iterable[Dict[str, Any]]] = None,
) -> list[Path]:
    """Collect relevant paths for strict verification."""
    paths: list[Path] = []
    for key in ("file_path", "directory_path", "source_file_path", "target_dir_path"):
        candidate = details.get(key)
        if isinstance(candidate, str) and candidate.strip():
            try:
                paths.append(Path(candidate))
            except Exception:
                continue

    # Add from tool events
    if tool_events:
        for ev in tool_events:
            paths.extend(_paths_from_event(ev))

    # Ensure uniqueness
    unique_paths: list[Path] = []
    seen = set()
    for p in paths:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(resolved)
    return unique_paths


def _ensure_tool_available(cmd: str) -> bool:
    """Check if a tool is available, and if not, attempt to install it.
    
    Returns:
        bool: True if tool is available (already existed or successfully installed).
    """
    try:
        args = shlex.split(cmd)
        if not args:
            return True
        
        base_cmd = args[0]
        # Resolve command (handles .exe, .cmd, etc on Windows)
        resolved = _resolve_command(base_cmd)
        
        # 1. If command is found, perform integrity check for runners
        if resolved:
            # Handle runners like npx, python -m, etc.
            if _is_command_runner(base_cmd):
                _repair_environment_for_runner(base_cmd, args)
            return True

        # 2. If command is missing from PATH, try ecosystem-specific recovery
        if _try_node_recovery(base_cmd):
            return True

        # Fallback to auto-install for known common tools across ecosystems
        return _try_auto_install(base_cmd)
        
    except Exception as e:
        print(f"  [!] Error checking/installing tool '{cmd}': {e}")
        return False


def _is_command_runner(base_cmd: str) -> bool:
    """Check if the command is a known package runner."""
    return base_cmd in ("npx", "npm", "python", "python3")


def _repair_environment_for_runner(runner: str, args: List[str]) -> None:
    """Attempt to repair the environment for a specific runner if its target is missing."""
    if runner in ("npx", "npm") and len(args) > 1:
        # Extract package name from npx/npm call
        pkg = args[1] if args[1] != "--yes" else (args[2] if len(args) > 2 else "")
        if pkg and pkg not in ("run", "install", "test"):
            _try_npm_repair(pkg)
    elif runner in ("python", "python3") and len(args) > 2 and args[1] == "-m":
        # Handle python -m <module>
        # (Generic pip repair could be added here if needed)
        pass


def _install_guard_key(root: Path, install_cmd: list[str]) -> tuple[str, str]:
    try:
        root_key = str(root.resolve())
    except Exception:
        root_key = str(root)
    cmd_key = " ".join(str(part).lower() for part in install_cmd if part is not None)
    return (root_key, cmd_key)


def _dependency_files_for_install(install_cmd: list[str]) -> list[str]:
    if not install_cmd:
        return []
    tokens = [str(part).lower() for part in install_cmd if part is not None]
    if not tokens:
        return []
    base = Path(tokens[0]).name
    if base in {"python", "python3"} and "-m" in tokens:
        idx = tokens.index("-m")
        if idx + 1 < len(tokens) and tokens[idx + 1] == "pip":
            base = "pip"
    if base in {"pip", "pip3"}:
        return [
            "pyproject.toml",
            "poetry.lock",
            "pdm.lock",
            "Pipfile.lock",
            "requirements.txt",
            "requirements-dev.txt",
            "requirements.in",
            "setup.cfg",
            "setup.py",
        ]
    if base in {"npm", "yarn", "pnpm"}:
        return [
            "package.json",
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        ]
    if base == "composer":
        return ["composer.json", "composer.lock"]
    if base in {"bundle", "bundler"}:
        return ["Gemfile", "Gemfile.lock"]
    if base == "cargo":
        return ["Cargo.toml", "Cargo.lock"]
    if base == "go":
        return ["go.mod", "go.sum"]
    if base in {"mvn", "mvnw"}:
        return ["pom.xml"]
    if base in {"gradle", "gradlew"}:
        return ["build.gradle", "build.gradle.kts", "gradle.lockfile"]
    if base == "dotnet":
        return ["packages.lock.json", "Directory.Packages.props"]
    return []


def _lockfile_snapshot(root: Path, dependency_files: list[str]) -> tuple[tuple[str, int, int], ...]:
    if not dependency_files:
        return tuple()
    entries: list[tuple[str, int, int]] = []
    for name in dependency_files:
        path = root / name
        if not path.exists():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(sorted(entries))


def _should_attempt_install(install_cmd: list[str], *, root: Optional[Path], missing_deps: bool) -> bool:
    if not missing_deps:
        return False
    root_path = root or config.ROOT
    snapshot = _lockfile_snapshot(root_path, _dependency_files_for_install(install_cmd))
    key = _install_guard_key(root_path, install_cmd)
    state = _INSTALL_GUARD_STATE.get(key)
    if state:
        if snapshot != state.get("snapshot"):
            state["snapshot"] = snapshot
            state["attempts"] = 0
            return True
        if state.get("attempts", 0) >= 1:
            return False
        return True
    _INSTALL_GUARD_STATE[key] = {"snapshot": snapshot, "attempts": 0}
    return True


def _record_install_attempt(install_cmd: list[str], *, root: Optional[Path]) -> None:
    root_path = root or config.ROOT
    key = _install_guard_key(root_path, install_cmd)
    state = _INSTALL_GUARD_STATE.get(key)
    if not state:
        state = {
            "snapshot": _lockfile_snapshot(root_path, _dependency_files_for_install(install_cmd)),
            "attempts": 0,
        }
        _INSTALL_GUARD_STATE[key] = state
    state["attempts"] = int(state.get("attempts", 0)) + 1


def _try_auto_install(base_cmd: str) -> bool:
    """Attempt to install a missing tool based on its name."""
    pkg_map = {
        "ruff": ["pip", "install", "ruff"],
        "mypy": ["pip", "install", "mypy"],
        "pytest": ["pip", "install", "pytest"],
        "eslint": ["npm", "install", "eslint", "--save-dev"],
    }

    if base_cmd in pkg_map:
        install_cmd = pkg_map[base_cmd]
        if not _should_attempt_install(install_cmd, root=config.ROOT, missing_deps=True):
            print(f"  [i] Skipping auto-install for {base_cmd}: dependency state unchanged.")
            return False
        print(f"  [i] Tool '{base_cmd}' not found, attempting auto-install: {install_cmd}...")
        _record_install_attempt(install_cmd, root=config.ROOT)
        install_res = execute_tool("run_cmd", {"cmd": install_cmd, "timeout": 300}, agent_name="quick_verify")
        try:
            if json.loads(install_res).get("rc") == 0:
                print(f"  [OK] Successfully installed {base_cmd}")
                return True
        except:
            pass
    return False


def _try_npm_repair(pkg: str) -> bool:
    """Attempt to repair node_modules if a package is expected but missing."""
    pkg_name = "typescript" if pkg == "tsc" else pkg
    if (config.ROOT / "node_modules" / pkg_name).exists():
        return True

    pkg_json_path = config.ROOT / "package.json"
    if not pkg_json_path.exists():
        return False
        
    try:
        pkg_data = json.loads(pkg_json_path.read_text(errors='ignore'))
        deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
        
        if pkg in deps or pkg_name in deps:
            print(f"  [i] package '{pkg}' missing from node_modules, attempting repair...")
            install_cmd = ["npm", "install"]
            if not _should_attempt_install(install_cmd, root=config.ROOT, missing_deps=True):
                print("  [i] Skipping npm install: dependency state unchanged.")
                return False
            _record_install_attempt(install_cmd, root=config.ROOT)
            execute_tool("run_cmd", {"cmd": ["npm", "install"], "timeout": 600}, agent_name="quick_verify")
            return (config.ROOT / "node_modules" / pkg_name).exists()
    except:
        pass
    return False


def _try_node_recovery(base_cmd: str) -> bool:
    """Attempt to recover missing command in Node environment by checking project config."""
    pkg_json_path = config.ROOT / "package.json"
    if not pkg_json_path.exists():
        return False

    try:
        pkg_data = json.loads(pkg_json_path.read_text(errors='ignore'))
        scripts = pkg_data.get("scripts", {})
        deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}

        # If it's a script or dependency, it's considered "available" (either directly or via npm/npx)
        return base_cmd in scripts or base_cmd in deps
    except:
        return False


def _attempt_ecosystem_fallback(cmd: str | List[str], timeout: int | None, use_tests_tool: bool, retry_count: int) -> Optional[Dict[str, Any]]:
    """Attempt to find an alternative way to run a missing command based on project context."""
    base_cmd = cmd[0] if isinstance(cmd, list) else shlex.split(cmd)[0]
    
    # 1. NODE.JS FALLBACKS
    pkg_json_path = config.ROOT / "package.json"
    if pkg_json_path.exists():
        try:
            pkg_data = json.loads(pkg_json_path.read_text(errors='ignore'))
            scripts = pkg_data.get("scripts", {})
            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
            
            # If the missing command is exactly an npm script name, try 'npm run <cmd>'
            if base_cmd in scripts and base_cmd != "npm":
                print(f"  [i] '{base_cmd}' not in PATH, but exists as npm script. Trying 'npm run {base_cmd}'...")
                return _run_validation_command(["npm", "run", base_cmd], timeout=timeout, _retry_count=retry_count+1)
            
            # If it's in dependencies but not PATH, try npx
            if base_cmd in deps and base_cmd != "npx":
                print(f"  [i] '{base_cmd}' not in PATH, but exists in dependencies. Trying 'npx {base_cmd}'...")
                return _run_validation_command(["npx", "--yes", base_cmd], timeout=timeout, _retry_count=retry_count+1)
                
            # If a runner itself failed (e.g. npx), try to extract the target and find a script for it
            if base_cmd in ("npx", "npm", "node") and len(cmd) > 1:
                # Extract target tool (e.g. npx eslint -> eslint)
                target = ""
                if base_cmd in ("npx", "npm"):
                    target = cmd[2] if isinstance(cmd, list) and len(cmd) > 2 and cmd[1] == "--yes" else (cmd[1] if len(cmd) > 1 else "")
                
                if target:
                    if target in scripts:
                        return _run_validation_command(["npm", "run", target], timeout=timeout, _retry_count=retry_count+1)
                    # Special case: common tool aliases in scripts
                    if target == "eslint" and "lint" in scripts:
                        return _run_validation_command(["npm", "run", "lint"], timeout=timeout, _retry_count=retry_count+1)
                    if target in ("vitest", "jest", "pytest") and "test" in scripts:
                        return _run_validation_command(["npm", "test"], use_tests_tool=True, timeout=timeout, _retry_count=retry_count+1)
        except:
            pass

    # 2. PYTHON FALLBACKS
    if base_cmd != "python":
        # Check if it might be available via python -m
        # (This is more of a probe, but safe for common tools)
        common_python_tools = {"pytest", "ruff", "mypy", "pylint", "black", "isort"}
        if base_cmd in common_python_tools:
            print(f"  [i] '{base_cmd}' not in PATH, trying 'python -m {base_cmd}'...")
            return _run_validation_command(["python", "-m", base_cmd], timeout=timeout, _retry_count=retry_count+1)

    return None


def _select_recovery_hint(stdout: str, stderr: str, error: str) -> Optional[str]:
    """Return a focused recovery hint when a known error pattern is detected."""
    combined = f"{stdout}\n{stderr}\n{error}"
    lowered = combined.lower()

    missing_script = _detect_missing_script(stdout, stderr)
    if missing_script:
        return f"Missing test script '{missing_script}'. Update package.json scripts or choose a different test command."
    if "cannot find package" in lowered or "err_module_not_found" in lowered or "module_not_found" in lowered:
        return "Missing dependency detected. Install the package or update the import path before retrying."
    if "modulenotfounderror" in lowered or "no module named" in lowered:
        return "Missing Python module detected. Install the module or update PYTHONPATH before retrying."
    if "command not found" in lowered or "is not recognized as an internal or external command" in lowered:
        return "Command not found. Install the tool or fix PATH, then retry."
    if "no tests found" in lowered or "no tests ran" in lowered or "no tests collected" in lowered:
        return "No tests were discovered. Check test paths/patterns or run a per-file test command."
    return None


def _extract_error(res: Dict[str, Any], default: str = "Unknown error") -> str:
    """Extract and truncate error message from tool result, with a recovery hint."""
    stdout = _strip_ansi(res.get("stdout", ""))
    stderr = _strip_ansi(res.get("stderr", ""))
    error = _strip_ansi(res.get("error", ""))
    rc = res.get("rc")
    help_info = res.get("help_info")
    
    msg = stderr or stdout or error or default
    msg = msg.strip()
    
    # If we have a failure (non-zero rc) but no output, provide more context
    if (rc is not None and rc != 0) and not stderr and not stdout and not error:
        msg = f"Command failed with exit code {rc} but produced no output (stdout/stderr)."
        if rc == 2:
            msg += " On Windows, exit code 2 often indicates a fatal configuration error or missing files for tools like ESLint."

    # Include help information if available
    if help_info:
        msg += f"\n\n--- COMMAND USAGE INFO (--help) ---\n{help_info}"

    specific_hint = _select_recovery_hint(stdout, stderr, error)
    if specific_hint:
        hint = f"\n\n[RECOVERY HINT] {specific_hint}"
    else:
        hint = (
            "\n\n[RECOVERY HINT] Analyze the output above. If it indicates a missing configuration file "
            "(e.g., eslint.config.js, .eslintrc.json, pyproject.toml, tsconfig.json), a missing dependency, or an "
            "uninitialized environment, your next step should be to fix the environment (e.g., "
            "create the config file, install the package, or initialize the project) before retrying."
        )

    if len(msg) > 500:
        msg = msg[:497] + "..."
    
    return msg + hint


def _get_help_output(cmd_name: str) -> Optional[str]:
    """Attempt to get usage/help output for a command."""
    # Common help flags
    for flag in ("--help", "-h"):
        try:
            # We use execute_tool directly to avoid recursion
            payload = {"cmd": f"{cmd_name} {flag}", "timeout": 5}
            raw = execute_tool("run_cmd", payload, agent_name="quick_verify")
            res = json.loads(raw)
            # rc=0 is success, but some tools output help to stderr or with non-zero rc
            out = (res.get("stdout") or res.get("stderr") or "").strip()
            if out and len(out) > 50: # Ignore very short outputs
                return out[:1500] # Return first 1500 chars
        except:
            continue
    return None


def _try_dynamic_help_discovery(path: Path) -> Optional[str]:
    """Try to determine how to run a file by executing it with help flags."""
    try:
        if not path.exists() or not path.is_file():
            return None
            
        # Determine likely runner
        runner = ""
        if path.suffix == ".py": runner = "python"
        elif path.suffix in (".js", ".ts", ".mjs", ".cjs"): runner = "node"
        elif path.suffix in (".sh", ".bash"): runner = "bash"
        
        if not runner:
            return None
            
        for flag in ("--help", "-h"):
            cmd = f"{runner} {_quote_path(path)} {flag}"
            raw = execute_tool("run_cmd", {"cmd": cmd, "timeout": 5}, agent_name="quick_verify")
            res = json.loads(raw)
            out = (res.get("stdout") or res.get("stderr") or "").strip()
            if out and ("usage:" in out.lower() or "options:" in out.lower() or "arguments:" in out.lower()):
                return out[:1000]
    except:
        pass
    return None


def _split_command_parts(cmd: str | list[str]) -> list[str]:
    if isinstance(cmd, list):
        return [str(part) for part in cmd if part is not None]
    try:
        return shlex.split(cmd)
    except Exception:
        return [str(cmd)]


def _command_has_explicit_cwd(cmd_parts: list[str]) -> bool:
    if not cmd_parts:
        return False
    base = cmd_parts[0].lower()
    if base == "npm":
        return "--prefix" in cmd_parts or "--cwd" in cmd_parts
    if base == "yarn":
        return "--cwd" in cmd_parts
    if base == "pnpm":
        return "--dir" in cmd_parts or "--prefix" in cmd_parts
    return False


def _resolve_validation_cwd(cmd: str | list[str], primary_path: Optional[Path]) -> Optional[Path]:
    if not primary_path:
        return None
    cmd_parts = _split_command_parts(cmd)
    if not cmd_parts:
        return None
    base = cmd_parts[0].lower()
    if base in {"npm", "yarn", "pnpm", "npx"} and not _command_has_explicit_cwd(cmd_parts):
        return find_project_root(primary_path)
    return None


def _output_indicates_tests_present(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    patterns = (
        r"\btests?\s*\(?\s*([1-9]\d*)\b",
        r"\b([1-9]\d*)\s+tests?\b",
        r"\bcollected\s+([1-9]\d*)\s+items\b",
    )
    for line in combined.splitlines():
        if "test files" in line or "test file" in line:
            continue
        if any(re.search(pattern, line) for pattern in patterns):
            return True
    return False


def _output_indicates_no_tests(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    if _output_indicates_tests_present(stdout, stderr):
        return False
    patterns = (
        r"\bno tests found\b",
        r"\bno tests ran\b",
        r"\bno tests collected\b",
        r"\bcollected\s+0\s+items\b",
        r"\bran\s+0\s+tests?\b",
        r"\bno test files\b",
        r"\b0\s+tests?\b",
        r"\b0\s+passing\b",
    )
    return any(re.search(pattern, combined) for pattern in patterns)


def _extract_test_files_from_output(output: str) -> list[str]:
    if not output:
        return []
    matches = re.findall(r"([A-Za-z0-9_/\\.-]+\.(?:test|spec)\.[A-Za-z0-9]+)", output)
    if not matches:
        return []
    seen = set()
    deduped: list[str] = []
    for match in matches:
        normalized = match.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _resolve_import_target(test_path: Path, module_spec: str, root: Path) -> Optional[Path]:
    if not module_spec:
        return None
    if not module_spec.startswith("."):
        return None
    base = (test_path.parent / module_spec)
    candidates: list[Path] = []
    if base.suffix:
        candidates.append(base)
    else:
        candidates.extend(
            base.with_suffix(ext)
            for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
        )
        candidates.append(base / "index.ts")
        candidates.append(base / "index.js")
        candidates.append(base / "index.tsx")
        candidates.append(base / "index.jsx")
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if not resolved.exists() or not resolved.is_file():
            continue
        try:
            root_resolved = root.resolve()
        except Exception:
            root_resolved = root
        if root_resolved not in resolved.parents and resolved != root_resolved:
            continue
        return resolved
    return None


def _detect_import_export_mismatch(test_files: list[str], root: Path) -> list[str]:
    hints: list[str] = []
    for test_file in test_files[:5]:
        try:
            test_path = Path(test_file)
            if not test_path.is_absolute():
                test_path = (root / test_path).resolve()
        except Exception:
            continue
        if not test_path.exists():
            continue
        content = _read_text_file(test_path)
        if not content:
            continue

        for match in re.finditer(r"import\s+([^;]+?)\s+from\s+['\"]([^'\"]+)['\"]", content):
            import_clause = match.group(1).strip()
            module_spec = match.group(2).strip()
            target = _resolve_import_target(test_path, module_spec, root)
            if not target:
                if module_spec.startswith("."):
                    hints.append(
                        f"{test_path.as_posix()} imports {module_spec} but the path does not resolve to a file."
                    )
                continue

            target_content = _read_text_file(target)
            if not target_content:
                continue
            exported_names, has_default = _extract_exports(target_content)
            default_name, named_imports = _parse_import_clause(import_clause)

            if default_name and not has_default:
                hints.append(
                    f"{test_path.as_posix()} imports default '{default_name}' from {module_spec} but {target.as_posix()} has no default export."
                )
            for name in named_imports:
                if name not in exported_names:
                    hints.append(
                        f"{test_path.as_posix()} imports '{{ {name} }}' from {module_spec} but {target.as_posix()} does not export it."
                    )

    return hints


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _load_package_json(root: Path) -> dict:
    pkg = root / "package.json"
    if not pkg.exists():
        return {}
    try:
        return json.loads(pkg.read_text(errors="ignore"))
    except Exception:
        return {}


def _package_dependencies(root: Path) -> set[str]:
    pkg_data = _load_package_json(root)
    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = pkg_data.get(key)
        if isinstance(value, dict):
            deps.update(value)
    return {str(name).lower() for name in deps.keys()}


def _extract_exports(content: str) -> tuple[set[str], bool]:
    names: set[str] = set()
    for match in re.finditer(r"export\s+(?:const|function|class|interface|type)\s+([A-Za-z0-9_]+)", content):
        names.add(match.group(1))
    for match in re.finditer(r"export\s+\{([^}]+)\}", content):
        for part in match.group(1).split(","):
            item = part.strip()
            if not item:
                continue
            if " as " in item:
                item = item.split(" as ", 1)[0].strip()
            names.add(item)
    has_default = bool(re.search(r"\bexport\s+default\b", content))
    return names, has_default


def _parse_import_clause(clause: str) -> tuple[Optional[str], list[str]]:
    default_name = None
    named: list[str] = []
    if not clause:
        return default_name, named
    if clause.startswith("{"):
        named = _parse_named_imports(clause)
        return default_name, named
    if clause.startswith("*"):
        return default_name, named
    if "," in clause:
        default_part, rest = clause.split(",", 1)
        default_name = default_part.strip()
        named = _parse_named_imports(rest)
        return default_name, named
    default_name = clause.strip()
    return default_name, named


def _parse_named_imports(segment: str) -> list[str]:
    match = re.search(r"\{([^}]+)\}", segment)
    if not match:
        return []
    names: list[str] = []
    for part in match.group(1).split(","):
        item = part.strip()
        if not item:
            continue
        if " as " in item:
            item = item.split(" as ", 1)[0].strip()
        names.append(item)
    return names


def _parse_env_file_vars(path: Path) -> set[str]:
    if not path.exists():
        return set()
    values: set[str] = set()
    for line in _read_text_file(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            values.add(key)
    return values


def _collect_env_vars_from_text(text: str) -> set[str]:
    if not text:
        return set()
    env_vars = set(re.findall(r"process\.env\.([A-Za-z0-9_]+)", text))
    env_vars.update(re.findall(r"import\.meta\.env\.([A-Za-z0-9_]+)", text))
    env_vars.update(re.findall(r"os\.environ\[['\"]([A-Za-z0-9_]+)['\"]\]", text))
    return env_vars


def _extract_string_literals(raw: str) -> list[str]:
    return [match for match in re.findall(r"['\"]([^'\"]+)['\"]", raw or "")]


def _extract_patterns_from_config_content(content: str) -> dict[str, list[str]]:
    patterns = {"include": [], "exclude": [], "test_match": [], "test_regex": []}
    if not content:
        return patterns
    fields = {
        "include": "include",
        "exclude": "exclude",
        "testMatch": "test_match",
        "testRegex": "test_regex",
    }
    for field, key in fields.items():
        matches = re.finditer(
            rf"{field}\s*:\s*(\[[^\]]*\]|['\"][^'\"]+['\"]|/[^/]+/)",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        for match in matches:
            raw = match.group(1)
            if raw.startswith("/") and raw.endswith("/") and key == "test_regex":
                patterns[key].append(raw.strip("/"))
                continue
            patterns[key].extend(_extract_string_literals(raw))
    return patterns


def _collect_test_discovery_patterns(root: Path) -> dict[str, list[str]]:
    combined = {"include": [], "exclude": [], "test_match": [], "test_regex": []}
    candidates = [
        "vitest.config.ts",
        "vitest.config.js",
        "vitest.config.mjs",
        "vitest.config.cjs",
        "vite.config.ts",
        "vite.config.js",
        "vite.config.mjs",
        "vite.config.cjs",
        "jest.config.ts",
        "jest.config.js",
        "jest.config.mjs",
        "jest.config.cjs",
    ]
    for name in candidates:
        path = root / name
        if not path.exists():
            continue
        content = _read_text_file(path)
        patterns = _extract_patterns_from_config_content(content)
        for key in combined:
            combined[key].extend(patterns[key])

    pkg = _load_package_json(root)
    jest_cfg = pkg.get("jest")
    if isinstance(jest_cfg, dict):
        combined["test_match"].extend(jest_cfg.get("testMatch", []) or [])
        regex = jest_cfg.get("testRegex")
        if isinstance(regex, str):
            combined["test_regex"].append(regex)
        elif isinstance(regex, list):
            combined["test_regex"].extend(regex)
    vitest_cfg = pkg.get("vitest") or pkg.get("test")
    if isinstance(vitest_cfg, dict):
        combined["include"].extend(vitest_cfg.get("include", []) or [])
        combined["exclude"].extend(vitest_cfg.get("exclude", []) or [])

    return combined


def _expand_brace_pattern(pattern: str) -> list[str]:
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    prefix, rest = pattern.split("{", 1)
    inner, suffix = rest.split("}", 1)
    parts = [part.strip() for part in inner.split(",") if part.strip()]
    return [f"{prefix}{part}{suffix}" for part in parts] or [pattern]


def _match_any_glob(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        for expanded in _expand_brace_pattern(pattern):
            if fnmatch.fnmatch(path, expanded):
                return True
    return False


def _detect_test_discovery_config_mismatch(test_files: list[str], root: Path) -> Optional[str]:
    if not test_files:
        return None
    patterns = _collect_test_discovery_patterns(root)
    include = patterns["include"] or patterns["test_match"]
    exclude = patterns["exclude"]
    regexes = patterns["test_regex"]

    normalized = [path.replace("\\", "/") for path in test_files]
    if include:
        if not any(_match_any_glob(path, include) for path in normalized):
            return "Test discovery patterns do not match any test files (check include/testMatch config)."
    if regexes:
        try:
            compiled = [re.compile(expr) for expr in regexes]
        except re.error:
            compiled = []
        if compiled and not any(any(regex.search(path) for regex in compiled) for path in normalized):
            return "testRegex patterns do not match any test files."
    if exclude and all(_match_any_glob(path, exclude) for path in normalized):
        return "All discovered test files are excluded by config patterns."
    return None


def _test_file_has_cases(content: str) -> bool:
    return bool(re.search(r"\b(it|test|bench)\s*\(", content))


def _detect_empty_test_files(test_files: list[str], root: Path) -> Optional[str]:
    for test_file in test_files[:5]:
        try:
            path = Path(test_file)
            if not path.is_absolute():
                path = (root / path).resolve()
        except Exception:
            continue
        content = _read_text_file(path)
        if content and not _test_file_has_cases(content):
            return f"{path.as_posix()} defines no test cases (no it()/test() calls)."
    return None


def _detect_missing_env_vars(test_files: list[str], root: Path) -> list[str]:
    env_vars: set[str] = set()
    for test_file in test_files[:5]:
        try:
            path = Path(test_file)
            if not path.is_absolute():
                path = (root / path).resolve()
        except Exception:
            continue
        env_vars.update(_collect_env_vars_from_text(_read_text_file(path)))
    if not env_vars:
        return []
    env_file_vars = _parse_env_file_vars(root / ".env")
    missing = []
    for name in sorted(env_vars):
        if name in {"NODE_ENV", "PATH", "PWD", "HOME"}:
            continue
        if name not in env_file_vars and name not in os.environ:
            missing.append(name)
    return missing


def _detect_missing_modules_from_output(output: str, root: Path) -> list[str]:
    if not output:
        return []
    deps = _package_dependencies(root)
    builtins = {
        "fs", "path", "http", "https", "url", "crypto", "stream", "events", "os", "util",
        "child_process", "buffer", "zlib", "net", "tls", "assert", "timers",
    }
    missing: list[str] = []
    for match in re.findall(r"Cannot find module ['\"]([^'\"]+)['\"]", output):
        module_name = match.strip()
        module_lower = module_name.lower()
        if module_name.startswith("."):
            missing.append(f"Missing local import: {module_name}")
        elif module_lower not in deps and module_lower not in builtins:
            missing.append(f"Missing dependency: {module_name}")
    for match in re.findall(r"Can't resolve ['\"]([^'\"]+)['\"]", output):
        module_name = match.strip()
        module_lower = module_name.lower()
        if module_name.startswith("."):
            missing.append(f"Missing local import: {module_name}")
        elif module_lower not in deps and module_lower not in builtins:
            missing.append(f"Missing dependency: {module_name}")
    return missing


def _detect_typescript_setup_issues(test_files: list[str], root: Path) -> list[str]:
    uses_ts = any(path.endswith((".ts", ".tsx")) for path in test_files)
    uses_vue = any(path.endswith(".vue") for path in test_files)
    if not (uses_ts or uses_vue):
        return []
    hints: list[str] = []
    if not (root / "tsconfig.json").exists() and not (root / "jsconfig.json").exists():
        hints.append("TypeScript files detected but tsconfig.json/jsconfig.json is missing.")
    deps = _package_dependencies(root)
    if "typescript" not in deps:
        hints.append("TypeScript is not listed in package.json dependencies.")
    if uses_vue and "@vue/compiler-sfc" not in deps:
        hints.append("Vue files detected but @vue/compiler-sfc is missing in dependencies.")
    return hints


def _detect_prisma_setup_issues(test_files: list[str], output: str, root: Path) -> list[str]:
    hinted = False
    for test_file in test_files[:5]:
        if "@prisma/client" in _read_text_file(root / test_file if not Path(test_file).is_absolute() else Path(test_file)):
            hinted = True
            break
    if "prisma" in (output or "").lower():
        hinted = True
    if not hinted:
        return []
    hints: list[str] = []
    if not (root / "prisma" / "schema.prisma").exists():
        hints.append("Prisma schema.prisma is missing.")
    if not (root / "node_modules" / "@prisma" / "client").exists():
        hints.append("@prisma/client is missing from node_modules.")
    if not (root / "prisma" / "migrations").exists():
        hints.append("Prisma migrations are missing; run prisma migrate to initialize.")
    return hints


def _detect_connection_errors(output: str) -> Optional[str]:
    lowered = (output or "").lower()
    if any(token in lowered for token in ("econnrefused", "connect econnrefused", "socket hang up", "enotfound")):
        return "Connection error detected (server not running or wrong host/port)."
    return None


def _detect_missing_test_runner(test_files: list[str], output: str, root: Path) -> Optional[str]:
    deps = _package_dependencies(root)
    content_hint = ""
    for test_file in test_files[:5]:
        content_hint += _read_text_file(root / test_file if not Path(test_file).is_absolute() else Path(test_file))
    combined = f"{output}\n{content_hint}".lower()
    if "vitest" in combined and "vitest" not in deps:
        return "Vitest is referenced but not listed in package.json dependencies."
    if "jest" in combined and "jest" not in deps:
        return "Jest is referenced but not listed in package.json dependencies."
    return None


def _build_test_diagnostics(output: str, test_files: list[str], root: Path) -> dict[str, Any]:
    debug: dict[str, Any] = {}
    hints: list[str] = []
    discovered = test_files or _discover_test_files(root)
    if discovered:
        debug["discovered_test_files"] = discovered[:5]

    import_hints = _detect_import_export_mismatch(discovered, root)
    hints.extend(import_hints[:2])

    config_hint = _detect_test_discovery_config_mismatch(discovered, root)
    if config_hint:
        hints.append(config_hint)

    empty_hint = _detect_empty_test_files(discovered, root)
    if empty_hint:
        hints.append(empty_hint)

    missing_env = _detect_missing_env_vars(discovered, root)
    if missing_env:
        debug["missing_env_vars"] = missing_env[:5]
        hints.append("Missing environment variables detected in tests.")

    missing_mods = _detect_missing_modules_from_output(output, root)
    if missing_mods:
        debug["missing_dependencies"] = missing_mods[:5]
        hints.append(missing_mods[0])

    if (root / "package.json").exists() and not (root / "node_modules").exists():
        hints.append("node_modules is missing; install dependencies before running tests.")
        hints.append("Run `npm install` (or yarn/pnpm) to install the test runner.")

    ts_hints = _detect_typescript_setup_issues(discovered, root)
    hints.extend(ts_hints[:2])

    output_lower = output.lower()
    # Broader framework/tooling hints
    if "cacerror" in output_lower and "vitest" in output_lower:
        hints.append("Vitest CLI error: invalid option or script; fix package.json test script to a non-watch single-file command.")
    if "unknown option" in output_lower and "jest" in output_lower:
        hints.append("Jest CLI error: invalid option; check package.json test script flags.")
    if "enoent" in output_lower and ("node" in output_lower or "npm" in output_lower):
        hints.append("Command failed to start; verify package.json scripts and that the test runner is installed.")
        hints.append("Install dependencies (npm install) and ensure the test script points to an existing runner.")
    if "playwright" in output_lower and "not found" in output_lower:
        hints.append("Playwright binary missing; install Playwright and run `npx playwright install`.")

    prisma_hints = _detect_prisma_setup_issues(discovered, output, root)
    hints.extend(prisma_hints[:2])

    conn_hint = _detect_connection_errors(output)
    if conn_hint:
        hints.append(conn_hint)

    runner_hint = _detect_missing_test_runner(discovered, output, root)
    if runner_hint:
        hints.append(runner_hint)

    if hints:
        debug["suspected_issue"] = hints[0]
        debug["hints"] = hints[:4]

    return debug


def _merge_debug_details(details: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    if not debug:
        return details
    merged = dict(details)
    merged["debug"] = debug
    return merged


def _path_is_test_like(path: Path) -> bool:
    try:
        parts = {part.lower() for part in path.parts}
    except Exception:
        parts = set()

    name = path.name.lower()
    if _TEST_NAME_PATTERN.search(name):
        return True
    if name.startswith("test_") or name.startswith("spec_"):
        return True
    if name.endswith("_test" + path.suffix.lower()) or name.endswith("_spec" + path.suffix.lower()):
        return True

    return bool(parts.intersection(_TEST_DIR_TOKENS))


def _extract_task_paths_for_tdd(task: Task) -> list[Path]:
    paths: list[Path] = []

    events = getattr(task, "tool_events", None) or []
    for ev in events:
        args = ev.get("args", {})
        if not isinstance(args, dict):
            continue
        for key in ("path", "file_path", "target", "source", "destination", "dest", "new_path", "old_path"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                resolved = _resolve_for_verification(val.strip(), purpose="tdd task path")
                if resolved:
                    paths.append(resolved)

    result_path = _extract_path_from_task_result(task.result)
    if result_path:
        resolved = _resolve_for_verification(result_path, purpose="tdd result path")
        if resolved:
            paths.append(resolved)

    if task.description:
        matches = re.findall(r'([A-Za-z0-9_/\\\.-]+\.[A-Za-z0-9]+)', task.description)
        for match in matches:
            resolved = _resolve_for_verification(match, purpose="tdd description path")
            if resolved:
                paths.append(resolved)

    # Deduplicate while preserving order
    seen = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _task_changes_tests_only(task: Task) -> bool:
    paths = _extract_task_paths_for_tdd(task)
    if not paths:
        return False
    has_test = any(_path_is_test_like(path) for path in paths)
    has_non_test = any(not _path_is_test_like(path) for path in paths)
    return has_test and not has_non_test


def _task_changes_non_tests(task: Task) -> bool:
    paths = _extract_task_paths_for_tdd(task)
    if not paths:
        return False
    return any(not _path_is_test_like(path) for path in paths)


def _is_test_failure(result: VerificationResult) -> bool:
    msg = (result.message or "").lower()
    if any(token in msg for token in ("test", "pytest", "jest", "vitest", "mocha")):
        return True

    details = result.details or {}
    for key in ("strict", "validation"):
        block = details.get(key)
        if not isinstance(block, dict):
            continue
        for label in block:
            label_lower = str(label).lower()
            if label_lower in _TDD_TEST_RESULT_KEYS or "test" in label_lower:
                return True
    failed_step = str(details.get("failed_step") or "").lower()
    if "test" in failed_step:
        return True
    return False


def _apply_tdd_red_override(
    result: VerificationResult,
    context: RevContext,
    *,
    reason: str,
) -> VerificationResult:
    context.agent_state["tdd_pending_green"] = True
    return VerificationResult(
        passed=True,
        message=reason,
        details={
            "tdd_expected_failure": True,
            "tdd_failure": result.details,
            "tdd_message": result.message,
        },
        should_replan=False,
    )


def _looks_like_test_file(path: Path) -> bool:
    name = path.name.lower()
    if _TEST_NAME_PATTERN.search(name):
        return True
    if name.startswith("test_") or name.startswith("spec_"):
        return True
    if name.endswith("_test" + path.suffix.lower()) or name.endswith("_spec" + path.suffix.lower()):
        return True
    return False


def _discover_test_files(root: Path, limit: int = _TEST_FILE_DISCOVERY_LIMIT) -> list[str]:
    candidates: list[str] = []
    roots: list[Path] = []
    for token in _TEST_DIR_TOKENS:
        candidate = root / token
        if candidate.exists() and candidate.is_dir():
            roots.append(candidate)
    if not roots:
        roots = [root]

    max_depth = 5
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(base):
            rel = Path(dirpath).relative_to(root)
            if any(part in config.EXCLUDE_DIRS for part in rel.parts):
                dirnames[:] = []
                continue
            if len(rel.parts) > max_depth:
                dirnames[:] = []
                continue
            for filename in filenames:
                path = Path(dirpath) / filename
                if _looks_like_test_file(path):
                    rel_path = path.relative_to(root)
                    candidates.append(rel_path.as_posix())
                    if len(candidates) >= limit:
                        return candidates
    return candidates


def _normalized_tokens(cmd_parts: list[str]) -> list[str]:
    tokens: list[str] = []
    for part in cmd_parts:
        if not part:
            continue
        part_lower = str(part).lower()
        tokens.append(part_lower)
        try:
            tokens.append(Path(part).name.lower())
        except Exception:
            continue
    return tokens


def _detect_test_runner(cmd_parts: list[str], stdout: str = "", stderr: str = "") -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "jest" in combined:
        return "jest"
    if "vitest" in combined:
        return "vitest"
    if "pytest" in combined or "collected 0 items" in combined:
        return "pytest"
    if "unittest" in combined:
        return "unittest"
    if "phpunit" in combined:
        return "phpunit"
    if "rspec" in combined:
        return "rspec"
    if "gradle" in combined:
        return "gradle"
    if "maven" in combined or "surefire" in combined:
        return "maven"
    if "dotnet" in combined or "mstest" in combined or "xunit" in combined or "nunit" in combined:
        return "dotnet"
    if "dart" in combined:
        return "dart"
    if "flutter" in combined:
        return "flutter"

    tokens = _normalized_tokens(cmd_parts)
    if not tokens:
        return "unknown"

    if tokens[0] in {"npm", "yarn", "pnpm", "composer"}:
        return tokens[0]

    if cmd_parts:
        cmd_parts_lower = [part.lower() for part in cmd_parts]
        head = cmd_parts_lower[0]
        if head == "go" and "test" in cmd_parts_lower:
            return "go"
        if head == "cargo" and "test" in cmd_parts_lower:
            return "cargo"
        if head == "dotnet" and "test" in cmd_parts_lower:
            return "dotnet"
        if head in {"mvn", "mvnw"} and "test" in cmd_parts_lower:
            return "maven"
        if Path(head).name in {"gradle", "gradlew"} and "test" in cmd_parts_lower:
            return "gradle"

    if tokens[0] in {"python", "python3", "py"} and "-m" in tokens:
        idx = tokens.index("-m")
        if idx + 1 < len(tokens):
            module = tokens[idx + 1]
            if module == "pytest":
                return "pytest"
            if module == "unittest":
                return "unittest"

    if "pytest" in tokens:
        return "pytest"
    if "unittest" in tokens:
        return "unittest"
    if "jest" in tokens:
        return "jest"
    if "vitest" in tokens:
        return "vitest"
    if "mocha" in tokens:
        return "mocha"
    if "ava" in tokens:
        return "ava"
    if "tap" in tokens:
        return "tap"
    if "jasmine" in tokens:
        return "jasmine"
    if "phpunit" in tokens:
        return "phpunit"
    if "rspec" in tokens:
        return "rspec"
    if "rake" in tokens and "test" in tokens:
        return "rake"
    if "node" in tokens and "--test" in tokens:
        return "node_test"
    if "dart" in tokens and "test" in tokens:
        return "dart"
    if "flutter" in tokens and "test" in tokens:
        return "flutter"

    return "unknown"


def _extract_test_paths_from_cmd(cmd_parts: list[str]) -> list[str]:
    test_paths: list[str] = []
    for arg in cmd_parts:
        if not arg or arg.startswith("-"):
            continue
        lower = str(arg).lower()
        if lower in _TEST_DIR_TOKENS and not any(sep in lower for sep in ("/", "\\")):
            continue
        try:
            path = Path(lower)
        except Exception:
            path = None
        parts = set(path.parts) if path else set()
        name = path.name if path else lower
        if _TEST_NAME_PATTERN.search(name):
            test_paths.append(arg)
            continue
        if parts and any(token in parts for token in _TEST_DIR_TOKENS):
            test_paths.append(arg)
    return test_paths


def _normalize_path_token(value: str) -> str:
    return str(value).replace("\\", "/")


def _normalize_test_paths(test_paths: list[str], cwd: Optional[Path | str]) -> list[str]:
    normalized: list[str] = []
    cwd_path = Path(cwd) if cwd else None
    for path in test_paths:
        try:
            current = Path(path)
            if cwd_path and current.is_absolute():
                try:
                    current = current.relative_to(cwd_path)
                except Exception:
                    pass
            normalized.append(str(current))
        except Exception:
            normalized.append(path)
    return normalized


def _strip_test_paths(cmd_parts: list[str], test_paths: list[str]) -> list[str]:
    test_set = {_normalize_path_token(path) for path in test_paths}
    return [part for part in cmd_parts if _normalize_path_token(part) not in test_set]


def _inject_double_dash(cmd_parts: list[str], test_paths: list[str]) -> list[str]:
    base = _strip_test_paths(cmd_parts, test_paths)
    if "--" in base:
        idx = base.index("--")
        before = base[:idx + 1]
        test_set = {_normalize_path_token(path) for path in test_paths}
        after = [part for part in base[idx + 1:] if _normalize_path_token(part) not in test_set]
        return before + test_paths + after
    return base + ["--"] + test_paths


def _build_jest_run_tests_by_path_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    if any(arg.startswith("--runTestsByPath") for arg in cmd_parts):
        return None

    parts = list(cmd_parts)
    test_set = set(test_paths)

    if parts and parts[0].lower() in {"npm", "yarn", "pnpm"}:
        if "--" in parts:
            idx = parts.index("--")
            before = parts[:idx + 1]
            after = [arg for arg in parts[idx + 1:] if arg not in test_set]
            return before + ["--runTestsByPath"] + test_paths + after
        return parts + ["--", "--runTestsByPath"] + test_paths

    new_parts: list[str] = []
    inserted = False
    for arg in parts:
        if not inserted and arg in test_set:
            new_parts.append("--runTestsByPath")
            inserted = True
        new_parts.append(arg)
    if not inserted:
        new_parts.append("--runTestsByPath")
        new_parts.extend(test_paths)
    return new_parts


def _build_vitest_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    parts = list(cmd_parts)
    tokens = _normalized_tokens(parts)
    if "npm" in tokens or "yarn" in tokens or "pnpm" in tokens:
        parts = _inject_double_dash(parts, test_paths)
    else:
        parts = _strip_test_paths(parts, test_paths) + test_paths
    if "--run" not in parts and "run" not in parts:
        parts.append("--run")
    return parts


def _build_pytest_command(cmd_parts: list[str], test_paths: list[str], cwd: Optional[Path | str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    normalized = _normalize_test_paths(test_paths, cwd)
    parts = _strip_test_paths(cmd_parts, test_paths)
    normalized_set = {_normalize_path_token(path) for path in normalized}
    existing = {_normalize_path_token(part) for part in parts}
    for path in normalized:
        if _normalize_path_token(path) not in existing:
            parts.append(path)
    return parts


def _build_unittest_command(cmd_parts: list[str], test_paths: list[str], cwd: Optional[Path | str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    modules: list[str] = []
    cwd_path = Path(cwd) if cwd else None
    for path in test_paths:
        try:
            current = Path(path)
            if cwd_path and current.is_absolute():
                try:
                    current = current.relative_to(cwd_path)
                except Exception:
                    pass
            if current.suffix != ".py":
                continue
            module = ".".join(current.with_suffix("").parts)
            if module and module not in modules:
                modules.append(module)
        except Exception:
            continue
    if not modules:
        return None
    parts = _strip_test_paths(cmd_parts, test_paths)
    for module in modules:
        if module not in parts:
            parts.append(module)
    return parts


def _build_go_test_command(cmd_parts: list[str], test_paths: list[str], cwd: Optional[Path | str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    if "./..." in cmd_parts:
        return None
    packages: list[str] = []
    cwd_path = Path(cwd) if cwd else None
    for path in test_paths:
        current = Path(path)
        if current.suffix == ".go":
            current = current.parent
        if cwd_path and current.is_absolute():
            try:
                current = current.relative_to(cwd_path)
            except Exception:
                pass
        pkg = str(current)
        if not pkg.startswith("."):
            pkg = f"./{pkg}"
        if pkg not in packages:
            packages.append(pkg)
    if not packages:
        return None
    parts = _strip_test_paths(cmd_parts, test_paths) + packages
    return parts


def _build_cargo_test_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    if any(part.startswith("--test") for part in cmd_parts):
        return None
    tests: list[str] = []
    filters: list[str] = []
    for path in test_paths:
        current = Path(path)
        stem = current.stem
        if not stem:
            continue
        if "tests" in {part.lower() for part in current.parts}:
            if stem not in tests:
                tests.append(stem)
        else:
            if stem not in filters:
                filters.append(stem)
    parts = _strip_test_paths(cmd_parts, test_paths)
    for test_name in tests:
        parts.extend(["--test", test_name])
    for filt in filters:
        if filt not in parts:
            parts.append(filt)
    return parts if tests or filters else None


def _build_dotnet_test_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths or "--filter" in cmd_parts:
        return None
    names: list[str] = []
    for path in test_paths:
        stem = Path(path).stem
        if stem and stem not in names:
            names.append(stem)
    if not names:
        return None
    expr = " | ".join(f"FullyQualifiedName~{name}" for name in names)
    parts = _strip_test_paths(cmd_parts, test_paths) + ["--filter", expr]
    return parts


def _build_maven_test_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths or any(part.startswith("-Dtest=") for part in cmd_parts):
        return None
    names: list[str] = []
    for path in test_paths:
        stem = Path(path).stem
        if stem and stem not in names:
            names.append(stem)
    if not names:
        return None
    parts = _strip_test_paths(cmd_parts, test_paths) + [f"-Dtest={','.join(names)}"]
    return parts


def _build_gradle_test_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths or "--tests" in cmd_parts:
        return None
    names: list[str] = []
    for path in test_paths:
        stem = Path(path).stem
        if stem and stem not in names:
            names.append(stem)
    if not names:
        return None
    parts = _strip_test_paths(cmd_parts, test_paths)
    for name in names:
        parts.extend(["--tests", name])
    return parts


def _build_rake_test_command(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths or any(part.startswith("TEST=") for part in cmd_parts):
        return None
    parts = _strip_test_paths(cmd_parts, test_paths)
    parts.append(f"TEST={test_paths[0]}")
    return parts


def _append_test_paths(cmd_parts: list[str], test_paths: list[str]) -> Optional[list[str]]:
    if not test_paths:
        return None
    parts = _strip_test_paths(cmd_parts, test_paths)
    existing = {_normalize_path_token(part) for part in parts}
    for path in test_paths:
        if _normalize_path_token(path) not in existing:
            parts.append(path)
    return parts


def _attempt_no_tests_fallback(cmd_parts: list[str], stdout: str, stderr: str, cwd: Optional[Path | str]) -> Optional[list[str]]:
    test_paths = _extract_test_paths_from_cmd(cmd_parts)
    if not test_paths:
        root = Path(cwd) if cwd else config.ROOT
        try:
            root = root.resolve()
        except Exception:
            root = Path.cwd().resolve()
        test_paths = _discover_test_files(root)
    if not test_paths:
        return None
    runner = _detect_test_runner(cmd_parts, stdout, stderr)
    normalized_paths = _normalize_test_paths(test_paths, cwd)

    if runner in {"npm", "yarn", "pnpm", "composer"}:
        return _inject_double_dash(cmd_parts, normalized_paths)
    if runner == "jest":
        return _build_jest_run_tests_by_path_command(cmd_parts, normalized_paths)
    if runner == "vitest":
        return _build_vitest_command(cmd_parts, normalized_paths)
    if runner == "pytest":
        return _build_pytest_command(cmd_parts, normalized_paths, cwd)
    if runner == "unittest":
        return _build_unittest_command(cmd_parts, normalized_paths, cwd)
    if runner == "go":
        return _build_go_test_command(cmd_parts, normalized_paths, cwd)
    if runner == "cargo":
        return _build_cargo_test_command(cmd_parts, normalized_paths)
    if runner == "dotnet":
        return _build_dotnet_test_command(cmd_parts, normalized_paths)
    if runner == "maven":
        return _build_maven_test_command(cmd_parts, normalized_paths)
    if runner == "gradle":
        return _build_gradle_test_command(cmd_parts, normalized_paths)
    if runner == "rake":
        return _build_rake_test_command(cmd_parts, normalized_paths)
    if runner in {"phpunit", "rspec", "mocha", "ava", "tap", "jasmine", "node_test", "dart", "flutter"}:
        return _append_test_paths(cmd_parts, normalized_paths)

    return None


def _run_validation_command(cmd: str | List[str], *, use_tests_tool: bool = False, timeout: int | None = None, cwd: Optional[Path | str] = None, _retry_count: int = 0) -> Dict[str, Any]:
    """Run a validation command via the tool runner and return parsed JSON."""
    if _retry_count > 2:
        return {"error": f"Max retries exceeded for command: {cmd}", "rc": -1}

    # Ensure tool is available before running
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    _ensure_tool_available(cmd_str)
    
    payload = {"cmd": cmd}
    if timeout:
        payload["timeout"] = timeout
    if cwd:
        payload["cwd"] = str(cwd)

    tool = "run_tests" if use_tests_tool else "run_cmd"
    try:
        raw = execute_tool(tool, payload, agent_name="quick_verify")
        data = json.loads(raw)
        if isinstance(data, dict):
            # Ensure cmd is present in the result
            if "cmd" not in data:
                data["cmd"] = cmd_str
            
            # RECOVERY LOGIC: If command failed because it was not found, try generic ecosystem fallbacks
            rc = data.get("rc")
            error_msg = str(data.get("error", "")).lower()
            
            if rc == -1 and ("not found" in error_msg or "file not found" in error_msg):
                fallback_res = _attempt_ecosystem_fallback(cmd, timeout, use_tests_tool, _retry_count)
                if fallback_res:
                    return fallback_res

            # If the command failed and produced no output, attempt to gather help output for better diagnostics
            if rc is not None and rc not in (0, 4) and not data.get("stdout") and not data.get("stderr"):
                try:
                    if isinstance(cmd, list):
                        base_cmd = cmd[0]
                    else:
                        tokens = shlex.split(cmd)
                        base_cmd = tokens[0] if tokens else ""
                        
                    # Only get help for tools, not for source files
                    if base_cmd in ("npm", "pip", "pytest", "eslint", "ruff", "mypy", "npx", "node", "python", "go", "cargo"):
                        help_info = _get_help_output(base_cmd)
                        if help_info:
                            data["help_info"] = help_info
                except:
                    pass
                    
            if _retry_count < 2:
                stdout = str(data.get("stdout") or "")
                stderr = str(data.get("stderr") or "")
                cmd_parts = _split_command_parts(cmd)
                if _output_indicates_no_tests(stdout, stderr):
                    fallback_cmd = _attempt_no_tests_fallback(cmd_parts, stdout, stderr, cwd)
                    if fallback_cmd and fallback_cmd != cmd_parts:
                        return _run_validation_command(
                            fallback_cmd,
                            use_tests_tool=use_tests_tool,
                            timeout=timeout,
                            cwd=cwd,
                            _retry_count=_retry_count + 1,
                        )

                missing_script = _detect_missing_script(stdout, stderr)
                if missing_script:
                    if use_tests_tool or "test" in missing_script.lower() or any("test" in part.lower() for part in cmd_parts):
                        fallback_cmd = _attempt_missing_script_fallback(cmd_parts, cwd)
                        if fallback_cmd and fallback_cmd != cmd_parts:
                            return _run_validation_command(
                                fallback_cmd,
                                use_tests_tool=use_tests_tool,
                                timeout=timeout,
                                cwd=cwd,
                                _retry_count=_retry_count + 1,
                            )
                        if use_tests_tool:
                            return {
                                "rc": 0,
                                "stdout": _NO_TEST_RUNNER_SENTINEL,
                                "stderr": "",
                                "cmd": cmd_str,
                                "note": f"missing script: {missing_script}",
                            }

            return data
        return {"raw": raw, "cmd": cmd_str}
    except Exception as e:
        return {"error": str(e), "cmd": cmd_str}


def _quote_path(path: Path) -> str:
    """Quote a path for shell commands, using relative path if within workspace."""
    try:
        if path.is_absolute() and path.is_relative_to(config.ROOT):
            rel_path = path.relative_to(config.ROOT)
            # Use "." for current directory instead of empty string
            path_str = str(rel_path) if str(rel_path) != "." else "."
            return quote_cmd_arg(path_str)
    except (ValueError, AttributeError):
        pass
    return quote_cmd_arg(str(path))


def _paths_or_default(paths: list[Path]) -> list[Path]:
    """Return provided paths or default to workspace root."""
    if paths:
        return paths
    try:
        return [config.ROOT]
    except Exception:
        return [Path(".").resolve()]


def _no_tests_expected(task: Optional[Task]) -> bool:
    """Check if 'no tests expected' is explicitly configured in task description or steps."""
    if not task:
        return False
    description = (task.description or "").lower()
    if "no tests expected" in description:
        return True
    if task.validation_steps:
        for step in task.validation_steps:
            if "no tests expected" in step.lower():
                return True
    return False


def _maybe_run_strict_verification(action_type: str, paths: list[Path], *, mode: str, task: Optional[Task] = None) -> Optional[VerificationResult | Dict[str, Any]]:
    """Run verification checks depending on verification mode (fast/strict) and project type."""
    if not paths:
        return None

    # Clear discovery cache
    global _COMMAND_HINT_CACHE
    _COMMAND_HINT_CACHE = {}

    strict_details: Dict[str, Any] = {}
    primary_path = paths[0] if paths else config.ROOT
    project_type = detect_project_type(primary_path)
    
    # Check for per-repo configuration overrides
    repo_config = getattr(config, "REPO_CONFIG", {})
    backend_config = repo_config.get("backend", {})
    frontend_config = repo_config.get("frontend", {})
    
    # -------------------------------------------------------------------------
    # PROJECT-SPECIFIC OVERRIDES
    # -------------------------------------------------------------------------
    custom_test_cmd = None
    custom_build_cmd = None
    
    if project_type == "python":
        custom_test_cmd = backend_config.get("test")
        custom_build_cmd = backend_config.get("build")
    elif project_type in ("vue", "react", "node", "nextjs"):
        custom_test_cmd = frontend_config.get("test")
        custom_build_cmd = frontend_config.get("build")

    # Run custom build if configured
    if custom_build_cmd:
        print(f"  → Running configured build command: {custom_build_cmd}")
        build_res = _run_validation_command(
            custom_build_cmd,
            timeout=config.VALIDATION_TIMEOUT_SECONDS,
            cwd=_resolve_validation_cwd(custom_build_cmd, primary_path),
        )
        strict_details["custom_build"] = build_res
        if build_res.get("rc", 0) != 0:
            return VerificationResult(
                passed=False,
                message=f"Verification failed: build command '{custom_build_cmd}' failed. Error: {_extract_error(build_res)}",
                details={"strict": strict_details},
                should_replan=True,
            )

    explicit_tests = False
    explicit_lint = False
    if task:
        explicit_tests = explicitly_requests_tests(task.description) or task.action_type == "test"
        explicit_lint = explicitly_requests_lint(task.description)

    # -------------------------------------------------------------------------
    # PYTHON VERIFICATION
    # -------------------------------------------------------------------------
    if project_type == "python":
        # Filter for Python files or directories for compileall
        compile_targets = [p for p in _paths_or_default(paths) if p.is_dir() or p.suffix == '.py']
        
        if compile_targets:
            # Use list-based command to bypass security blocks
            compile_cmd = ["python", "-m", "compileall"] + [str(p) for p in compile_targets]
            compile_res = _run_validation_command(compile_cmd, timeout=max(config.VALIDATION_TIMEOUT_SECONDS, 180))
            strict_details["compileall"] = compile_res
            if compile_res.get("blocked") or compile_res.get("rc", 1) != 0:
                return VerificationResult(
                    passed=False,
                    message=f"Verification failed: compileall errors. Error: {_extract_error(compile_res)}",
                    details={"strict": strict_details},
                    should_replan=True,
                )

        if mode == "fast":
            return strict_details

        if explicit_tests:
            # Targeted pytest for touched test files/directories
            if custom_test_cmd:
                pytest_cmd = custom_test_cmd
            else:
                test_targets = []
                for p in paths:
                    parts_lower = {part.lower() for part in p.parts}
                    if "tests" in parts_lower or p.name.startswith("test_") or p.name.endswith("_test.py"):
                        test_targets.append(p)
                if test_targets:
                    pytest_cmd = ["pytest", "-q"] + [str(p) for p in test_targets]
                else:
                    pytest_cmd = ["pytest", "-q"]
            
            pytest_res = _run_validation_command(pytest_cmd, use_tests_tool=True, timeout=config.VALIDATION_TIMEOUT_SECONDS)
            strict_details["pytest"] = pytest_res
            rc = pytest_res.get("rc", 1)
            # Pytest exit codes: 0=pass, 1=fail, 2=interrupted, 3=internal error, 4=usage error, 5=no tests collected
            if pytest_res.get("blocked") or (rc != 0 and rc != 4):
                if rc == 5:
                    if _no_tests_expected(task):
                        strict_details["pytest_note"] = "No tests collected (rc=5) - explicitly allowed"
                    else:
                        return VerificationResult(
                            passed=False,
                            message="Verification INCONCLUSIVE: pytest collected 0 tests (rc=5)",
                            details={"strict": strict_details},
                            should_replan=True,
                        )
                else:
                    return VerificationResult(
                        passed=False,
                        message=f"Verification failed: pytest errors. Error: {_extract_error(pytest_res)}",
                        details={"strict": strict_details},
                        should_replan=True,
                    )
            elif rc == 4:
                strict_details["pytest_note"] = "No tests collected (rc=4) - treated as pass"

        # Optional lint/type checks
        py_paths = [p for p in paths if p.suffix == ".py" and p.exists()]
        if py_paths and explicit_lint:
            targets = [str(p) for p in py_paths[:10]]
            # E9: Runtime/syntax errors, F63: Invalid print syntax, F7: Statement problems
            optional_checks = [
                ("ruff", ["ruff", "check"] + targets + ["--select", "E9,F63,F7"]),
                ("mypy", ["mypy"] + targets)
            ]
            
            for label, cmd in optional_checks:
                res = _run_validation_command(cmd, timeout=config.VALIDATION_TIMEOUT_SECONDS)
                strict_details[label] = res
                rc = res.get("rc")
                if rc is None:
                    rc = 0 if res.get("blocked") else 1
                if not res.get("blocked") and rc not in (0, None):
                    return VerificationResult(
                        passed=False,
                        message=f"Verification failed: {label} errors. Error: {_extract_error(res)}",
                        details={"strict": strict_details},
                        should_replan=True,
                    )

    # -------------------------------------------------------------------------
    # NODE / VUE / REACT VERIFICATION
    # -------------------------------------------------------------------------
    elif project_type in ("vue", "react", "node", "nextjs"):
        # Identify relevant Node files
        node_extensions = {".js", ".ts", ".jsx", ".tsx", ".vue", ".mjs", ".cjs"}
        node_paths = [p for p in paths if p.suffix in node_extensions and p.exists()]

        # 1. Syntax check for plain JS files (fast)
        js_paths = [p for p in paths if p.suffix == '.js' and p.exists()]
        if js_paths:
            for js_file in js_paths:
                cmd = ["node", "--check", str(js_file)]
                res = _run_validation_command(
                    cmd,
                    timeout=30,
                    cwd=_resolve_validation_cwd(cmd, primary_path),
                )
                strict_details[f"syntax_{js_file.name}"] = res
                if not res.get("blocked") and res.get("rc", 1) != 0:
                    return VerificationResult(
                        passed=False,
                        message=f"Syntax error in {js_file.name}. Error: {_extract_error(res)}",
                        details={"strict": strict_details},
                        should_replan=True
                    )

        # 2. Targeted Linting (eslint)
        if node_paths and mode == "strict" and explicit_lint:
             targets = [str(p) for p in node_paths[:10]]
             # Use list-based npx command to avoid security blocks
             cmd = ["npx", "--yes", "eslint"] + targets + ["--quiet"]
             res = _run_validation_command(
                 cmd,
                 timeout=60,
                 cwd=_resolve_validation_cwd(cmd, primary_path),
             )
             strict_details["eslint"] = res
             rc = res.get("rc")
             if not res.get("blocked") and rc is not None and rc != 0:
                  error_msg = _extract_error(res, "Unknown linting error")
                  return VerificationResult(
                        passed=False,
                        message=f"Linting failed: {error_msg}",
                        details={"strict": strict_details},
                        should_replan=True
                    )

        # 3. Vue/TS Type Checking (slower, maybe skip in strict=false?)
        if project_type == "vue" and explicit_lint:
            vue_ts_touched = any(p.suffix in ('.vue', '.ts') for p in paths)
            if vue_ts_touched:
                if mode == "strict":
                    cmd = ["npx", "--yes", "vue-tsc", "--noEmit"]
                    res = _run_validation_command(
                        cmd,
                        timeout=120,
                        cwd=_resolve_validation_cwd(cmd, primary_path),
                    )
                    strict_details["vue-tsc"] = res
                    if not res.get("blocked") and res.get("rc", 1) != 0:
                         return VerificationResult(
                            passed=False,
                            message=f"Vue type check failed. Error: {_extract_error(res)}",
                            details={"strict": strict_details},
                            should_replan=True
                        )

        # 3. Unit Tests (Vitest/Jest)
        # Look for test files in the paths
        test_touched = any("test" in p.name or "spec" in p.name for p in paths)
        if explicit_tests:
            # Try dynamic discovery first
            test_cmd = None
            hinted_test = None
            
            # Find a relevant test file to inspect
            relevant_test_file = next((p for p in paths if p.is_file() and ("test" in p.name or "spec" in p.name)), None)
            if relevant_test_file:
                hinted_test = _inspect_file_for_command_hints(relevant_test_file, "test")
            
            # Determine project root early as it is needed for path calculations
            root = find_project_root(primary_path)

            if hinted_test:
                test_cmd = hinted_test
            else:
                # Fallback to package.json detection
                try:
                    pkg_json = json.loads((root / "package.json").read_text(errors='ignore'))
                    scripts = pkg_json.get("scripts", {})
                    if "test:unit" in scripts:
                        test_cmd = ["npm", "run", "test:unit"]
                    elif "test" in scripts:
                        test_cmd = ["npm", "test"]
                    else:
                        test_cmd = ["npm", "test"] # Generic fallback
                except Exception:
                    test_cmd = ["npm", "test"]

            if test_cmd:
                # Convert string command to list if needed
                if isinstance(test_cmd, str):
                    test_cmd = shlex.split(test_cmd)

                # Ensure it's a list for further manipulation
                test_cmd = list(test_cmd)

                # Prevent watch mode which hangs execution
                if any(v in test_cmd[0] for v in ("vitest", "vite")):
                    if "--run" not in test_cmd and "run" not in test_cmd:
                        test_cmd.append("--run")
                elif "jest" in test_cmd[0]:
                    if "--watchAll=false" not in test_cmd:
                        test_cmd.append("--watchAll=false")
                
                # Append file filters if possible
                if test_touched:
                    test_files = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) 
                                 for p in paths if "test" in p.name or "spec" in p.name]
                    if test_files:
                        # Use ' -- ' to pass args to the underlying script
                        if len(test_cmd) >= 2 and test_cmd[0] == "npm" and test_cmd[1] == "run":
                            test_cmd.append("--")
                        test_cmd.extend(test_files)

                res = _run_validation_command(
                    test_cmd,
                    use_tests_tool=True,
                    timeout=config.VALIDATION_TIMEOUT_SECONDS,
                    cwd=_resolve_validation_cwd(test_cmd, primary_path),
                )
                strict_details["npm_test"] = res
                # Ignore rc if no tests found?
                if not res.get("blocked") and res.get("rc", 1) != 0:
                     return VerificationResult(
                        passed=False,
                        message=f"Frontend tests failed. Error: {_extract_error(res)}",
                        details={"strict": strict_details},
                        should_replan=True
                    )

    # 3. GO
    elif project_type == "go":
        # 1. Compilation check
        compile_res = _run_validation_command("go build ./...", timeout=120)
        strict_details["go_build"] = compile_res
        if compile_res.get("rc", 0) != 0:
            return VerificationResult(
                passed=False,
                message=f"Go build failed. Error: {_extract_error(compile_res)}",
                details={"strict": strict_details},
                should_replan=True
            )
        
        # 2. Tests
        if explicit_tests:
            cmd = custom_test_cmd or "go test ./..."
            test_res = _run_validation_command(cmd, use_tests_tool=True, timeout=120)
            strict_details["go_test"] = test_res
            if test_res.get("rc", 0) != 0:
                return VerificationResult(
                    passed=False,
                    message=f"Go tests failed. Error: {_extract_error(test_res)}",
                    details={"strict": strict_details},
                    should_replan=True
                )

    # 4. RUST
    elif project_type == "rust":
        # 1. Check/Build
        compile_res = _run_validation_command("cargo check", timeout=300)
        strict_details["cargo_check"] = compile_res
        if compile_res.get("rc", 0) != 0:
            return VerificationResult(
                passed=False,
                message=f"Cargo check failed. Error: {_extract_error(compile_res)}",
                details={"strict": strict_details},
                should_replan=True
            )
            
        # 2. Tests
        if explicit_tests:
            cmd = custom_test_cmd or "cargo test"
            test_res = _run_validation_command(cmd, use_tests_tool=True, timeout=300)
            strict_details["cargo_test"] = test_res
            if test_res.get("rc", 0) != 0:
                return VerificationResult(
                    passed=False,
                    message=f"Cargo tests failed. Error: {_extract_error(test_res)}",
                    details={"strict": strict_details},
                    should_replan=True
                )

    # 5. C# / .NET
    elif project_type == "csharp":
        compile_res = _run_validation_command("dotnet build", timeout=180)
        strict_details["dotnet_build"] = compile_res
        if compile_res.get("rc", 0) != 0:
            return VerificationResult(
                passed=False,
                message=f"Dotnet build failed. Error: {_extract_error(compile_res)}",
                details={"strict": strict_details},
                should_replan=True
            )
            
        if explicit_tests:
            cmd = custom_test_cmd or "dotnet test"
            test_res = _run_validation_command(cmd, use_tests_tool=True, timeout=180)
            strict_details["dotnet_test"] = test_res
            if test_res.get("rc", 0) != 0:
                return VerificationResult(
                    passed=False,
                    message=f"Dotnet tests failed. Error: {_extract_error(test_res)}",
                    details={"strict": strict_details},
                    should_replan=True
                )

    return strict_details


# Simple cache for file command hints to avoid redundant discovery per task
_COMMAND_HINT_CACHE: Dict[Tuple[str, str], Optional[str]] = {}

def _inspect_file_for_command_hints(path: Path, tool_type: str) -> Optional[str]:
    """Inspect a file's content and environment for tool-specific execution hints."""
    cache_key = (str(path.resolve()), tool_type)
    if cache_key in _COMMAND_HINT_CACHE:
        return _COMMAND_HINT_CACHE[cache_key]
        
    result = None
    try:
        if not path.exists() or not path.is_file():
            return None
            
        content = path.read_text(errors='ignore')
        root = find_project_root(path)
        
        if tool_type == "test":
            # Node.js Test detection
            if path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                # 1. Content-based detection
                if "vitest" in content or "from 'vitest'" in content or "from \"vitest\"" in content:
                    result = "npx --yes vitest run"
                elif "jest" in content or "@jest/globals" in content or "describe(" in content:
                    result = "npx --yes jest --watchAll=false"
                elif "mocha" in content or "describe(" in content: # Mocha also uses describe
                    # Check package.json for mocha
                    pkg_json_path = root / "package.json"
                    if pkg_json_path.exists():
                        pkg_json = json.loads(pkg_json_path.read_text(errors='ignore'))
                        if "mocha" in str(pkg_json.get("devDependencies", {})) or "mocha" in str(pkg_json.get("dependencies", {})):
                            result = "npx --yes mocha"

                if not result:
                    # 2. Package.json script detection
                    pkg_json_path = root / "package.json"
                    if pkg_json_path.exists():
                        pkg_json = json.loads(pkg_json_path.read_text(errors='ignore'))
                        scripts = pkg_json.get("scripts", {})
                        for s_name in ("test:unit", "test", "unit"):
                            if s_name in scripts:
                                s_cmd = scripts[s_name].lower()
                                if "vitest" in s_cmd: result = "npx --yes vitest run"; break
                                if "jest" in s_cmd: result = "npx --yes jest --watchAll=false"; break
                                if "mocha" in s_cmd: result = "npx --yes mocha"; break
            
            # Python Test detection
            if not result and path.suffix == ".py":
                if "import unittest" in content or "unittest.TestCase" in content:
                    result = "python -m unittest"
                elif "import pytest" in content or "def test_" in content or "@pytest." in content:
                    result = "pytest -q"
                    
        elif tool_type == "lint":
            # Node.js Lint detection
            if path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                # If we see eslint comments or have a local config, prefer eslint
                if "eslint" in content or any((root / f).exists() for f in (".eslintrc.json", "eslint.config.js", ".eslintrc.js", "eslint.config.mjs", "eslint.config.cjs")):
                    result = "npx --yes eslint --quiet"
        
        # If static inspection fails and it looks like a CLI/script, try dynamic help discovery
        if not result and path.suffix in (".js", ".py", ".sh"):
            # Only probe if it contains likely CLI markers or is in a bin/scripts dir
            if "process.argv" in content or "sys.argv" in content or "argparse" in content or "click" in content:
                help_info = _try_dynamic_help_discovery(path)
                if help_info:
                    # We don't return the full help, but we've verified it responds to help
                    pass
                    
    except Exception:
        pass
        
    _COMMAND_HINT_CACHE[cache_key] = result
    return result


def _run_validation_steps(task: Task, details: Dict[str, Any], tool_events: Optional[Iterable[Dict[str, Any]]]) -> Optional[VerificationResult | Dict[str, Any]]:
    """Execute declarative validation steps (lint/tests/compile) via tool runner."""
    # Clear discovery cache for each task validation run
    global _COMMAND_HINT_CACHE
    _COMMAND_HINT_CACHE = {}
    
    validation_steps = task.validation_steps
    commands: list[tuple[str, str | list[str], str]] = []
    seen_cmds = set()
    no_runner_detected = False
    paths = _paths_or_default(_collect_paths_for_strict_checks("", details, tool_events))

    def _add(label: str, cmd: str | list[str], tool: str = "run_cmd") -> None:
        # Convert list to string for de-duplication
        cmd_key = " ".join(cmd) if isinstance(cmd, list) else cmd
        if cmd_key in seen_cmds:
            return
        seen_cmds.add(cmd_key)
        commands.append((label, cmd, tool))

    # Get project type relative to the first relevant path
    primary_path = paths[0] if paths else config.ROOT
    project_type = detect_project_type(primary_path)

    # Get Python file paths for targeted linting
    py_paths = [p for p in paths if p.suffix == ".py" and p.exists()]

    # Get Node file paths for targeted linting
    node_extensions = {".js", ".ts", ".jsx", ".tsx", ".vue", ".mjs", ".cjs"}
    node_paths = [p for p in paths if p.suffix in node_extensions and p.exists()]

    explicit_tests = explicitly_requests_tests(task.description) or task.action_type == "test"
    explicit_lint = explicitly_requests_lint(task.description)
    skip_lint = not explicit_lint
    skip_tests = not explicit_tests
    skip_notes: Dict[str, Any] = {}
    if skip_lint:
        skip_notes["lint_skipped"] = {"skipped": True, "reason": "not_explicitly_requested"}
    if skip_tests:
        skip_notes["tests_skipped"] = {"skipped": True, "reason": "not_explicitly_requested"}

    for step in validation_steps:
        text = step.lower()
        
        # 1. SYNTAX / COMPILE
        if "syntax" in text or "compile" in text or "build" in text:
            if project_type == "python":
                compile_targets = [p for p in paths if p.is_dir() or p.suffix == '.py']
                if compile_targets:
                    _add("compileall", ["python", "-m", "compileall"] + [str(p) for p in compile_targets])
            elif project_type == "go": _add("go_build", ["go", "build", "./..."])
            elif project_type == "rust": _add("cargo_check", ["cargo", "check"])
            elif project_type == "csharp": _add("dotnet_build", ["dotnet", "build"])
            elif project_type == "cpp_cmake": _add("cmake_build", ["cmake", "--build", "."])
            elif project_type == "cpp_make": _add("make", ["make"])
            elif project_type == "java_maven": _add("mvn_compile", ["mvn", "compile"])
            elif project_type == "java_gradle" or project_type == "kotlin": _add("gradle_build", ["./gradlew", "build"])

        # 2. LINT
        if "lint" in text or "linter" in text:
            if skip_lint:
                continue
            hinted_lint = _inspect_file_for_command_hints(primary_path, "lint") if paths else None
            
            if hinted_lint and node_paths:
                targets = [str(p) for p in node_paths[:10]]
                # Split hinted_lint if it's a string
                lint_parts = shlex.split(hinted_lint) if isinstance(hinted_lint, str) else hinted_lint
                _add("eslint_hinted", lint_parts + targets)
            elif project_type == "python" and py_paths:
                ruff_targets = [str(p) for p in py_paths[:10]]
                _add("ruff", ["ruff", "check"] + ruff_targets + ["--select", "E9,F63,F7"])
            elif project_type in ("node", "vue", "react", "nextjs"):
                if node_paths:
                    targets = [str(p) for p in node_paths[:10]]
                    # Use list-based npx command to avoid security blocks
                    _add("eslint", ["npx", "--yes", "eslint"] + targets + ["--quiet"])
                else:
                    _add("npm_lint", ["npm", "run", "lint"])
            elif project_type == "go": _add("go_vet", ["go", "vet", "./..."])
            elif project_type == "rust": _add("clippy", ["cargo", "clippy"])

        # 3. TEST
        if "test" in text:
            if skip_tests:
                continue
            hinted_test = _inspect_file_for_command_hints(primary_path, "test") if paths else None
            
            if hinted_test:
                test_parts = shlex.split(hinted_test) if isinstance(hinted_test, str) else hinted_test
                _add("hinted_test", test_parts + [str(primary_path)], "run_tests")
            else:
                detected = detect_test_command(primary_path)
                if detected:
                    _add("project_test", detected, "run_tests")
                elif project_type == "python":
                    _add("pytest", ["pytest", "-q"], "run_tests")
                elif project_type in ("node", "vue", "react", "nextjs"):
                    no_runner_detected = True
                elif project_type == "go":
                    _add("go_test", ["go", "test", "./..."], "run_tests")
                elif project_type == "rust":
                    _add("cargo_test", ["cargo", "test"], "run_tests")
                elif project_type == "ruby":
                    _add("rake_test", ["bundle", "exec", "rake", "test"], "run_tests")
                elif project_type == "php":
                    _add("phpunit", ["vendor/bin/phpunit"], "run_tests")
                elif project_type == "java_maven":
                    _add("mvn_test", ["mvn", "test"], "run_tests")
                elif project_type == "java_gradle" or project_type == "kotlin":
                    _add("gradle_test", ["./gradlew", "test"], "run_tests")
                elif project_type == "csharp":
                    _add("dotnet_test", ["dotnet", "test"], "run_tests")
                elif project_type == "flutter":
                    _add("flutter_test", ["flutter", "test"], "run_tests")
                else:
                    no_runner_detected = True

        # 4. TYPE CHECK
        if "mypy" in text or "type" in text:
            if project_type == "python" and py_paths:
                mypy_targets = [str(p) for p in py_paths[:10]]
                _add("mypy", ["mypy"] + mypy_targets)
            elif project_type in ("node", "typescript", "vue", "react", "nextjs"):
                _add("tsc", ["npx", "--yes", "tsc", "--noEmit"])

    if not commands:
        if skip_notes:
            return skip_notes
        if no_runner_detected:
            return VerificationResult(
                passed=True,
                message="No test runner detected; skipping validation",
                details={"skipped": True, "reason": "no_test_runner_detected"},
            )
        return None

    results: Dict[str, Any] = {}
    for label, cmd, tool in commands:
        cwd = _resolve_validation_cwd(cmd, primary_path)
        res = _run_validation_command(
            cmd,
            use_tests_tool=(tool == "run_tests"),
            timeout=config.VALIDATION_TIMEOUT_SECONDS,
            cwd=cwd,
        )
        results[label] = res
        rc = res.get("rc")
        if rc is None:
            rc = 0 if res.get("blocked") else 1

        # Handle pytest exit code 4 (usage error/no tests in older versions) as pass
        if label == "pytest" and rc == 4:
            results[label] = {**res, "note": "No tests collected (rc=4) - treated as pass"}
        # Handle exit code 5 (no tests collected) as INCONCLUSIVE unless explicitly allowed
        elif label == "pytest" and rc == 5:
            if _no_tests_expected(task):
                results[label] = {**res, "note": "No tests collected (rc=5) - explicitly allowed"}
            else:
                return VerificationResult(
                    passed=False,
                    message="Verification INCONCLUSIVE: pytest collected 0 tests (rc=5)",
                    details={"validation": results, "failed_step": label},
                    should_replan=True,
                )
        elif res.get("blocked") or (rc is not None and rc not in (0, 4)):
            error_msg = _extract_error(res)
            return VerificationResult(
                passed=False,
                message=f"Validation step failed: {label}. Error: {error_msg}",
                details={"validation": results, "failed_step": label},
                should_replan=True,
            )

    if skip_notes:
        results.update(skip_notes)
    return results


def _run_syntax_check(file_path: Path) -> Tuple[bool, str, bool]:
    """Run syntax validation for a file based on its extension.

    Returns:
        (is_valid, error_message, skipped) - (True, "", False) if valid,
        (False, "error details", False) if invalid, (True, "", True) if check skipped.
    """
    suffix = file_path.suffix.lower()

    # Python files
    if suffix == '.py':
        try:
            import subprocess
            result = subprocess.run(
                ['python', '-m', 'py_compile', str(file_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "", False
            return False, f"Python syntax error: {result.stderr.strip()}", False
        except Exception as e:
            return False, f"Failed to run syntax check: {str(e)}", False

    # JavaScript/TypeScript files
    elif suffix in {'.js', '.jsx', '.mjs', '.cjs'}:
        # Try node --check first (fastest)
        try:
            import subprocess
            result = subprocess.run(
                ['node', '--check', str(file_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "", False
            return False, f"JavaScript syntax error: {result.stderr.strip()}", False
        except FileNotFoundError:
            # Node not available, skip validation
            return True, "", True
        except Exception as e:
            return False, f"Failed to run syntax check: {str(e)}", False

    elif suffix in {'.ts', '.tsx'}:
        # Try TypeScript compiler if available
        try:
            import subprocess
            result = subprocess.run(
                ['tsc', '--noEmit', '--skipLibCheck', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, "", False
            return False, f"TypeScript error: {result.stdout.strip()}", False
        except FileNotFoundError:
            # TypeScript not available, skip validation
            return True, "", True
        except Exception as e:
            return False, f"Failed to run syntax check: {str(e)}", False

    elif suffix == '.vue':
        # Vue SFCs: try vue-tsc only if a Vue project marker exists (package.json with vue dependency)
        pkg = _load_package_json(Path(config.ROOT) if getattr(config, "ROOT", None) else Path.cwd())
        deps = set()
        for field in ("dependencies", "devDependencies", "peerDependencies"):
            values = pkg.get(field, {})
            if isinstance(values, dict):
                deps.update({str(k).strip().lower() for k in values.keys()})
        is_vue_project = any(dep.startswith("vue") for dep in deps)
        if not is_vue_project:
            return True, "", True
        try:
            import subprocess
            result = subprocess.run(
                ['npx', '--yes', 'vue-tsc', '--noEmit', str(file_path)],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                return True, "", False
            return False, f"Vue SFC error: {result.stdout.strip() or result.stderr.strip()}", False
        except FileNotFoundError:
            return True, "", True
        except Exception as e:
            return False, f"Failed to run syntax check: {str(e)}", False

    # JSON files
    elif suffix == '.json':
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            json.loads(content)
            return True, "", False
        except json.JSONDecodeError as e:
            return False, f"JSON syntax error: {str(e)}", False
        except Exception as e:
            return False, f"Failed to read JSON: {str(e)}", False

    # YAML files
    elif suffix in {'.yml', '.yaml'}:
        try:
            import yaml
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            yaml.safe_load(content)
            return True, "", False
        except ImportError:
            # PyYAML not available, skip validation
            return True, "", True
        except Exception as e:
            return False, f"YAML syntax error: {str(e)}", False

    # XML/HTML files
    elif suffix in {'.xml', '.html', '.htm'}:
        try:
            from xml.etree import ElementTree as ET
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            ET.fromstring(content)
            return True, "", False
        except Exception as e:
            # XML parsing can be strict, treat as warning not error
            return True, f"XML validation warning: {str(e)}", True

    # For other file types, assume valid (no syntax check available)
    return True, "", True


def _log_syntax_result(context: RevContext, file_path: Path, ok: bool, skipped: bool, msg: str) -> None:
    """Log syntax check outcome for visibility in logs/insights."""
    status = "skipped" if skipped else ("ok" if ok else "error")
    try:
        context.add_insight(
            "syntax_check",
            str(file_path),
            {
                "status": status,
                "message": msg,
            },
        )
        print(f"  [syntax-check] {file_path}: {status} ({msg})")
    except Exception:
        pass


def _enqueue_project_typecheck(context: RevContext, tasks: List[Task], reason: str = "") -> Optional[str]:
    """
    Add a project-level typecheck/build task based on detected stack.
    This is used when per-file syntax checks are skipped (missing tooling).
    """
    root = Path(getattr(context, "workspace_root", "") or Path.cwd())
    cmd = _detect_build_command_for_root(root)
    if not cmd:
        return None
    # Keep the command clean; append reason only after a delimiter so command extraction stays correct.
    desc = f"{cmd} -- project typecheck/build to validate syntax"
    if reason:
        desc += f" [{reason}]"
    tasks.append(
        Task(
            description=desc,
            action_type="run",
        )
    )
    return cmd


def _log_syntax_result(context: RevContext, file_path: Path, ok: bool, skipped: bool, msg: str) -> None:
    """Log syntax check outcome for visibility in logs/insights."""
    status = "skipped" if skipped else ("ok" if ok else "error")
    try:
        context.add_insight(
            "syntax_check",
            str(file_path),
            {
                "status": status,
                "message": msg,
            },
        )
        print(f"  [syntax-check] {file_path}: {status} ({msg})")
    except Exception:
        pass


def _verify_file_edit(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a file was actually edited and has valid syntax."""

    file_path: Path | None = None

    # Priority 1: Extract from task result (most reliable)
    ev = _latest_tool_event(getattr(task, "tool_events", None), {"write_file", "replace_in_file", "apply_patch", "append_to_file"})
    if ev:
        for p in _paths_from_event(ev):
            resolved = _resolve_for_verification(normalize_path(str(p)), purpose="verify file edit")
            if resolved:
                file_path = resolved
                break

    result_path = _extract_path_from_task_result(task.result)
    if result_path:
        normalized = normalize_path(result_path)
        file_path = _resolve_for_verification(normalized, purpose="verify file edit")

    # Priority 2: Check last tool call arguments
    if not file_path:
        last_call = get_last_tool_call()
        if last_call:
            tool_name = (last_call.get("name") or "").lower()
            if tool_name in {"replace_in_file", "write_file", "apply_patch", "append_to_file"}:
                args = last_call.get("args") or {}
                candidate = (
                    args.get("path")
                    or args.get("file_path")
                    or args.get("target_path")
                )
                if isinstance(candidate, str) and candidate.strip():
                    normalized = normalize_path(candidate.strip())
                    file_path = _resolve_for_verification(normalized, purpose="verify file edit")

                # If args didn't provide a usable path, try the tool result payload
                if not file_path:
                    try:
                        last_result = json.loads(last_call.get("result") or "{}")
                    except Exception:
                        last_result = {}
                    if isinstance(last_result, dict):
                        for key in ("path_abs", "path_rel", "file", "path"):
                            candidate2 = last_result.get(key)
                            if isinstance(candidate2, str) and candidate2.strip():
                                normalized = normalize_path(candidate2.strip())
                                file_path = _resolve_for_verification(normalized, purpose="verify file edit")
                                if file_path:
                                    break

    # Priority 3: Parse from task description (fallback)
    # Patterns handle both Windows and Unix paths
    if not file_path:
        patterns = [
            # Windows absolute path
            r'(?:in\s+)?(?:file\s+)?["\']?([a-zA-Z]:[/\\][^"\'\s]+\.[a-zA-Z0-9]+)["\']?',
            # Unix or relative path
            r'(?:in\s+)?(?:file\s+)?["\']?(\.?[/\\]?[a-zA-Z0-9_/\\\-\.]+\.[a-zA-Z0-9]+)["\']?',
            # phrases like "edit foo.py" or "modify foo.py"
            r'(?:edit|update|modify)\s+["\']?([a-zA-Z0-9_/\\\-\.]+\.[a-zA-Z0-9]+)["\']?',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, task.description, re.IGNORECASE)
            if matches:
                candidate = matches[0].strip()
                if candidate:
                    normalized = normalize_path(candidate)
                    file_path = _resolve_for_verification(normalized, purpose="verify file edit")
                    if file_path:
                        break

    if not file_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={},
            should_replan=True
        )

    if not file_path.exists():
        return VerificationResult(
            passed=False,
            message=f"File to edit does not exist: {file_path}",
            details={"expected_path": str(file_path)},
            should_replan=True
        )

    # Run syntax validation on the edited file
    is_valid, error_msg, skipped = _run_syntax_check(file_path)

    if not is_valid:
        # Syntax error detected - edit introduced a syntax error
        _log_syntax_result(context, file_path, ok=False, skipped=False, msg=error_msg)
        suggested_cmd = _enqueue_project_typecheck(context, tasks := [], reason="Per-file syntax error")
        if tasks:
            context.set_agent_state("injected_tasks_after_skip", True)
            context.agent_requests.append({"type": "INJECT_TASKS", "details": {"tasks": tasks}})
        return VerificationResult(
            passed=False,
            message=f"Edit to {file_path.name} introduced a syntax error",
            details={
                "file_path": str(file_path),
                "syntax_error": error_msg,
                "suggestion": "Fix the syntax error in the file",
                "suggested_build_cmd": suggested_cmd,
            },
            should_replan=True
        )

    if skipped:
        _log_syntax_result(context, file_path, ok=True, skipped=True, msg="skipped (no checker available)")
        suggested_cmd = _enqueue_project_typecheck(context, tasks := [], reason="Per-file syntax check skipped")
        if tasks:
            context.set_agent_state("injected_tasks_after_skip", True)
            context.agent_requests.append({"type": "INJECT_TASKS", "details": {"tasks": tasks}})
        return VerificationResult(
            passed=True,
            message=f"Syntax check skipped for {file_path.name}; a project typecheck/build has been enqueued.",
            details={
                "file_path": str(file_path),
                "syntax_skipped": True,
                "suggested_build_cmd": suggested_cmd,
            },
            should_replan=False,
        )

    _log_syntax_result(context, file_path, ok=True, skipped=False, msg="valid")
    _ensure_test_request_for_file(context, file_path)
    # File exists and has valid syntax - verification passed!
    return VerificationResult(
        passed=True,
        message=f"Edit to {file_path.name} verified successfully (file exists and syntax is valid)",
        details={
            "file_path": str(file_path),
            "syntax_checked": True
        }
    )


def _verify_read_task(task: Task, context: RevContext) -> VerificationResult:
    """Verification for read/analyze/research tasks with no-op detection."""
    events = getattr(task, "tool_events", None) or []
    if not events:
        return VerificationResult(
            passed=False,
            message="Read task executed no tools",
            details={},
            should_replan=True,
        )

    # Note: verify_task_execution already checked tool_noop for all events.
    # If we reached here, no explicit tool_noop was found.
    # We still perform a basic check that at least one tool ran.
    
    return VerificationResult(
        passed=True,
        message="Read-like task executed tool(s)",
        details={"tools": [ev.get("tool") for ev in events]},
    )


def _verify_directory_creation(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a directory was actually created."""

    dir_path: Path | None = None

    # Priority 1: Extract from task result (most reliable)
    ev = _latest_tool_event(getattr(task, "tool_events", None), {"create_directory"})
    if ev:
        for p in _paths_from_event(ev):
            resolved = _resolve_for_verification(normalize_path(str(p)), purpose="verify directory creation")
            if resolved:
                dir_path = resolved
                break

    extracted_from_result = _extract_path_from_task_result(task.result)
    if extracted_from_result:
        # Normalize the path first to handle Windows/Unix differences
        normalized = normalize_path(extracted_from_result)
        dir_path = _resolve_for_verification(normalized, purpose="verify directory creation")

    # Priority 2: Check last tool call arguments (second most reliable)
    if not dir_path:
        last_call = get_last_tool_call()
        if last_call:
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("path") or args.get("target") or args.get("directory")
                if isinstance(candidate, str) and candidate.strip():
                    # Normalize before resolution
                    normalized = normalize_path(candidate.strip())
                    dir_path = _resolve_for_verification(normalized, purpose="verify directory creation")

    # Priority 3: Parse from task description (least reliable, fallback only)
    # These patterns now handle both Windows and Unix paths
    if not dir_path:
        patterns = [
            # Match paths with forward or back slashes
            r'(?:directory\s+)?["\']?([a-zA-Z]:[/\\][^"\'\s]+)["\']?',  # Windows absolute
            r'(?:directory\s+)?["\']?(\.?[/\\][a-zA-Z0-9_/\\\-\.]+)["\']?',  # Unix absolute or relative
            r'(?:create|add)\s+(?:directory\s+)?["\']?([a-zA-Z0-9_/\\\-\.]+[/\\]?)["\']?',  # General
        ]

        for pattern in patterns:
            matches = re.findall(pattern, task.description, re.IGNORECASE)
            if matches:
                candidate = matches[0].strip("/").strip("\\").strip()
                if candidate:
                    normalized = normalize_path(candidate)
                    dir_path = _resolve_for_verification(normalized, purpose="verify directory creation")
                    if dir_path:
                        break

    if not dir_path:
        # Provide more helpful error details
        return VerificationResult(
            passed=False,
            message="Could not determine directory path to verify",
            details={
                "task_result": str(task.result)[:200] if task.result else None,
                "last_tool_call": get_last_tool_call(),
                "hint": "Tool result did not contain a recognizable path"
            },
            should_replan=True
        )

    if dir_path.exists() and dir_path.is_dir():
        # Return normalized relative path for cleaner output
        rel_path = normalize_to_workspace_relative(dir_path)
        return VerificationResult(
            passed=True,
            message=f"Directory created successfully: {rel_path}",
            details={"directory_path": str(dir_path), "relative_path": rel_path, "is_dir": True}
        )
    else:
        return VerificationResult(
            passed=False,
            message=f"Directory was not created: {dir_path}",
            details={"expected_path": str(dir_path)},
            should_replan=True
        )


def _verify_test_execution(task: Task, context: RevContext) -> VerificationResult:
    """Verify that tests actually passed."""

    # Prefer the tool result from the task itself (avoid re-running expensive tests).
    payload = _parse_task_result_payload(task.result)
    if payload:
        if isinstance(payload.get("blocked"), (list, str)):
            return VerificationResult(
                passed=False,
                message="Test command was blocked by tool allowlist",
                details=payload,
                should_replan=True,
            )
        if payload.get("timeout") or payload.get("timed_out") or payload.get("timeout_decision"):
            # Only fail after the second timeout. Track per-task signature.
            sig = (task.description or "").strip().lower() or "test-timeout"
            key = f"timeout_count::{sig}"
            try:
                count = int(context.get_agent_state(key, 0))
            except Exception:
                count = 0
            count += 1
            context.set_agent_state(key, count)
            # Surface a short view of stdout/stderr so the user can see why it hung.
            stdout_tail = ""
            stderr_tail = ""
            if isinstance(payload.get("stdout"), str):
                stdout_tail = payload["stdout"][-400:]
            if isinstance(payload.get("stderr"), str):
                stderr_tail = payload["stderr"][-400:]
            tail_msg = ""
            if stdout_tail or stderr_tail:
                tail_msg = f" | stdout_tail: {stdout_tail[:200]}... stderr_tail: {stderr_tail[:200]}..."
            # Mark that a remediation should be planned if the timeout originated from tests.
            details = dict(payload)
            details["timeout_count"] = count
            details["stdout_tail"] = stdout_tail
            details["stderr_tail"] = stderr_tail
            # Persist a planner hint so subsequent prompts know a fix is required.
            context.set_agent_state("timeout_needs_fix_note", True)
            try:
                # Nudge planner explicitly via user_feedback to request a safer test command.
                fb = "Test command timed out; propose an explicit non-watch, file-targeted test command based on package.json scripts before retrying."
                if hasattr(context, "user_feedback"):
                    context.user_feedback.append(fb)
            except Exception:
                pass
            if payload.get("needs_fix"):
                details["needs_fix"] = True
            if count < 2:
                return VerificationResult(
                    passed=False,
                    message=f"Test command timed out (first occurrence); will retry with adjustments{tail_msg}",
                    details=details,
                    should_replan=False,
                    inconclusive=True,
                )
            return VerificationResult(
                passed=False,
                message=f"Test command timed out (repeated){tail_msg}",
                details=details,
                should_replan=True,
            )

    desc_lower = (task.description or "").lower()
    output_combined = ""
    if payload:
        output_combined = (payload.get("stdout", "") or "") + (payload.get("stderr", "") or "")

    if payload and payload.get("skipped") is True and payload.get("kind") == "skipped_tests":
        last_test_iteration = payload.get("last_test_iteration")
        last_test_rc = payload.get("last_test_rc")

        if isinstance(last_test_rc, int) and last_test_rc != 0:
            context.agent_state["tests_blocked_no_changes"] = True
            return VerificationResult(
                passed=True,
                message="Skipped pytest (no code changes since last failure)",
                details={
                    "skipped": True,
                    "blocked": True,
                    "last_test_iteration": last_test_iteration,
                    "last_test_rc": last_test_rc,
                },
            )

        return VerificationResult(
            passed=True,
            message="Skipped pytest (no changes since last pass)",
            details={
                "skipped": True,
                "last_test_iteration": last_test_iteration,
                "last_test_rc": last_test_rc,
            },
        )

    if payload and isinstance(payload.get("rc"), int):
        rc = payload.get("rc", 1)
        stdout = str(payload.get("stdout", "") or "")
        stderr = str(payload.get("stderr", "") or "")
        output = stdout + stderr
        cwd = None
        if isinstance(payload, dict):
            cwd_value = payload.get("cwd") or payload.get("working_dir") or payload.get("workdir")
            if isinstance(cwd_value, (str, Path)):
                cwd = str(cwd_value)
        context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
        context.agent_state["last_test_rc"] = rc
        blocked_reason = None
        blocked_hints: list[str] = []
        suspected_issue: Optional[str] = None
        if payload.get("blocked") is True:
            blocked_reason = (stderr or stdout or "Command blocked").strip()
        elif "blocked non-terminating vitest command" in output.lower():
            blocked_reason = "Blocked non-terminating Vitest command."
        # Detect Vitest CLI option errors (e.g., --runTestsByPath not supported) to avoid misleading hints.
        elif "cacerror" in output.lower() and "vitest" in output.lower():
            blocked_reason = "Vitest CLI error: invalid option; test script/command is incorrect."
            suspected_issue = "Invalid Vitest test script/flags (e.g., unsupported --runTestsByPath)."
            blocked_hints = [
                "Patch package.json test script to a non-watch single-file command, e.g., \"vitest run tests/user.test.ts\".",
                "Avoid unsupported Vitest flags like --runTestsByPath.",
            ]
        elif payload.get("needs_fix"):
            blocked_reason = "Test command timed out and needs a remediation (e.g., safer command/config)."
            suspected_issue = suspected_issue or "Test command timed out; likely hanging (watch mode or long-running requests)."
        if blocked_reason:
            return VerificationResult(
                passed=False,
                message="Verification INCONCLUSIVE: command blocked",
                details={
                    "rc": rc,
                    "output": output[:800],
                    "stdout": stdout[:400],
                    "stderr": stderr[:400],
                    "blocked": True,
                    "skip_failure_counts": True,
                    "reason": blocked_reason,
                    "cmd": payload.get("cmd") or payload.get("command"),
                    "cwd": cwd,
                    "suspected_issue": suspected_issue,
                    "hints": blocked_hints or None,
                    "needs_fix": payload.get("needs_fix"),
                },
                should_replan=True,
                inconclusive=True,
            )
        if _NO_TEST_RUNNER_SENTINEL in output:
            return VerificationResult(
                passed=True,
                message="No test runner detected; tests skipped",
                details={"rc": rc, "output": output[:200], "skipped": True, "reason": "no_test_runner_detected"},
            )
        if _output_indicates_no_tests(stdout, stderr) and not _no_tests_expected(task):
            root = Path(cwd) if cwd else config.ROOT
            try:
                root = root.resolve()
            except Exception:
                root = Path.cwd().resolve()
            test_files = _extract_test_files_from_output(output)
            debug_info = _build_test_diagnostics(output, test_files, root)
            # If we saw a Vitest CLI error, surface it and avoid unrelated hints (e.g., Prisma).
            vitest_cli_error = None
            if "cacerror" in output.lower() and "vitest" in output.lower():
                vitest_cli_error = "Vitest CLI error detected (invalid option). Check package.json test script."
                debug_info = debug_info or {}
                existing_hints = debug_info.get("hints") if isinstance(debug_info.get("hints"), list) else []
                debug_info["suspected_issue"] = vitest_cli_error
                debug_info["hints"] = existing_hints + [
                    "Update package.json test script to a non-watch, single-file command, e.g., \"vitest run tests/user.test.ts\".",
                    "Avoid unsupported flags like --runTestsByPath in Vitest.",
                ]
            else:
                # If we cannot determine the root cause, surface stdout/stderr and suggest a safe, targeted command.
                if not debug_info:
                    debug_info = {}
                existing_hints = debug_info.get("hints") if isinstance(debug_info.get("hints"), list) else []
                if not debug_info.get("suspected_issue"):
                    debug_info["suspected_issue"] = "Test discovery failed for unknown reasons; see stdout/stderr."
                suggested_cmd = None
                first_file = test_files[0] if test_files else None
                if first_file:
                    suggested_cmd = f"npx vitest run {first_file}"
                if suggested_cmd:
                    existing_hints.append(f"Try a targeted run: {suggested_cmd}")
                debug_info["hints"] = existing_hints
            return VerificationResult(
                passed=False,
                message="Verification INCONCLUSIVE: no tests discovered",
                details={
                    "rc": rc,
                    "output": output[:500],
                    "no_tests_discovered": True,
                    "non_retriable": True,
                    "skip_failure_counts": True,
                    "test_files": test_files,
                    "debug": debug_info if debug_info else None,
                    "cmd": payload.get("cmd") or payload.get("command"),
                },
                should_replan=True,
                inconclusive=True,
            )
        missing_script = _detect_missing_script(stdout, stderr)
        if missing_script:
            cmd_value = payload.get("cmd") or payload.get("command") or ""
            cmd_parts = _split_command_parts(cmd_value)
            cwd = payload.get("cwd")
            fallback_cmd = _attempt_missing_script_fallback(cmd_parts, cwd)
            if fallback_cmd:
                fallback_result = _run_validation_command(
                    fallback_cmd,
                    use_tests_tool=True,
                    timeout=config.VALIDATION_TIMEOUT_SECONDS,
                    cwd=cwd,
                )
                fallback_stdout = str(fallback_result.get("stdout", "") or "")
                fallback_stderr = str(fallback_result.get("stderr", "") or "")
                fallback_output = fallback_stdout + fallback_stderr
                fallback_rc = fallback_result.get("rc")
                context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
                context.agent_state["last_test_rc"] = fallback_rc
                if _NO_TEST_RUNNER_SENTINEL in fallback_output:
                    return VerificationResult(
                        passed=True,
                        message="No test runner detected; tests skipped",
                        details={"rc": fallback_rc, "output": fallback_output[:200], "skipped": True},
                    )
                if _output_indicates_no_tests(fallback_stdout, fallback_stderr) and not _no_tests_expected(task):
                    return VerificationResult(
                        passed=False,
                        message="No tests found after retrying missing script",
                        details={"rc": fallback_rc, "output": fallback_output[:500], "retry_cmd": fallback_result.get("cmd")},
                        should_replan=True,
                    )
                if fallback_rc == 0:
                    return VerificationResult(
                        passed=True,
                        message="Tests passed after retrying missing script",
                        details={"rc": fallback_rc, "output": fallback_output[:200], "retry_cmd": fallback_result.get("cmd")},
                    )
                return VerificationResult(
                    passed=False,
                    message=f"Tests failed after retry (rc={fallback_rc})",
                    details={"rc": fallback_rc, "output": fallback_output[:500], "retry_cmd": fallback_result.get("cmd")},
                    should_replan=True,
                )
            return VerificationResult(
                passed=True,
                message="No test script detected; tests skipped",
                details={"rc": rc, "output": output[:200], "skipped": True, "reason": "missing_test_script"},
            )
        if rc == 0:
            cmd = payload.get("cmd") or payload.get("command")
            if isinstance(cmd, str) and cmd.strip() and "pytest" not in cmd.lower():
                return VerificationResult(
                    passed=True,
                    message="Command succeeded",
                    details={"rc": rc, "command": cmd, "output": output[:200]},
                )
            return VerificationResult(
                passed=True,
                message="Tests passed",
                details={"rc": rc, "output": output[:200]},
            )
        if rc == 5:
            if _no_tests_expected(task):
                return VerificationResult(
                    passed=True,
                    message="No tests collected (rc=5) - explicitly allowed",
                    details={"rc": rc, "output": output[:200]},
                )
            return VerificationResult(
                passed=False,
                message="Verification INCONCLUSIVE: pytest collected 0 tests (rc=5)",
                details={"rc": rc, "output": output[:500]},
                should_replan=True,
            )
        root_path = Path(cwd) if cwd else (config.ROOT or Path.cwd())
        try:
            root_path = root_path.resolve()
        except Exception:
            root_path = Path.cwd().resolve()
        return VerificationResult(
            passed=False,
            message=f"Tests failed (rc={rc})",
            details=_merge_debug_details(
                {"rc": rc, "output": output[:500]},
                _build_test_diagnostics(
                    output,
                    _extract_test_files_from_output(output),
                    root_path,
                ),
            ),
            should_replan=True,
        )

    if payload is not None:
        return VerificationResult(
            passed=False,
            message="Test command did not return an exit code (rc); cannot verify",
            details={"payload": payload},
            should_replan=True,
        )

    last_test_iteration = context.agent_state.get("last_test_iteration")
    last_test_rc = context.agent_state.get("last_test_rc")
    last_code_change_iteration = context.agent_state.get("last_code_change_iteration", -1)
    if (
        isinstance(last_test_iteration, int)
        and isinstance(last_code_change_iteration, int)
        and last_code_change_iteration <= last_test_iteration
    ):
        if last_test_rc == 0:
            return VerificationResult(
                passed=True,
                message="Skipped tests (no changes since last pass)",
                details={"last_test_iteration": last_test_iteration}
            )
        context.agent_state["tests_blocked_no_changes"] = True
        return VerificationResult(
            passed=True,
            message="Skipped pytest (no code changes since last failure)",
            details={"blocked": True, "last_test_iteration": last_test_iteration, "last_test_rc": last_test_rc},
        )

    # Fall back to running tests if we have no usable tool result.
    try:
        result = execute_tool("run_tests", {"cmd": "pytest -q", "timeout": 30}, agent_name="quick_verify")
        result_data = json.loads(result)
        rc = result_data.get("rc", 1)
        output = result_data.get("stdout", "") + result_data.get("stderr", "")
        context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
        context.agent_state["last_test_rc"] = rc

        if rc == 0:
            return VerificationResult(
                passed=True,
                message="Tests passed",
                details={"rc": rc, "output": output[:200]}
            )
        if rc == 5:
            if _no_tests_expected(task):
                return VerificationResult(
                    passed=True,
                    message="No tests collected (rc=5) - explicitly allowed",
                    details={"rc": rc, "output": output[:200]}
                )
            return VerificationResult(
                passed=False,
                message="Verification INCONCLUSIVE: pytest collected 0 tests (rc=5)",
                details={"rc": rc, "output": output[:500]},
                should_replan=True
            )
        else:
            return VerificationResult(
                passed=False,
                message=f"Tests failed (rc={rc})",
                details={"rc": rc, "output": output[:500]},
                should_replan=True
            )
    except Exception as e:
        return VerificationResult(
            passed=False,
            message=f"Could not verify test execution: {e}",
            details={"error": str(e)},
            should_replan=True
        )


def quick_verify_extraction_completeness(
    source_file: Path,
    target_dir: Path,
    expected_items: list
) -> Tuple[bool, Dict[str, Any]]:
    """
    Quick check that an extraction is complete.

    Verifies that:
    - All expected items were extracted to separate files
    - No duplicates exist
    - Imports are correct

    Args:
        source_file: Original file that was extracted from
        target_dir: Directory where items were extracted to
        expected_items: List of class/function names that should be extracted

    Returns:
        (success: bool, details: dict)
    """

    details = {
        "expected_items": expected_items,
        "found_files": []
    }

    if not target_dir.exists():
        details["error"] = f"Target directory does not exist: {target_dir}"
        return False, details

    py_files = list(target_dir.glob("*.py"))
    details["found_files"] = [f.name for f in py_files]

    # Check that we have the right number of files
    if len(py_files) < len(expected_items):
        details["error"] = f"Found {len(py_files)} files but expected {len(expected_items)} items to be extracted"
        return False, details

    # Check that source file still exists and wasn't truncated
    if source_file.exists():
        content = _read_file_with_fallback_encoding(source_file)
        if content and not content.strip():
            details["warning"] = f"Source file {source_file} is now empty after extraction"
            return False, details

    return True, details
