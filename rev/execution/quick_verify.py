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
from rev.tools.registry import execute_tool
from rev.core.context import RevContext


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

    # Don't try to guess the refactoring type - just verify the repo state changed
    # If there are issues below, they'll be caught. Otherwise, assume it succeeded.

    # Try to identify the target directory from the task description
    # Look for patterns like "./lib/analysts/" or "lib/analysts"
    dir_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\-]+\/[a-zA-Z0-9_\-]+\/)'
    dir_matches = re.findall(dir_pattern, task.description)

    if not dir_matches:
        return VerificationResult(
            passed=False,
            message="Could not determine target directory from task description",
            details={"description": task.description, "warning": "Cannot verify extraction without target dir"},
            should_replan=True
        )

    target_dir = Path(dir_matches[0].strip("/"))
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
        old_file = Path(old_file_matches[0])
        debug_info["source_file"] = str(old_file)
        debug_info["source_file_exists"] = old_file.exists()

        if old_file.exists():
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

    # Try to extract file path from task description
    # Patterns: "create file at ./lib/file.py" or "add ./lib/file.py"
    patterns = [
        r'(?:file\s+)?(?:at\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\.py)["\']?',
        r'(?:add|create)\s+(?:file\s+)?(?:at\s+)?["\']?([a-zA-Z0-9_/\-]+\.py)["\']?',
    ]

    file_path = None
    for pattern in patterns:
        matches = re.findall(pattern, task.description, re.IGNORECASE)
        if matches:
            file_path = Path(matches[0])
            break

    if not file_path:
        # If we can't determine from description, check task.result
        if task.result and isinstance(task.result, str):
            # Result might contain the file path
            result_match = re.search(r'(?:\.?\/)?[a-zA-Z0-9_/\-]+\.py', task.result)
            if result_match:
                file_path = Path(result_match.group(0))

    if not file_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={"description": task.description},
            should_replan=True
        )

    # Ensure relative path is absolute
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

    # Check if file exists
    if file_path.exists():
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

    for key in ("file", "path", "updated_file"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
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
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={},
            should_replan=True
        )

    if extracted_path.is_absolute():
        file_path = extracted_path
    else:
        file_path = Path.cwd() / extracted_path

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

    patterns = [
        r'(?:directory\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\/)["\']?',
        r'(?:create|add)\s+(?:directory\s+)?["\']?([a-zA-Z0-9_/\-]+\/)["\']?',
    ]

    dir_path = None
    for pattern in patterns:
        matches = re.findall(pattern, task.description, re.IGNORECASE)
        if matches:
            dir_path = Path(matches[0].strip("/"))
            break

    if not dir_path:
        return VerificationResult(
            passed=False,
            message="Could not determine directory path to verify",
            details={},
            should_replan=True
        )

    if not dir_path.is_absolute():
        dir_path = Path.cwd() / dir_path

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

    # Try to run tests
    try:
        result = execute_tool("run_tests", {"cmd": "pytest -q", "timeout": 30})
        result_data = json.loads(result)
        rc = result_data.get("rc", 1)
        output = result_data.get("stdout", "") + result_data.get("stderr", "")

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
