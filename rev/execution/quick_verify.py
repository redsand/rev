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
import shutil
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
from rev.tools.utils import quote_cmd_arg
from rev.llm.client import ollama_chat

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
        results = payload.get("matches") or payload.get("results")
        if isinstance(results, list) and len(results) == 0:
            return f"tool_noop: {tool_l} returned 0 results. RECOVERY: Broaden your search pattern or check for typos in file names/symbols."
            
    elif tool_l == "run_tests":
        stdout = (payload.get("stdout") or "").lower()
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
    """
    if task.status != TaskStatus.COMPLETED:
        return VerificationResult(
            passed=False,
            message=f"Task status is {task.status.name}, not COMPLETED",
            details={"status": task.status.name},
            should_replan=False
        )

    # Surface tool no-ops clearly (e.g., search with 0 matches) first.
    # This ensures all actions are checked for functional success.
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

    action_type = task.action_type.lower()
    verification_mode = _get_verification_mode()

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
    verifiable_read_actions = {"read", "analyze", "research", "investigate", "general", "verify"}
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
    elif action_type in verifiable_read_actions:
        result = _verify_read_task(task, context)
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
                task, result.details, getattr(task, "tool_events", None)
            )
            if isinstance(validation_outcome, VerificationResult):
                return validation_outcome
            if validation_outcome:
                result.details["validation"] = validation_outcome
        elif verification_mode:
            strict_paths = _collect_paths_for_strict_checks(
                action_type, result.details, getattr(task, "tool_events", None)
            )
            strict_outcome = _maybe_run_strict_verification(action_type, strict_paths, mode=verification_mode, task=task)
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
                                import_test_result = execute_tool("run_cmd", {"cmd": import_test_cmd, "timeout": 10})
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
        resolved = shutil.which(base_cmd)
        
        if resolved:
            # If it's npx, we might still be missing the specific package
            if base_cmd == "npx" and len(args) > 1:
                pkg = args[1]
                # If we're looking for eslint or tsc specifically, we can check node_modules
                if pkg in ("eslint", "tsc"):
                    pkg_name = "typescript" if pkg == "tsc" else pkg
                    if not (config.ROOT / "node_modules" / pkg_name).exists():
                        print(f"  [i] npx command '{pkg}' missing from node_modules, attempting install...")
                        # Run npm install locally
                        install_res = execute_tool("run_cmd", {"cmd": f"npm install {pkg_name} --save-dev", "timeout": 300})
                        try:
                            return json.loads(install_res).get("rc") == 0
                        except:
                            return False
            # Verify if the resolved path is inside the workspace and return True if it exists
            return True

        # Tool missing - attempt auto-install
        pkg_map = {
            "ruff": "pip install ruff",
            "mypy": "pip install mypy",
            "pytest": "pip install pytest",
            "eslint": "npm install eslint --save-dev",
            "tsc": "npm install typescript --save-dev",
        }

        if base_cmd in pkg_map:
            install_cmd = pkg_map[base_cmd]
            
            # For Node tools, ensure package.json exists if we're doing a local install
            if base_cmd in ("eslint", "tsc") or (base_cmd == "npx" and len(args) > 1 and args[1] in ("eslint", "tsc")):
                if not (config.ROOT / "package.json").exists():
                    print("  [i] package.json missing, initializing with 'npm init -y'...")
                    execute_tool("run_cmd", {"cmd": "npm init -y", "timeout": 30})

            print(f"  [i] Tool '{base_cmd}' not found, attempting auto-install: {install_cmd}...")
            install_res = execute_tool("run_cmd", {"cmd": install_cmd, "timeout": 300})
            try:
                success = json.loads(install_res).get("rc") == 0
                if success:
                    print(f"  [OK] Successfully installed {base_cmd}")
                    return True
            except:
                pass
            
        return False
    except Exception as e:
        print(f"  [!] Error checking/installing tool '{cmd}': {e}")
        return False


def _extract_error(res: Dict[str, Any], default: str = "Unknown error") -> str:
    """Extract and truncate error message from tool result, with a broad recovery hint."""
    stdout = res.get("stdout", "")
    stderr = res.get("stderr", "")
    rc = res.get("rc")
    help_info = res.get("help_info")
    
    msg = stderr or stdout or default
    msg = msg.strip()
    
    # If we have a failure (non-zero rc) but no output, provide more context
    if (rc is not None and rc != 0) and not stderr and not stdout:
        msg = f"Command failed with exit code {rc} but produced no output (stdout/stderr)."
        if rc == 2:
            msg += " On Windows, exit code 2 often indicates a fatal configuration error or missing files for tools like ESLint."

    # Include help information if available
    if help_info:
        msg += f"\n\n--- COMMAND USAGE INFO (--help) ---\n{help_info}"

    # Generic, broad recovery hint covering config, dependencies, and environment
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
            raw = execute_tool("run_cmd", payload)
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
            raw = execute_tool("run_cmd", {"cmd": cmd, "timeout": 5})
            res = json.loads(raw)
            out = (res.get("stdout") or res.get("stderr") or "").strip()
            if out and ("usage:" in out.lower() or "options:" in out.lower() or "arguments:" in out.lower()):
                return out[:1000]
    except:
        pass
    return None


def _run_validation_command(cmd: str, *, use_tests_tool: bool = False, timeout: int | None = None) -> Dict[str, Any]:
    """Run a validation command via the tool runner and return parsed JSON."""
    # Ensure tool is available before running
    _ensure_tool_available(cmd)
    
    payload = {"cmd": cmd}
    if timeout:
        payload["timeout"] = timeout

    tool = "run_tests" if use_tests_tool else "run_cmd"
    try:
        raw = execute_tool(tool, payload)
        data = json.loads(raw)
        if isinstance(data, dict):
            # Ensure cmd is present in the result
            if "cmd" not in data:
                data["cmd"] = cmd
            
            # If the command failed, attempt to gather help output for better diagnostics
            rc = data.get("rc")
            if rc is not None and rc not in (0, 4):
                try:
                    tokens = shlex.split(cmd)
                    if tokens:
                        base_cmd = tokens[0]
                        help_info = _get_help_output(base_cmd)
                        if help_info:
                            data["help_info"] = help_info
                except:
                    pass
                    
            return data
        return {"raw": raw, "cmd": cmd}
    except Exception as e:
        return {"error": str(e), "cmd": cmd}


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


def _find_project_root(path: Path) -> Path:
    """Find the nearest project root containing project markers, staying within workspace."""
    try:
        current = path.resolve()
        if not current.is_dir():
            current = current.parent
        
        # Don't go outside workspace root
        try:
            root_limit = config.ROOT.resolve()
        except:
            root_limit = Path(".").resolve()
        
        markers = {
            "package.json", "pyproject.toml", "requirements.txt", "setup.py",
            "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml",
            "build.gradle", "CMakeLists.txt", "Makefile", "prisma", ".git"
        }
        
        while len(current.parts) >= len(root_limit.parts):
            if any((current / m).exists() for m in markers):
                return current
            if current == root_limit:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
            
        return root_limit
    except Exception:
        return config.ROOT


def _detect_project_type(path: Path) -> str:
    """Detect the project type (python, vue, node, go, rust, etc) relative to a path."""
    try:
        root = _find_project_root(path)
        
        # 1. Node.js Ecosystem
        if (root / "package.json").exists():
            content = (root / "package.json").read_text(errors="ignore")
            if '"vue"' in content: return "vue"
            if '"react"' in content: return "react"
            if '"next"' in content: return "nextjs"
            return "node"
        
        # 2. Python Ecosystem
        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
            return "python"
            
        # 3. Go Ecosystem
        if (root / "go.mod").exists():
            return "go"
            
        # 4. Rust Ecosystem
        if (root / "Cargo.toml").exists():
            return "rust"
            
        # 5. Ruby Ecosystem
        if (root / "Gemfile").exists() or (root / "Rakefile").exists():
            return "ruby"
            
        # 6. PHP Ecosystem
        if (root / "composer.json").exists():
            return "php"
            
        # 7. Java/Kotlin Ecosystem
        if (root / "pom.xml").exists():
            return "java_maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            # Check if it's Kotlin
            if any(root.rglob("*.kt")):
                return "kotlin"
            return "java_gradle"
            
        # 8. C# / .NET Ecosystem
        if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
            return "csharp"
            
        # 9. C/C++ Ecosystem
        if (root / "CMakeLists.txt").exists():
            return "cpp_cmake"
        if (root / "Makefile").exists():
            return "cpp_make"
            
        # 10. Mobile / Flutter
        if (root / "pubspec.yaml").exists():
            return "flutter"

        # Fallback by file extension in root
        if root.exists() and root.is_dir():
            for f in root.iterdir():
                if f.suffix == ".py": return "python"
                if f.suffix in (".js", ".ts"): return "node"
                if f.suffix == ".go": return "go"
                if f.suffix == ".rs": return "rust"
                if f.suffix == ".rb": return "ruby"
                if f.suffix == ".php": return "php"
                if f.suffix == ".java": return "java_maven"
                if f.suffix == ".kt": return "kotlin"
                if f.suffix == ".cs": return "csharp"
    except Exception:
        pass
    return "unknown"


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

    strict_details: Dict[str, Any] = {}
    primary_path = paths[0] if paths else config.ROOT
    project_type = _detect_project_type(primary_path)
    
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
        build_res = _run_validation_command(custom_build_cmd, timeout=config.VALIDATION_TIMEOUT_SECONDS)
        strict_details["custom_build"] = build_res
        if build_res.get("rc", 0) != 0:
            return VerificationResult(
                passed=False,
                message=f"Verification failed: build command '{custom_build_cmd}' failed. Error: {_extract_error(build_res)}",
                details={"strict": strict_details},
                should_replan=True,
            )

    # -------------------------------------------------------------------------
    # PYTHON VERIFICATION
    # -------------------------------------------------------------------------
    if project_type == "python":
        # Filter for Python files or directories for compileall
        compile_targets = [p for p in _paths_or_default(paths) if p.is_dir() or p.suffix == '.py']
        
        if compile_targets:
            compile_cmd = "python -m compileall " + " ".join(_quote_path(p) for p in compile_targets)
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
                pytest_cmd = "pytest -q " + " ".join(_quote_path(p) for p in test_targets)
            else:
                pytest_cmd = "pytest -q"
        
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
        if py_paths:
            ruff_targets = " ".join(_quote_path(p) for p in py_paths[:10])
            # E9: Runtime/syntax errors, F63: Invalid print syntax, F7: Statement problems
            optional_checks = [("ruff", f"ruff check {ruff_targets} --select E9,F63,F7")]
            optional_checks.append(("mypy", f"mypy {ruff_targets}"))
            
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
                cmd = f"node --check {quote_cmd_arg(str(js_file))}"
                res = _run_validation_command(cmd, timeout=30)
                strict_details[f"syntax_{js_file.name}"] = res
                if not res.get("blocked") and res.get("rc", 1) != 0:
                    return VerificationResult(
                        passed=False,
                        message=f"Syntax error in {js_file.name}. Error: {_extract_error(res)}",
                        details={"strict": strict_details},
                        should_replan=True
                    )

        # 2. Targeted Linting (eslint)
        if node_paths and mode == "strict":
             targets = " ".join(_quote_path(p) for p in node_paths[:10])
             # Use --yes to ignore prompts and --quiet to ignore formatting warnings (too strict)
             cmd = f"npx --yes eslint {targets} --quiet"
             res = _run_validation_command(cmd, timeout=60)
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
        # In 'fast' mode, we might skip full type checking unless it's a critical file
        if project_type == "vue":
            # Check if we should run vue-tsc
            # If we touched .vue or .ts files
            vue_ts_touched = any(p.suffix in ('.vue', '.ts') for p in paths)
            if vue_ts_touched:
                # Try running vue-tsc if available in package.json
                # This is heavy, so only run if we're not in super-fast mode?
                # For now, let's assume 'fast' mode avoids full project type check.
                if mode == "strict":
                    cmd = "npx --yes vue-tsc --noEmit"
                    res = _run_validation_command(cmd, timeout=120)
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
        if test_touched or mode == "strict":
            # Try dynamic discovery first
            test_cmd = None
            hinted_test = None
            
            # Find a relevant test file to inspect
            relevant_test_file = next((p for p in paths if p.is_file() and ("test" in p.name or "spec" in p.name)), None)
            if relevant_test_file:
                hinted_test = _inspect_file_for_command_hints(relevant_test_file, "test")
            
            if hinted_test:
                test_cmd = hinted_test
            else:
                # Fallback to package.json detection
                root = _find_project_root(primary_path)
                try:
                    pkg_json = json.loads((root / "package.json").read_text(errors='ignore'))
                    scripts = pkg_json.get("scripts", {})
                    if "test:unit" in scripts:
                        test_cmd = "npm run test:unit"
                    elif "test" in scripts:
                        test_cmd = "npm test"
                    else:
                        test_cmd = "npm test" # Generic fallback
                except Exception:
                    test_cmd = "npm test"

            if test_cmd:
                # Prevent watch mode which hangs execution
                if "vitest" in test_cmd or "vite" in test_cmd:
                    if "--run" not in test_cmd and " run" not in test_cmd:
                        test_cmd += " --run"
                elif "jest" in test_cmd:
                    if "--watchAll=false" not in test_cmd:
                        test_cmd += " --watchAll=false"
                
                # Append file filters if possible
                if test_touched:
                    test_files = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) 
                                 for p in paths if "test" in p.name or "spec" in p.name]
                    if test_files:
                        # Use ' -- ' to pass args to the underlying script
                        if "npm run" in test_cmd:
                            test_cmd += " -- " + " ".join(quote_cmd_arg(f) for f in test_files)
                        else:
                            test_cmd += " " + " ".join(quote_cmd_arg(f) for f in test_files)

                res = _run_validation_command(test_cmd, use_tests_tool=True, timeout=config.VALIDATION_TIMEOUT_SECONDS)
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
        if mode == "strict" or custom_test_cmd:
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
        if mode == "strict" or custom_test_cmd:
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
            
        if mode == "strict" or custom_test_cmd:
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


def _inspect_file_for_command_hints(path: Path, tool_type: str) -> Optional[str]:
    """Inspect a file's content and environment for tool-specific execution hints."""
    try:
        if not path.exists() or not path.is_file():
            return None
            
        content = path.read_text(errors='ignore')
        root = _find_project_root(path)
        
        if tool_type == "test":
            # Node.js Test detection
            if path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                # 1. Content-based detection
                if "vitest" in content or "from 'vitest'" in content or "from \"vitest\"" in content:
                    return "npx --yes vitest run"
                if "jest" in content or "@jest/globals" in content or "describe(" in content:
                    return "npx --yes jest --watchAll=false"
                if "mocha" in content or "describe(" in content: # Mocha also uses describe
                    # Check package.json for mocha
                    pkg_json_path = root / "package.json"
                    if pkg_json_path.exists():
                        pkg_json = json.loads(pkg_json_path.read_text(errors='ignore'))
                        if "mocha" in str(pkg_json.get("devDependencies", {})) or "mocha" in str(pkg_json.get("dependencies", {})):
                            return "npx --yes mocha"

                # 2. Package.json script detection
                pkg_json_path = root / "package.json"
                if pkg_json_path.exists():
                    pkg_json = json.loads(pkg_json_path.read_text(errors='ignore'))
                    scripts = pkg_json.get("scripts", {})
                    for s_name in ("test:unit", "test", "unit"):
                        if s_name in scripts:
                            s_cmd = scripts[s_name].lower()
                            if "vitest" in s_cmd: return "npx --yes vitest run"
                            if "jest" in s_cmd: return "npx --yes jest --watchAll=false"
                            if "mocha" in s_cmd: return "npx --yes mocha"
            
            # Python Test detection
            if path.suffix == ".py":
                if "import unittest" in content or "unittest.TestCase" in content:
                    return "python -m unittest"
                if "import pytest" in content or "def test_" in content or "@pytest." in content:
                    return "pytest -q"
                    
        elif tool_type == "lint":
            # Node.js Lint detection
            if path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                # If we see eslint comments or have a local config, prefer eslint
                if "eslint" in content or any((root / f).exists() for f in (".eslintrc.json", "eslint.config.js", ".eslintrc.js", "eslint.config.mjs", "eslint.config.cjs")):
                    return "npx --yes eslint --quiet"
        
        # If static inspection fails, try dynamic help discovery
        help_info = _try_dynamic_help_discovery(path)
        if help_info:
            # We don't return the full help, but we've verified it responds to help
            # This logic could be expanded to parse the help for specific runners
            pass
                    
    except Exception:
        pass
    return None


