#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-Stage Verification Pipeline.

Implements layered verification: syntax → unit → integration → behavioral.
Each stage validates different aspects of code quality and correctness.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
from enum import Enum
import subprocess
import re

from rev.models.task import Task


class VerificationStage(Enum):
    """Verification stages in order of execution."""
    SYNTAX = "syntax"           # Compile/parse check
    UNIT = "unit"               # Unit tests
    INTEGRATION = "integration" # Integration tests
    BEHAVIORAL = "behavioral"   # End-to-end behavioral tests


class RiskLevel(Enum):
    """Risk levels for determining required verification stages."""
    LOW = "low"           # Docs, comments, config only
    MEDIUM = "medium"     # Code changes
    HIGH = "high"         # Infra, tooling, multi-file changes


@dataclass
class StageResult:
    """Result of running a single verification stage."""
    stage: VerificationStage
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class VerificationResult:
    """Result of running the full verification pipeline."""
    passed: bool
    stages_run: List[StageResult] = field(default_factory=list)
    stages_skipped: List[VerificationStage] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    details: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Generate a summary of the verification result."""
        total = len(self.stages_run)
        passed_count = sum(1 for s in self.stages_run if s.passed)

        lines = [
            f"Verification: {'PASSED' if self.passed else 'FAILED'}",
            f"Risk Level: {self.risk_level.value}",
            f"Stages: {passed_count}/{total} passed"
        ]

        if self.stages_run:
            lines.append("Stage Results:")
            for result in self.stages_run:
                status = "✓" if result.passed else "✗"
                lines.append(f"  {status} {result.stage.value}: {result.message}")

        if self.stages_skipped:
            lines.append(f"Skipped Stages: {', '.join(s.value for s in self.stages_skipped)}")

        return "\n".join(lines)


class VerificationPipeline:
    """Multi-stage verification pipeline for code changes."""

    def __init__(self, workspace_root: Path):
        """
        Initialize verification pipeline.

        Args:
            workspace_root: Root directory of the workspace
        """
        self.workspace_root = workspace_root

    def verify(
        self,
        task: Task,
        file_paths: Optional[List[str]] = None,
        required_stages: Optional[List[VerificationStage]] = None
    ) -> VerificationResult:
        """
        Run verification pipeline for a task.

        Args:
            task: The task to verify
            file_paths: Optional list of files to verify (extracted from task if not provided)
            required_stages: Optional list of stages to run (auto-selected if not provided)

        Returns:
            VerificationResult with pass/fail status and stage details
        """
        # Determine file paths
        if file_paths is None:
            file_paths = self._extract_file_paths(task)

        # Assess risk level
        risk_level = self._assess_risk(task, file_paths)

        # Select verification stages
        if required_stages is None:
            required_stages = select_stages_for_task(task, file_paths, risk_level)

        # Run each stage
        stages_run = []
        all_stages = list(VerificationStage)
        stages_skipped = [s for s in all_stages if s not in required_stages]

        for stage in required_stages:
            result = self._run_stage(stage, task, file_paths)
            stages_run.append(result)

            # Stop on first failure
            if not result.passed:
                break

        # Overall pass = all required stages passed
        overall_passed = all(s.passed for s in stages_run)

        return VerificationResult(
            passed=overall_passed,
            stages_run=stages_run,
            stages_skipped=stages_skipped,
            risk_level=risk_level,
            details={
                "task_id": getattr(task, 'task_id', None),
                "file_count": len(file_paths),
                "stage_count": len(stages_run)
            }
        )

    def _run_stage(
        self,
        stage: VerificationStage,
        task: Task,
        file_paths: List[str]
    ) -> StageResult:
        """Run a single verification stage."""
        if stage == VerificationStage.SYNTAX:
            return self._verify_syntax(file_paths)
        elif stage == VerificationStage.UNIT:
            return self._verify_unit_tests(file_paths)
        elif stage == VerificationStage.INTEGRATION:
            return self._verify_integration(file_paths)
        elif stage == VerificationStage.BEHAVIORAL:
            return self._verify_behavioral(task)
        else:
            return StageResult(
                stage=stage,
                passed=False,
                message=f"Unknown stage: {stage}"
            )

    def _verify_syntax(self, file_paths: List[str]) -> StageResult:
        """Verify syntax is valid (compile check)."""
        python_files = [f for f in file_paths if f.endswith('.py')]

        if not python_files:
            return StageResult(
                stage=VerificationStage.SYNTAX,
                passed=True,
                message="No Python files to check"
            )

        errors = []
        for file_path in python_files:
            full_path = self.workspace_root / file_path
            if not full_path.exists():
                continue

            try:
                result = subprocess.run(
                    ["python", "-m", "compileall", str(full_path)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    errors.append(f"{file_path}: {result.stderr}")

            except Exception as e:
                errors.append(f"{file_path}: {e}")

        if errors:
            return StageResult(
                stage=VerificationStage.SYNTAX,
                passed=False,
                message=f"Syntax errors in {len(errors)} file(s)",
                details={"errors": errors}
            )

        return StageResult(
            stage=VerificationStage.SYNTAX,
            passed=True,
            message=f"Syntax valid for {len(python_files)} file(s)"
        )

    def _verify_unit_tests(self, file_paths: List[str]) -> StageResult:
        """Verify unit tests pass."""
        # Find corresponding test files
        test_files = self._find_test_files(file_paths)

        if not test_files:
            return StageResult(
                stage=VerificationStage.UNIT,
                passed=True,
                message="No test files found (skipping)",
                details={"skipped": True}
            )

        # Run pytest on test files
        test_paths = " ".join(str(self.workspace_root / f) for f in test_files)

        try:
            result = subprocess.run(
                f"pytest {test_paths} -q --tb=short",
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return StageResult(
                    stage=VerificationStage.UNIT,
                    passed=True,
                    message=f"Unit tests passed ({len(test_files)} test file(s))",
                    details={"stdout": result.stdout[:500]}
                )
            else:
                return StageResult(
                    stage=VerificationStage.UNIT,
                    passed=False,
                    message=f"Unit tests failed (exit code: {result.returncode})",
                    details={
                        "stdout": result.stdout[:500],
                        "stderr": result.stderr[:500]
                    }
                )

        except subprocess.TimeoutExpired:
            return StageResult(
                stage=VerificationStage.UNIT,
                passed=False,
                message="Unit tests timed out (60s)"
            )
        except Exception as e:
            return StageResult(
                stage=VerificationStage.UNIT,
                passed=False,
                message=f"Failed to run unit tests: {e}"
            )

    def _verify_integration(self, file_paths: List[str]) -> StageResult:
        """Verify integration tests pass."""
        # Look for integration test directory
        integration_test_dir = self.workspace_root / "tests" / "integration"

        if not integration_test_dir.exists():
            return StageResult(
                stage=VerificationStage.INTEGRATION,
                passed=True,
                message="No integration tests found (skipping)",
                details={"skipped": True}
            )

        # Determine which integration tests to run based on changed files
        relevant_tests = self._find_relevant_integration_tests(file_paths)

        if not relevant_tests:
            return StageResult(
                stage=VerificationStage.INTEGRATION,
                passed=True,
                message="No relevant integration tests (skipping)",
                details={"skipped": True}
            )

        try:
            test_paths = " ".join(str(t) for t in relevant_tests)
            result = subprocess.run(
                f"pytest {test_paths} -q --tb=short",
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                return StageResult(
                    stage=VerificationStage.INTEGRATION,
                    passed=True,
                    message=f"Integration tests passed ({len(relevant_tests)} test(s))",
                    details={"stdout": result.stdout[:500]}
                )
            else:
                return StageResult(
                    stage=VerificationStage.INTEGRATION,
                    passed=False,
                    message=f"Integration tests failed (exit code: {result.returncode})",
                    details={
                        "stdout": result.stdout[:500],
                        "stderr": result.stderr[:500]
                    }
                )

        except subprocess.TimeoutExpired:
            return StageResult(
                stage=VerificationStage.INTEGRATION,
                passed=False,
                message="Integration tests timed out (120s)"
            )
        except Exception as e:
            return StageResult(
                stage=VerificationStage.INTEGRATION,
                passed=False,
                message=f"Failed to run integration tests: {e}"
            )

    def _verify_behavioral(self, task: Task) -> StageResult:
        """Verify behavioral/end-to-end tests pass."""
        # Check if there's a behavioral test command in task metadata
        behavioral_cmd = None

        if hasattr(task, 'metadata') and isinstance(task.metadata, dict):
            behavioral_cmd = task.metadata.get('behavioral_test_cmd')

        if not behavioral_cmd:
            return StageResult(
                stage=VerificationStage.BEHAVIORAL,
                passed=True,
                message="No behavioral test specified (skipping)",
                details={"skipped": True}
            )

        try:
            result = subprocess.run(
                behavioral_cmd,
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode == 0:
                return StageResult(
                    stage=VerificationStage.BEHAVIORAL,
                    passed=True,
                    message="Behavioral tests passed",
                    details={"stdout": result.stdout[:500]}
                )
            else:
                return StageResult(
                    stage=VerificationStage.BEHAVIORAL,
                    passed=False,
                    message=f"Behavioral tests failed (exit code: {result.returncode})",
                    details={
                        "stdout": result.stdout[:500],
                        "stderr": result.stderr[:500]
                    }
                )

        except subprocess.TimeoutExpired:
            return StageResult(
                stage=VerificationStage.BEHAVIORAL,
                passed=False,
                message="Behavioral tests timed out (180s)"
            )
        except Exception as e:
            return StageResult(
                stage=VerificationStage.BEHAVIORAL,
                passed=False,
                message=f"Failed to run behavioral tests: {e}"
            )

    def _extract_file_paths(self, task: Task) -> List[str]:
        """Extract file paths from task."""
        paths = []

        # Extract from task description
        file_pattern = r'[\w/\\.-]+\.(?:py|js|ts|jsx|tsx|java|cpp|c|h|go|rs|rb|php|md|txt|yaml|yml|json)\b'
        matches = re.findall(file_pattern, task.description)
        paths.extend(matches)

        # Extract from tool events
        if hasattr(task, 'tool_events') and task.tool_events:
            for event in task.tool_events:
                if isinstance(event, dict):
                    args = event.get('args', {})
                    for key in ['path', 'file_path', 'target']:
                        if key in args and isinstance(args[key], str):
                            paths.append(args[key])

        return list(set(paths))

    def _assess_risk(self, task: Task, file_paths: List[str]) -> RiskLevel:
        """Assess risk level based on task and files."""
        # Check file types
        code_files = [f for f in file_paths if f.endswith(('.py', '.js', '.ts', '.java', '.cpp', '.go', '.rs'))]
        doc_files = [f for f in file_paths if f.endswith(('.md', '.txt', '.rst'))]
        config_files = [f for f in file_paths if f.endswith(('.yaml', '.yml', '.json', '.toml', '.ini'))]

        # Risk heuristics
        if not code_files:
            # Only docs/config
            return RiskLevel.LOW

        if len(code_files) > 3:
            # Multi-file code change
            return RiskLevel.HIGH

        # Check for infrastructure/tooling changes
        infra_patterns = ['tool', 'execution', 'orchestrator', 'agent', 'llm', 'pipeline']
        task_desc_lower = task.description.lower()

        if any(pattern in task_desc_lower for pattern in infra_patterns):
            return RiskLevel.HIGH

        if any(pattern in ' '.join(code_files).lower() for pattern in infra_patterns):
            return RiskLevel.HIGH

        # Default to medium for code changes
        return RiskLevel.MEDIUM

    def _find_test_files(self, file_paths: List[str]) -> List[str]:
        """Find test files corresponding to source files."""
        test_files = []

        for file_path in file_paths:
            if file_path.startswith('test_') or '/test_' in file_path:
                # Already a test file
                test_files.append(file_path)
                continue

            # Look for corresponding test file
            path_obj = Path(file_path)
            stem = path_obj.stem

            # Common test file patterns
            patterns = [
                f"tests/test_{stem}.py",
                f"test/test_{stem}.py",
                f"tests/{stem}_test.py",
                f"{path_obj.parent}/test_{stem}.py"
            ]

            for pattern in patterns:
                test_path = self.workspace_root / pattern
                if test_path.exists():
                    test_files.append(pattern)
                    break

        return list(set(test_files))

    def _find_relevant_integration_tests(self, file_paths: List[str]) -> List[Path]:
        """Find integration tests relevant to changed files."""
        integration_dir = self.workspace_root / "tests" / "integration"

        if not integration_dir.exists():
            return []

        # Get all integration test files
        all_tests = list(integration_dir.glob("test_*.py"))

        # For now, run all integration tests
        # In the future, could use dependency analysis to be more selective
        return all_tests


def select_stages_for_task(
    task: Task,
    file_paths: List[str],
    risk_level: RiskLevel
) -> List[VerificationStage]:
    """
    Select verification stages based on risk level and task type.

    Args:
        task: The task being verified
        file_paths: Files modified by the task
        risk_level: Assessed risk level

    Returns:
        List of stages to run, in order
    """
    stages = []

    # Risk-based stage selection
    if risk_level == RiskLevel.LOW:
        # Docs-only: just syntax check
        stages.append(VerificationStage.SYNTAX)

    elif risk_level == RiskLevel.MEDIUM:
        # Code change: syntax + unit tests
        stages.append(VerificationStage.SYNTAX)
        stages.append(VerificationStage.UNIT)

    elif risk_level == RiskLevel.HIGH:
        # Infra/tooling: full pipeline
        stages.append(VerificationStage.SYNTAX)
        stages.append(VerificationStage.UNIT)
        stages.append(VerificationStage.INTEGRATION)

    # Add behavioral if specified in task
    if hasattr(task, 'metadata') and isinstance(task.metadata, dict):
        if task.metadata.get('behavioral_test_cmd'):
            if VerificationStage.BEHAVIORAL not in stages:
                stages.append(VerificationStage.BEHAVIORAL)

    return stages
