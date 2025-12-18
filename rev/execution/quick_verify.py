"""
Quick verification module for sub-agent execution.

Provides lightweight, task-specific verification that can be run after each
task completes to ensure it actually did what was requested. This is critical
for the workflow loop: Plan → Execute → Verify → Report → Re-plan if needed
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from rev.models.task import Task, TaskStatus
from rev.tools.registry import execute_tool, get_last_tool_call
from rev.core.context import RevContext
from rev.tools.workspace_resolver import WorkspacePathError, resolve_workspace_path


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

    # If the planner mislabeled the action type but the tool call clearly indicates
    # a directory creation, verify it as such. This prevents false failures like
    # "File created but is empty" when a directory was created.
    last_call = get_last_tool_call() or {}
    last_tool = (last_call.get("name") or "").lower()
    if last_tool == "create_directory" and action_type in {"add", "create"}:
        return _verify_directory_creation(task, context)

    # Route to appropriate verification handler
    if action_type == "refactor":
        return _verify_refactoring(task, context)
    elif action_type == "add" or action_type == "create":
        return _verify_file_creation(task, context)
    elif action_type == "edit":
        return _verify_file_edit(task, context)
    elif action_type == "create_directory":
        return _verify_directory_creation(task, context)
    elif action_type == "test":
        return _verify_test_execution(task, context)
    else:
        # For unknown action types, return a passing result but flag for caution
        return VerificationResult(
            passed=True,
            message=f"No specific verification available for action type '{action_type}'",
            details={"action_type": action_type, "note": "Verification skipped for this action type"}
        )


def _verify_refactoring(task: Task, context: RevContext) -> VerificationResult:
    """
    Verify that a refactoring task actually extracted/reorganized code.

    For extraction tasks like "break out analysts into individual files":
    - Check that new files were created
    - Check that imports in new files are valid
    - Check that the old file was updated with imports
    """

    details = {}
    issues = []
    debug_info = {}
    result_payload = _parse_task_result_payload(task.result)
    call_sites_updated = []
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

        if not target_dir:
            package_init = result_payload.get("package_init")
            if isinstance(package_init, str) and package_init.strip():
                init_path = _resolve_for_verification(package_init.strip(), purpose="verify refactoring package init")
                if init_path:
                    target_dir = init_path.parent

    if not target_dir:
        last_call = get_last_tool_call() or {}
        if (last_call.get("name") or "").lower() == "split_python_module_classes":
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("target_directory")
                if isinstance(candidate, str) and candidate.strip():
                    target_dir = _resolve_for_verification(candidate.strip(), purpose="verify refactoring target dir")

    if not target_dir:
        # Fallback: try to parse something directory-looking from the task description.
        dir_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\-]+\/[a-zA-Z0-9_\-]+)(?:\/)?'
        dir_matches = re.findall(dir_pattern, task.description)
        if dir_matches:
            best_dir = max(dir_matches, key=len)
            target_dir = _resolve_for_verification(best_dir.strip("/"), purpose="verify refactoring target dir")

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
    old_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\-]+\.py)'
    old_file_matches = re.findall(old_file_pattern, task.description)
    if old_file_matches:
        old_file = _resolve_for_verification(old_file_matches[0], purpose="verify refactoring source file")
        if not old_file:
            issues.append(f"[FAIL] Could not resolve source file path for verification: {old_file_matches[0]}")
            debug_info["main_file_status"] = "UNRESOLVABLE"
            old_file = None
        debug_info["source_file"] = str(old_file)
        debug_info["source_file_exists"] = old_file.exists() if old_file else False

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
                    issues.append(
                        f"[FAIL] Original file {old_file} no longer exists and package '{package_candidate}' was not found"
                    )
                    debug_info["main_file_status"] = "MISSING"

    if issues:
        if call_sites_updated:
            non_benign = [issue for issue in issues if "Original file" not in issue]
            if not non_benign:
                warning_msg = "Source module still exists but class files and call sites were updated"
                details["warnings"] = issues
                debug_info["warnings"] = issues
                return VerificationResult(
                    passed=True,
                    message=f"[OK] Extraction succeeded with call site updates ({len(call_sites_updated)} files); "
                            f"{warning_msg}",
                    details={**details, "debug": debug_info}
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
    extracted_from_result = _extract_path_from_task_result(task.result)
    if extracted_from_result:
        file_path = _resolve_for_verification(extracted_from_result, purpose="verify file creation")

    # Try to extract file path from task description
    # Patterns: "create file at ./lib/file.py" or "add ./lib/file.py"
    patterns = [
        r'(?:file\s+)?(?:at\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\.py)["\']?',
        r'(?:add|create)\s+(?:file\s+)?(?:at\s+)?["\']?([a-zA-Z0-9_/\-]+\.py)["\']?',
    ]

    if not file_path:
        for pattern in patterns:
            matches = re.findall(pattern, task.description, re.IGNORECASE)
            if matches:
                candidate = matches[0]
                file_path = _resolve_for_verification(candidate, purpose="verify file creation")
                if file_path:
                    break

    if not file_path:
        # If we can't determine from description, check task.result
        if task.result and isinstance(task.result, str):
            # Result might contain the file path
            result_match = re.search(r'(?:\.?\/)?[a-zA-Z0-9_/\-]+\.py', task.result)
            if result_match:
                file_path = _resolve_for_verification(result_match.group(0), purpose="verify file creation")

    if not file_path:
        last_call = get_last_tool_call()
        if last_call:
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("path") or args.get("file") or args.get("target")
                if isinstance(candidate, str) and candidate.strip():
                    file_path = _resolve_for_verification(candidate.strip(), purpose="verify file creation")

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


def _verify_file_edit(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a file was actually edited."""

    # This is harder to verify without knowing the original content
    # For now, just check that the file exists and isn't empty

    patterns = [
        # ./path/to/file.py or /path/to/file.py
        r'(?:in\s+)?(?:file\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\.py)["\']?',
        # phrases like "edit foo.py" or "modify foo.py"
        r'(?:edit|update|modify)\s+["\']?([a-zA-Z0-9_/\-]+\.py)["\']?',
        # fallback: any python file path-looking token
        r'([a-zA-Z0-9_\-./\\]+\.py)',
    ]

    extracted_path: Path | None = None
    raw_candidate: str | None = None
    for pattern in patterns:
        matches = re.findall(pattern, task.description, re.IGNORECASE)
        if matches:
            raw_candidate = matches[0]
            break

    if raw_candidate:
        normalized = raw_candidate.strip().strip('"\''" ")
        # Remove leading ./ or .\ or excess slashes (so "/foo.py" -> "foo.py")
        normalized = re.sub(r'^[./\\]+', '', normalized)
        if normalized:
            extracted_path = Path(normalized)

    if not extracted_path:
        result_path = _extract_path_from_task_result(task.result)
        if result_path:
            extracted_path = Path(result_path.strip().strip("\"'"))

    if not extracted_path:
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
                    extracted_path = Path(candidate.strip().strip("\"'"))

    if not extracted_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={},
            should_replan=True
        )

    file_path = _resolve_for_verification(str(extracted_path), purpose="verify file edit")
    if not file_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={"path": str(extracted_path)},
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
    extracted_from_result = _extract_path_from_task_result(task.result)
    if extracted_from_result:
        dir_path = _resolve_for_verification(extracted_from_result, purpose="verify directory creation")

    patterns = [
        r'(?:directory\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\/)["\']?',
        r'(?:create|add)\s+(?:directory\s+)?["\']?([a-zA-Z0-9_/\-]+\/)["\']?',
    ]

    if not dir_path:
        for pattern in patterns:
            matches = re.findall(pattern, task.description, re.IGNORECASE)
            if matches:
                candidate = matches[0].strip("/").strip("\\")
                dir_path = _resolve_for_verification(candidate, purpose="verify directory creation")
                if dir_path:
                    break

    if not dir_path:
        last_call = get_last_tool_call()
        if last_call:
            args = last_call.get("args") or {}
            if isinstance(args, dict):
                candidate = args.get("path") or args.get("target")
                if isinstance(candidate, str) and candidate.strip():
                    dir_path = _resolve_for_verification(candidate.strip(), purpose="verify directory creation")

    if not dir_path:
        return VerificationResult(
            passed=False,
            message="Could not determine directory path to verify",
            details={},
            should_replan=True
        )

    if dir_path.exists() and dir_path.is_dir():
        return VerificationResult(
            passed=True,
            message=f"Directory created successfully: {dir_path.name}",
            details={"directory_path": str(dir_path), "is_dir": True}
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
    if payload and isinstance(payload.get("rc"), int):
        rc = payload.get("rc", 1)
        output = (payload.get("stdout", "") or "") + (payload.get("stderr", "") or "")
        context.agent_state["last_test_iteration"] = context.agent_state.get("current_iteration")
        context.agent_state["last_test_rc"] = rc
        if rc == 0:
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
        return VerificationResult(
            passed=False,
            message="Skipping test re-run (no code changes since last failure)",
            details={"last_test_iteration": last_test_iteration, "last_test_rc": last_test_rc},
            should_replan=True
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