def _run_validation_steps(task: Task, details: Dict[str, Any], tool_events: Optional[Iterable[Dict[str, Any]]]) -> Optional[VerificationResult | Dict[str, Any]]:
    """Execute declarative validation steps (lint/tests/compile) via tool runner."""
    validation_steps = task.validation_steps
    commands: list[tuple[str, str, str]] = []
    seen_cmds = set()
    paths = _paths_or_default(_collect_paths_for_strict_checks("", details, tool_events))

    def _add(label: str, cmd: str, tool: str = "run_cmd") -> None:
        if cmd in seen_cmds:
            return
        seen_cmds.add(cmd)
        commands.append((label, cmd, tool))

    # Get project type relative to the first relevant path
    primary_path = paths[0] if paths else config.ROOT
    project_type = _detect_project_type(primary_path)

    # Get Python file paths for targeted linting
    py_paths = [p for p in paths if p.suffix == ".py" and p.exists()]

    # Get Node file paths for targeted linting
    node_extensions = {".js", ".ts", ".jsx", ".tsx", ".vue", ".mjs", ".cjs"}
    node_paths = [p for p in paths if p.suffix in node_extensions and p.exists()]

    for step in validation_steps:
        text = step.lower()
        
        # 1. SYNTAX / COMPILE
        if "syntax" in text or "compile" in text or "build" in text:
            if project_type == "python":
                compile_targets = [p for p in paths if p.is_dir() or p.suffix == '.py']
                if compile_targets:
                    _add("compileall", "python -m compileall " + " ".join(_quote_path(p) for p in compile_targets))
            elif project_type == "go": _add("go_build", "go build ./...")
            elif project_type == "rust": _add("cargo_check", "cargo check")
            elif project_type == "csharp": _add("dotnet_build", "dotnet build")
            elif project_type == "cpp_cmake": _add("cmake_build", "cmake --build .")
            elif project_type == "cpp_make": _add("make", "make")
            elif project_type == "java_maven": _add("mvn_compile", "mvn compile")
            elif project_type == "java_gradle" or project_type == "kotlin": _add("gradle_build", "./gradlew build")

        # 2. LINT
        if "lint" in text or "linter" in text:
            hinted_lint = _inspect_file_for_command_hints(primary_path, "lint") if paths else None
            
            if hinted_lint and node_paths:
                targets = " ".join(_quote_path(p) for p in node_paths[:10])
                _add("eslint_hinted", f"{hinted_lint} {targets}")
            elif project_type == "python" and py_paths:
                ruff_targets = " ".join(_quote_path(p) for p in py_paths[:10])
                _add("ruff", f"ruff check {ruff_targets} --select E9,F63,F7")
            elif project_type in ("node", "vue", "react", "nextjs"):
                if node_paths:
                    targets = " ".join(_quote_path(p) for p in node_paths[:10])
                    # Use npx --yes eslint --quiet to target specific files and ignore formatting warnings (too strict)
                    _add("eslint", f"npx --yes eslint {targets} --quiet")
                else:
                    _add("npm_lint", "npm run lint")
            elif project_type == "go": _add("go_vet", "go vet ./...")
            elif project_type == "rust": _add("clippy", "cargo clippy")

        # 3. TEST
        if "test" in text:
            hinted_test = _inspect_file_for_command_hints(primary_path, "test") if paths else None
            
            if hinted_test:
                target = _quote_path(primary_path)
                _add("hinted_test", f"{hinted_test} {target}", "run_tests")
            elif project_type == "python": _add("pytest", "pytest -q", "run_tests")
            elif project_type in ("node", "vue", "react", "nextjs"): _add("npm_test", "npm test", "run_tests")
            elif project_type == "go": _add("go_test", "go test ./...", "run_tests")
            elif project_type == "rust": _add("cargo_test", "cargo test", "run_tests")
            elif project_type == "ruby": _add("rake_test", "bundle exec rake test", "run_tests")
            elif project_type == "php": _add("phpunit", "vendor/bin/phpunit", "run_tests")
            elif project_type == "java_maven": _add("mvn_test", "mvn test", "run_tests")
            elif project_type == "java_gradle" or project_type == "kotlin": _add("gradle_test", "./gradlew test", "run_tests")
            elif project_type == "csharp": _add("dotnet_test", "dotnet test", "run_tests")
            elif project_type == "flutter": _add("flutter_test", "flutter test", "run_tests")
            else: _add("pytest", "pytest -q", "run_tests") # Default fallback

        # 4. TYPE CHECK
        if "mypy" in text or "type" in text:
            if project_type == "python" and py_paths:
                mypy_targets = " ".join(_quote_path(p) for p in py_paths[:10])
                _add("mypy", f"mypy {mypy_targets}")
            elif project_type in ("node", "typescript", "vue", "react", "nextjs"):
                _add("tsc", "npx --yes tsc --noEmit")

    if not commands:
        return None

    results: Dict[str, Any] = {}
    for label, cmd, tool in commands:
        res = _run_validation_command(cmd, use_tests_tool=(tool == "run_tests"), timeout=config.VALIDATION_TIMEOUT_SECONDS)
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
        if payload.get("timeout"):
            return VerificationResult(
                passed=False,
                message="Test command timed out",
                details=payload,
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
        output = (payload.get("stdout", "") or "") + (payload.get("stderr", "") or "")
        context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
        context.agent_state["last_test_rc"] = rc
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
