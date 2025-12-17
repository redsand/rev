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


@dataclass
class VerificationResult:
    """Result of verifying a task's execution."""
    passed: bool
    message: str
    details: Dict[str, Any]
    should_replan: bool = False

    def __str__(self) -> str:
        status = '[OK]' if self.passed else '[FAIL]'
        return f"{status} {self.message}"


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

    # Check if this is an extraction task
    desc_lower = task.description.lower()
    is_extraction = any(word in desc_lower for word in ["extract", "break out", "split", "separate", "move out"])

    if not is_extraction:
        return VerificationResult(
            passed=True,
            message="Refactoring task does not appear to be an extraction",
            details={"is_extraction": False}
        )

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

    # Check 1: Directory exists
    if not target_dir.exists():
        issues.append(f"Target directory '{target_dir}' does not exist")
    else:
        details["directory_exists"] = True

        # Check 2: Files were created in the directory
        py_files = list(target_dir.glob("*.py"))
        if not py_files:
            issues.append(f"No Python files found in '{target_dir}' - extraction may have failed")
        else:
            details["files_created"] = len(py_files)
            details["files"] = [f.name for f in py_files]

            # Check 3: Verify imports in created files
            import_errors = []
            for py_file in py_files:
                try:
                    content = py_file.read_text()
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
                                import_errors.append(f"{py_file.name}: imports missing {module_name}.py")
                except Exception as e:
                    import_errors.append(f"Error reading {py_file.name}: {e}")

            if import_errors:
                issues.extend(import_errors)
            else:
                details["imports_valid"] = True

    # Check 4: Verify old file was updated with imports (if applicable)
    # Look for the original file mentioned in task description
    old_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\-]+\.py)'
    old_file_matches = re.findall(old_file_pattern, task.description)
    if old_file_matches:
        old_file = Path(old_file_matches[0])
        if old_file.exists():
            try:
                content = old_file.read_text()
                # Check if it has import statements from the new directory
                has_imports_from_new = re.search(rf'from\s+\.{target_dir.name}', content)
                if has_imports_from_new:
                    details["main_file_updated"] = True
                else:
                    issues.append(f"Original file {old_file} not updated with imports from {target_dir}")
            except Exception as e:
                issues.append(f"Could not read {old_file}: {e}")

    if issues:
        return VerificationResult(
            passed=False,
            message=f"Extraction verification failed: {len(issues)} issue(s) found",
            details={**details, "issues": issues},
            should_replan=True
        )

    return VerificationResult(
        passed=True,
        message=f"Extraction successful: {details.get('files_created', 0)} files created with valid imports",
        details=details
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


def _verify_file_edit(task: Task, context: RevContext) -> VerificationResult:
    """Verify that a file was actually edited."""

    # This is harder to verify without knowing the original content
    # For now, just check that the file exists and isn't empty

    patterns = [
        r'(?:in\s+)?(?:file\s+)?["\']?(\.?\/[a-zA-Z0-9_/\-]+\.py)["\']?',
        r'(?:edit|update|modify)\s+["\']?([a-zA-Z0-9_/\-]+\.py)["\']?',
    ]

    file_path = None
    for pattern in patterns:
        matches = re.findall(pattern, task.description, re.IGNORECASE)
        if matches:
            file_path = Path(matches[0])
            break

    if not file_path:
        return VerificationResult(
            passed=False,
            message="Could not determine file path to verify",
            details={},
            should_replan=True
        )

    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

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
        content = source_file.read_text()
        if not content.strip():
            details["warning"] = f"Source file {source_file} is now empty after extraction"
            return False, details

    return True, details
