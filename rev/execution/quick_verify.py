"""
Quick verification module for sub-agent execution.

Provides lightweight, task-specific verification that can be run after each
task completes to ensure it actually did what was requested. This is critical
for the workflow loop: Plan → Execute → Verify → Report → Re-plan if needed
"""

import json
import re
import os
import shlex
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Iterable
from dataclasses import dataclass

from rev.models.task import Task, TaskStatus
from rev.tools.registry import execute_tool, get_last_tool_call
from rev import config
from rev.core.context import RevContext
from rev.tools.workspace_resolver import (
    WorkspacePathError,
    resolve_workspace_path,
    normalize_path,
    normalize_to_workspace_relative,
)

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


def _extract_tool_noop(tool: str, raw_result: Any) -> Optional[str]:
    """Return a tool_noop reason string when a tool reports no changes."""
    tool_l = (tool or "").lower()
    if tool_l != "replace_in_file":
        return None
    if not isinstance(raw_result, str) or not raw_result.strip():
        return None
    try:
        payload = json.loads(raw_result)
    except Exception:
        return None
    if isinstance(payload, dict) and payload.get("replaced") == 0:
        return "tool_noop: replace_in_file made no changes (replaced=0)"
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
    """Result of verifying a task's execution."""
    passed: bool
    message: str
    details: Dict[str, Any]
    should_replan: bool = False

    def __str__(self) -> str:
        status = '[OK]' if self.passed else '[FAIL]'
        # Remove any Unicode characters that might cause encoding issues on Windows
        safe_message = self.message.replace('[OK]', '[OK]').replace('[FAIL]', '[FAIL]').replace('[FAIL]', '[FAIL]')
        return f"{status} {safe_message}"


def verify_task_execution(task: Task, context: RevContext) -> VerificationResult:
    """
    Verify that a task actually completed successfully.

    This checks that:
    1. The task's action was actually performed
    2. Any files mentioned were actually created/modified
    3. Imports are valid if this was a refactoring task
    4. Tests still pass (if applicable)

    Args:
        task: The task that was supposedly completed
        context: The execution context

    Returns:
        VerificationResult indicating if the task truly succeeded
    """

    if task.status != TaskStatus.COMPLETED:
        return VerificationResult(
            passed=False,
            message=f"Task status is {task.status.name}, not COMPLETED",
            details={"status": task.status.name},
            should_replan=False
        )

    action_type = task.action_type.lower()
    verification_mode = _get_verification_mode()

    # Surface tool no-ops clearly (e.g., replace_in_file with replaced=0).
    if action_type in {"add", "create", "edit", "refactor", "delete", "rename"}:
        events = getattr(task, "tool_events", None) or []
        for ev in reversed(list(events)):
            reason = _extract_tool_noop(str(ev.get("tool") or ""), ev.get("raw_result"))
            if reason:
                return VerificationResult(
                    passed=False,
                    message=reason,
                    details={"tool": ev.get("tool"), "artifact_ref": ev.get("artifact_ref")},
                    should_replan=True,
                )

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

    # Enforce validation_steps when provided; otherwise fall back to strict verification
    # mode (default: fast compileall).
    if result.passed and action_type in {"add", "create", "edit", "refactor"}:
        if task.validation_steps:
            validation_outcome = _run_validation_steps(
                task.validation_steps, result.details, getattr(task, "tool_events", None)
            )
            if isinstance(validation_outcome, VerificationResult):
                return validation_outcome
            if validation_outcome:
                result.details["validation"] = validation_outcome
        elif verification_mode:
            strict_paths = _collect_paths_for_strict_checks(
                action_type, result.details, getattr(task, "tool_events", None)
            )
            strict_outcome = _maybe_run_strict_verification(action_type, strict_paths, mode=verification_mode)
            if isinstance(strict_outcome, VerificationResult):
                return strict_outcome
            if strict_outcome:
                result.details["strict"] = strict_outcome

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
        issues.append(f"[FAIL] Target directory '{target_dir}' does not exist - extraction was never started")
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

    # Check 4: Verify old file was updated with imports (if applicable)
    # Look for the original file mentioned in task description
    old_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-]+\.py)'
    old_file_matches = re.findall(old_file_pattern, task.description)
    if old_file_matches:
        old_file = _resolve_for_verification(old_file_matches[0], purpose="verify refactoring source file")
        if not old_file and target_dir:
            # Heuristic: source next to target_dir, e.g., module.py when target_dir=module/
            alt_source = (target_dir.parent / f"{target_dir.name}.py").resolve()
            if alt_source.exists():
                old_file = alt_source
        if not old_file:
            issues.append(f"[FAIL] Could not resolve source file path for verification: {old_file_matches[0]}")
            debug_info["main_file_status"] = "UNRESOLVABLE"
            old_file = None
        debug_info["source_file"] = str(old_file)
        debug_info["source_file_exists"] = old_file.exists() if old_file else False
        if old_file:
            details["source_file_path"] = str(old_file)

        if old_file and old_file.exists():
            try:
                # Use helper function for robust multi-encoding file reading
                content = _read_file_with_fallback_encoding(old_file)

                if content is None:
                    debug_info["main_file_status"] = "NOT_READABLE"
                else:
                    original_size = len(content)
                    debug_info["source_file_size"] = original_size

                    # Check if it has import statements from the new directory
                    has_imports_from_new = re.search(rf'from\s+\.{target_dir.name}', content)
                    if has_imports_from_new:
                        details["main_file_updated"] = True
                        debug_info["main_file_status"] = "UPDATED_WITH_IMPORTS"
                    else:
                        issues.append(
                            f"[FAIL] Original file {old_file} was NOT updated with imports from {target_dir}\n"
                            f"   File still contains {original_size} bytes (should be much smaller if extracted)"
                        )
                        debug_info["main_file_status"] = "NOT_UPDATED"
            except Exception as e:
                issues.append(f"[FAIL] Could not read {old_file}: {e}")
                debug_info["main_file_status"] = f"ERROR: {str(e)}"
        else:
            if old_file:
                package_candidate = old_file.with_suffix("")
                package_init = package_candidate / "__init__.py"
                if package_candidate.exists() and package_init.exists():
                    details["main_file_converted_to_package"] = True
                    debug_info["main_file_status"] = "CONVERTED_TO_PACKAGE"
                    debug_info["package_path"] = str(package_candidate)
                else:
                    # If target_dir exists with files, downgrade to warning
                    if target_dir and target_dir.exists():
                        warn = (
                            f"Original file {old_file} missing but extraction target {target_dir} exists; "
                            "treating as converted package"
                        )
                        details["main_file_converted_to_package"] = True
                        debug_info["main_file_status"] = "MISSING_BUT_TARGET_EXISTS"
                        debug_info["warnings"] = debug_info.get("warnings", []) + [warn]
                    else:
                        issues.append(
                            f"[FAIL] Original file {old_file} no longer exists and package '{package_candidate}' was not found"
                        )
                        debug_info["main_file_status"] = "MISSING"

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
    if file_path.exists():
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

        return VerificationResult(
            passed=True,
            message=f"File created successfully: {file_path.name}",
            details=details
        )
    else:
        return VerificationResult(
            passed=False,
            message=f"File was not created: {file_path}",
            details={"expected_path": str(file_path)},
            should_replan=True
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
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


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


def _run_validation_command(cmd: str, *, use_tests_tool: bool = False, timeout: int | None = None) -> Dict[str, Any]:
    """Run a validation command via the tool runner and return parsed JSON."""
    payload = {"cmd": cmd}
    if timeout:
        payload["timeout"] = timeout

    tool = "run_tests" if use_tests_tool else "run_cmd"
    try:
        raw = execute_tool(tool, payload)
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"raw": raw}
    except Exception as e:
        return {"error": str(e), "cmd": cmd}


