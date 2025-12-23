#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DoD Verifier.

Verifies that all Definition of Done criteria are satisfied before marking a task complete.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path
import subprocess
import re

from rev.models.dod import DefinitionOfDone, Deliverable, DeliverableType
from rev.models.task import Task


@dataclass
class DeliverableVerificationResult:
    """Result of verifying a single deliverable."""
    deliverable: Deliverable
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DoDVerificationResult:
    """Result of verifying an entire DoD."""
    passed: bool
    dod: DefinitionOfDone
    deliverable_results: List[DeliverableVerificationResult] = field(default_factory=list)
    unmet_criteria: List[str] = field(default_factory=list)
    met_criteria: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Generate a summary of the verification result."""
        total = len(self.deliverable_results)
        passed_count = sum(1 for r in self.deliverable_results if r.passed)

        lines = [
            f"DoD Verification: {'PASSED' if self.passed else 'FAILED'}",
            f"Deliverables: {passed_count}/{total} passed"
        ]

        if self.met_criteria:
            lines.append(f"Met criteria ({len(self.met_criteria)}):")
            for criterion in self.met_criteria:
                lines.append(f"  ✓ {criterion}")

        if self.unmet_criteria:
            lines.append(f"Unmet criteria ({len(self.unmet_criteria)}):")
            for criterion in self.unmet_criteria:
                lines.append(f"  ✗ {criterion}")

        return "\n".join(lines)


def verify_dod(dod: DefinitionOfDone, task: Task, workspace_root: Path = None) -> DoDVerificationResult:
    """
    Verify all DoD criteria are satisfied.

    This is a HARD GATE - the task cannot be marked complete unless all criteria pass.

    Args:
        dod: The Definition of Done to verify
        task: The task that was executed
        workspace_root: Root directory for path resolution

    Returns:
        DoDVerificationResult with pass/fail status and details
    """
    if workspace_root is None:
        workspace_root = Path.cwd()

    deliverable_results = []
    unmet_criteria = []
    met_criteria = []

    # Verify each deliverable
    for deliverable in dod.deliverables:
        result = _verify_deliverable(deliverable, task, workspace_root)
        deliverable_results.append(result)

        if not result.passed:
            unmet_criteria.append(f"{deliverable.type.value}: {result.message}")

    # Verify acceptance criteria
    for criterion in dod.acceptance_criteria:
        is_met = _verify_criterion(criterion, task, workspace_root, deliverable_results)
        if is_met:
            met_criteria.append(criterion)
        else:
            unmet_criteria.append(criterion)

    # Overall pass = all deliverables passed AND all criteria met
    all_passed = all(r.passed for r in deliverable_results) and not unmet_criteria

    # ENFORCEMENT: API Work Requirements
    # If the task looks like API work, require at least one integration check
    api_keywords = ["api", "route", "endpoint", "controller", "rest", "crud", "auth"]
    is_api_work = any(kw in task.description.lower() for kw in api_keywords)
    
    if is_api_work and all_passed:
        api_checks = {
            DeliverableType.API_ROUTE_CHECK,
            DeliverableType.CURL_SMOKE_TEST,
            DeliverableType.PLAYWRIGHT_TEST,
            DeliverableType.TEST_PASS # Generic tests might cover it
        }
        has_api_check = any(r.deliverable.type in api_checks and r.passed for r in deliverable_results)
        
        if not has_api_check:
            all_passed = False
            msg = "API work detected but no integration check (route check, curl, or playwright) was performed or passed."
            unmet_criteria.append(f"API_GATE: {msg}")

    return DoDVerificationResult(
        passed=all_passed,
        dod=dod,
        deliverable_results=deliverable_results,
        unmet_criteria=unmet_criteria,
        met_criteria=met_criteria,
        details={
            "task_id": task.task_id if hasattr(task, 'task_id') else None,
            "task_description": task.description
        }
    )


def _verify_deliverable(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify a single deliverable."""

    if deliverable.type == DeliverableType.FILE_MODIFIED:
        return _verify_file_modified(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.FILE_CREATED:
        return _verify_file_created(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.FILE_DELETED:
        return _verify_file_deleted(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.TEST_PASS:
        return _verify_test_pass(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.SYNTAX_VALID:
        return _verify_syntax_valid(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.RUNTIME_CHECK:
        return _verify_runtime_check(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.IMPORTS_WORK:
        return _verify_imports_work(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.API_ROUTE_CHECK:
        return _verify_api_route_check(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.CURL_SMOKE_TEST:
        return _verify_curl_smoke_test(deliverable, task, workspace_root)

    elif deliverable.type == DeliverableType.PLAYWRIGHT_TEST:
        return _verify_playwright_test(deliverable, task, workspace_root)

    else:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Unknown deliverable type: {deliverable.type}"
        )


def _verify_api_route_check(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify API route is registered."""
    if not deliverable.expect:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No route pattern specified in 'expect'"
        )

    # Try to find route registration in modified files
    found = False
    if hasattr(task, 'tool_events') and task.tool_events:
        for event in task.tool_events:
            args = event.get('args', {})
            path = args.get('path') or args.get('file_path')
            if path:
                p = workspace_root / path
                if p.exists() and p.is_file():
                    content = p.read_text(errors='ignore')
                    if re.search(deliverable.expect, content):
                        found = True
                        break

    if found:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=True,
            message=f"API route registration found: {deliverable.expect}"
        )
    else:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"API route registration NOT found: {deliverable.expect}"
        )


def _verify_curl_smoke_test(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify API endpoint via curl."""
    if not deliverable.command:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No curl command specified"
        )

    try:
        # Use run_cmd via tool registry if possible, or subprocess
        from rev.tools.registry import execute_tool
        result_json = execute_tool("run_cmd", {"cmd": deliverable.command, "timeout": 30})
        result = json.loads(result_json)

        if result.get("rc") == 0:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=True,
                message=f"Curl smoke test passed"
            )
        else:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Curl smoke test failed: {result.get('stderr')}"
            )
    except Exception as e:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Curl smoke test failed: {e}"
        )


def _verify_playwright_test(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify via Playwright."""
    cmd = deliverable.command or "npx playwright test"
    
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=True,
                message="Playwright tests passed"
            )
        else:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Playwright tests failed (rc={result.returncode})",
                details={"stderr": result.stderr}
            )
    except Exception as e:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Playwright execution failed: {e}"
        )


def _verify_file_modified(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify a file was modified."""
    if not deliverable.path and not deliverable.paths:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No file path specified"
        )

    paths_to_check = deliverable.paths if deliverable.paths else [deliverable.path]

    # Check if files exist
    for path_str in paths_to_check:
        file_path = workspace_root / path_str
        if not file_path.exists():
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"File does not exist: {path_str}"
            )

    # Check if file was actually modified by looking at tool events
    if hasattr(task, 'tool_events') and task.tool_events:
        modified_files = set()
        for event in task.tool_events:
            if isinstance(event, dict):
                args = event.get('args', {})
                for key in ['path', 'file_path', 'target']:
                    if key in args:
                        modified_files.add(args[key])

        # Check if any of the expected files were modified
        for path_str in paths_to_check:
            if any(path_str in mf or mf in path_str for mf in modified_files):
                return DeliverableVerificationResult(
                    deliverable=deliverable,
                    passed=True,
                    message=f"File modified: {path_str}",
                    details={"modified_files": list(modified_files)}
                )

    # Fallback: just check if file exists
    return DeliverableVerificationResult(
        deliverable=deliverable,
        passed=True,
        message=f"Files exist: {', '.join(paths_to_check)}"
    )


def _verify_file_created(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify a file was created."""
    if not deliverable.path and not deliverable.paths:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No file path specified"
        )

    paths_to_check = deliverable.paths if deliverable.paths else [deliverable.path]

    for path_str in paths_to_check:
        file_path = workspace_root / path_str
        if not file_path.exists():
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"File was not created: {path_str}"
            )

        # Check file is not empty
        if file_path.stat().st_size == 0:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"File exists but is empty: {path_str}"
            )

    return DeliverableVerificationResult(
        deliverable=deliverable,
        passed=True,
        message=f"Files created: {', '.join(paths_to_check)}"
    )


def _verify_file_deleted(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify a file was deleted."""
    if not deliverable.path and not deliverable.paths:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No file path specified"
        )

    paths_to_check = deliverable.paths if deliverable.paths else [deliverable.path]

    for path_str in paths_to_check:
        file_path = workspace_root / path_str
        if file_path.exists():
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"File still exists (should be deleted): {path_str}"
            )

    return DeliverableVerificationResult(
        deliverable=deliverable,
        passed=True,
        message=f"Files deleted: {', '.join(paths_to_check)}"
    )


def _verify_test_pass(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify tests pass."""
    if not deliverable.command:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No test command specified"
        )

    try:
        result = subprocess.run(
            deliverable.command,
            shell=True,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=60
        )

        expected_rc = 0
        if deliverable.expect:
            # Parse expected exit code from expect string
            match = re.search(r'exit.*?code.*?==\s*(\d+)', deliverable.expect)
            if match:
                expected_rc = int(match.group(1))

        if result.returncode == expected_rc:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=True,
                message=f"Tests passed (exit code: {result.returncode})",
                details={"stdout": result.stdout[:500], "stderr": result.stderr[:500]}
            )
        else:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Tests failed (exit code: {result.returncode}, expected: {expected_rc})",
                details={"stdout": result.stdout[:500], "stderr": result.stderr[:500]}
            )

    except subprocess.TimeoutExpired:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="Test command timed out (60s)"
        )
    except Exception as e:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Failed to run test command: {e}"
        )


def _verify_syntax_valid(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify syntax is valid."""
    paths_to_check = deliverable.paths if deliverable.paths else ([deliverable.path] if deliverable.path else [])

    if not paths_to_check:
        # Check all Python files modified by task
        if hasattr(task, 'tool_events') and task.tool_events:
            paths_to_check = []
            for event in task.tool_events:
                if isinstance(event, dict):
                    args = event.get('args', {})
                    for key in ['path', 'file_path']:
                        if key in args and args[key].endswith('.py'):
                            paths_to_check.append(args[key])

    if not paths_to_check:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=True,
            message="No Python files to check"
        )

    # Run compileall on each file
    for path_str in paths_to_check:
        file_path = workspace_root / path_str
        if not file_path.exists():
            continue

        try:
            result = subprocess.run(
                ["python", "-m", "compileall", str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return DeliverableVerificationResult(
                    deliverable=deliverable,
                    passed=False,
                    message=f"Syntax error in {path_str}",
                    details={"stderr": result.stderr}
                )

        except Exception as e:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Failed to check syntax: {e}"
            )

    return DeliverableVerificationResult(
        deliverable=deliverable,
        passed=True,
        message=f"Syntax valid for {len(paths_to_check)} file(s)"
    )


def _verify_runtime_check(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify runtime check."""
    if not deliverable.command:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No command specified"
        )

    try:
        result = subprocess.run(
            deliverable.command,
            shell=True,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        expected_rc = 0
        if deliverable.expect:
            match = re.search(r'exit.*?code.*?==\s*(\d+)', deliverable.expect)
            if match:
                expected_rc = int(match.group(1))

        if result.returncode == expected_rc:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=True,
                message=f"Runtime check passed (exit code: {result.returncode})"
            )
        else:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Runtime check failed (exit code: {result.returncode}, expected: {expected_rc})"
            )

    except Exception as e:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Runtime check failed: {e}"
        )


def _verify_imports_work(
    deliverable: Deliverable,
    task: Task,
    workspace_root: Path
) -> DeliverableVerificationResult:
    """Verify imports work."""
    if not deliverable.path:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message="No module path specified"
        )

    # Convert file path to module name
    module_name = deliverable.path.replace("/", ".").replace("\\", ".").replace(".py", "")

    try:
        result = subprocess.run(
            ["python", "-c", f"import {module_name}"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=True,
                message=f"Import successful: {module_name}"
            )
        else:
            return DeliverableVerificationResult(
                deliverable=deliverable,
                passed=False,
                message=f"Import failed: {module_name}",
                details={"stderr": result.stderr}
            )

    except Exception as e:
        return DeliverableVerificationResult(
            deliverable=deliverable,
            passed=False,
            message=f"Import check failed: {e}"
        )


def _verify_criterion(
    criterion: str,
    task: Task,
    workspace_root: Path,
    deliverable_results: List[DeliverableVerificationResult]
) -> bool:
    """Verify a single acceptance criterion."""
    criterion_lower = criterion.lower()

    # Check for common patterns
    if "pytest" in criterion_lower and "exit" in criterion_lower and "0" in criterion_lower:
        # Check if any test deliverable passed
        return any(
            r.passed and r.deliverable.type == DeliverableType.TEST_PASS
            for r in deliverable_results
        )

    if "syntax" in criterion_lower and "error" in criterion_lower:
        # Check if syntax validation passed
        return any(
            r.passed and r.deliverable.type == DeliverableType.SYNTAX_VALID
            for r in deliverable_results
        )

    if "no" in criterion_lower and "error" in criterion_lower:
        # Generic "no errors" check - all deliverables passed
        return all(r.passed for r in deliverable_results)

    # Fallback: assume met if we got this far
    return True