def _quote_path(path: Path) -> str:
    """Quote a path for shell commands."""
    return shlex.quote(str(path))


def _paths_or_default(paths: list[Path]) -> list[Path]:
    """Return provided paths or default to workspace root."""
    if paths:
        return paths
    try:
        return [config.ROOT]
    except Exception:
        return [Path(".").resolve()]


def _maybe_run_strict_verification(action_type: str, paths: list[Path], *, mode: str) -> Optional[VerificationResult | Dict[str, Any]]:
    """Run compileall/tests depending on verification mode (fast/strict)."""
    if not paths:
        return None

    strict_details: Dict[str, Any] = {}
    compile_targets = _paths_or_default(paths)
    compile_cmd = "python -m compileall " + " ".join(_quote_path(p) for p in compile_targets)
    compile_res = _run_validation_command(compile_cmd, timeout=max(config.VALIDATION_TIMEOUT_SECONDS, 180))
    strict_details["compileall"] = compile_res
    if compile_res.get("blocked") or compile_res.get("rc", 1) != 0:
        return VerificationResult(
            passed=False,
            message="Verification failed: compileall errors",
            details={"strict": strict_details},
            should_replan=True,
        )

    if mode == "fast":
        return strict_details

    # Targeted pytest for touched test files/directories
    test_targets = []
    for p in paths:
        parts_lower = {part.lower() for part in p.parts}
        if "tests" in parts_lower or p.name.startswith("test_") or p.name.endswith("_test.py"):
            test_targets.append(p)
    if test_targets:
        pytest_cmd = "pytest -q " + " ".join(_quote_path(p) for p in test_targets)
    else:
        pytest_cmd = "pytest -q"
    pytest_res = _run_validation_command(pytest_cmd, use_tests_tool=True, timeout=config.VALIDATION_TIMEOUT_SECONDS)
    strict_details["pytest"] = pytest_res
    rc = pytest_res.get("rc", 1)
    if pytest_res.get("blocked") or rc != 0:
        return VerificationResult(
            passed=False,
            message="Verification failed: pytest errors",
            details={"strict": strict_details},
            should_replan=True,
        )

    # Optional lint/type checks if allowed
    optional_checks = []
    if "ruff" in config.ALLOW_CMDS:
        optional_checks.append(("ruff", "ruff check ."))
    if "mypy" in config.ALLOW_CMDS:
        optional_checks.append(("mypy", "mypy ."))
    for label, cmd in optional_checks:
        res = _run_validation_command(cmd, timeout=config.VALIDATION_TIMEOUT_SECONDS)
        strict_details[label] = res
        rc = res.get("rc")
        if rc is None:
            rc = 0 if res.get("blocked") else 1
        # Optional: do not fail on blocked, but fail on non-zero rc when executed
        if not res.get("blocked") and rc not in (0, None):
            return VerificationResult(
                passed=False,
                message=f"Verification failed: {label} errors",
                details={"strict": strict_details},
                should_replan=True,
            )

    return strict_details


def _run_validation_steps(validation_steps: list[str], details: Dict[str, Any], tool_events: Optional[Iterable[Dict[str, Any]]]) -> Optional[VerificationResult | Dict[str, Any]]:
    """Execute declarative validation steps (lint/tests/compile) via tool runner."""
    commands: list[tuple[str, str, str]] = []
    seen_cmds = set()
    paths = _paths_or_default(_collect_paths_for_strict_checks("", details, tool_events))

    def _add(label: str, cmd: str, tool: str = "run_cmd") -> None:
        if cmd in seen_cmds:
            return
        seen_cmds.add(cmd)
        commands.append((label, cmd, tool))

    for step in validation_steps:
        text = step.lower()
        if "syntax" in text or "compile" in text:
            cmd = "python -m compileall " + " ".join(_quote_path(p) for p in paths)
            _add("compileall", cmd)
        if "lint" in text or "linter" in text:
            _add("ruff", "ruff check .")
        if "test" in text:
            _add("pytest", "pytest -q", "run_tests")
        if "mypy" in text or "type" in text:
            _add("mypy", "mypy .")

    if not commands:
        return None

    results: Dict[str, Any] = {}
    for label, cmd, tool in commands:
        res = _run_validation_command(cmd, use_tests_tool=(tool == "run_tests"), timeout=config.VALIDATION_TIMEOUT_SECONDS)
        results[label] = res
        rc = res.get("rc")
        if rc is None:
            rc = 0 if res.get("blocked") else 1
        if res.get("blocked") or (rc is not None and rc != 0):
            return VerificationResult(
                passed=False,
                message=f"Validation step failed: {label}",
                details={"validation": results, "failed_step": label},
                should_replan=True,
            )

    return results


def _verify_file_edit(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a file was actually edited."""

    # This is harder to verify without knowing the original content
    # For now, just check that the file exists and isn't empty

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

    # File exists, assume edit was successful
    # (Without knowing original content, we can't fully verify the edit)
    return VerificationResult(
        passed=True,
        message=f"File exists and can be edited: {file_path.name}",
        details={"file_path": str(file_path), "note": "Full edit verification requires content comparison"}
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
        if payload.get("timeout"):
            return VerificationResult(
                passed=False,
                message="Test command timed out",
                details=payload,
                should_replan=True,
            )

    # If the task is about auto-registration, surface the observed count from stdout/stderr even if rc != 0.
    def _extract_auto_registered_count(out: str) -> Optional[int]:
        if not out:
            return None
        match = re.search(r"Auto-registered\s+(\d+)", out, re.IGNORECASE)
        return int(match.group(1)) if match else None

    desc_lower = (task.description or "").lower()
    output_combined = ""
    if payload:
        output_combined = (payload.get("stdout", "") or "") + (payload.get("stderr", "") or "")
    if "auto-registered" in desc_lower and output_combined:
        count = _extract_auto_registered_count(output_combined)
        if count is not None and count <= 0:
            return VerificationResult(
                passed=False,
                message=f"Auto-registration still empty (Auto-registered {count})",
                details={"count": count, "output": output_combined[:500]},
                should_replan=True,
            )
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
        output = (payload.get("stdout", "") or "") + (payload.get("stderr", "") or "")
        context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
        context.agent_state["last_test_rc"] = rc
        if rc == 0:
            cmd = payload.get("cmd") or payload.get("command")
            if isinstance(cmd, str) and cmd.strip() and "pytest" not in cmd.lower():
                if "auto-registered" in (task.description or "").lower():
                    match = re.search(r"Auto-registered\s+(\d+)", output, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        if count <= 0:
                            return VerificationResult(
                                passed=False,
                                message=f"Auto-registration still empty (Auto-registered {count})",
                                details={"count": count, "command": cmd, "output": output[:500]},
                                should_replan=True,
                            )
                    else:
                        return VerificationResult(
                            passed=False,
                            message="Could not find Auto-registered count in startup output",
                            details={"command": cmd, "output": output[:500]},
                            should_replan=True,
                        )
                return VerificationResult(
                    passed=True,
                    message="Command succeeded",
                    details={"rc": rc, "command": cmd, "output": output[:200]},
                )
            return VerificationResult(
                passed=True,
                message="Tests passed",
                details={"rc": rc, "output": output[:200]}
            )
        return VerificationResult(
            passed=False,
            message=f"Tests failed (rc={rc})",
            details={"rc": rc, "output": output[:500]},
            should_replan=True
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
        result = execute_tool("run_tests", {"cmd": "pytest -q", "timeout": 30})
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
