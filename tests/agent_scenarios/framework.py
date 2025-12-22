#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Framework for agent scenario testing.

This module provides infrastructure for capturing historical agent failure
modes as reproducible test scenarios.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

from rev.debug_logger import get_logger


logger = get_logger()


@dataclass
class AgentScenario:
    """Definition of an agent failure scenario to test.

    A scenario captures a specific failure mode that occurred historically
    and needs to be prevented from regressing.
    """
    name: str
    description: str
    initial_state: Dict[str, Any]  # Files, git state, etc.
    user_request: str
    expected_artifacts: List[str]  # Files that should exist after execution
    expected_dod_checks: List[str]  # DoD criteria that should pass
    known_failure_modes: List[str]  # What historically went wrong
    timeout_seconds: int = 300
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    """Result of running an agent scenario."""
    scenario_name: str
    passed: bool
    artifacts_created: List[str]
    artifacts_missing: List[str]
    dod_checks_passed: List[str]
    dod_checks_failed: List[str]
    failure_mode_avoided: bool
    rollback_successful: bool
    execution_time_seconds: float
    error_message: Optional[str] = None
    agent_output: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "scenario_name": self.scenario_name,
            "passed": self.passed,
            "artifacts_created": self.artifacts_created,
            "artifacts_missing": self.artifacts_missing,
            "dod_checks_passed": self.dod_checks_passed,
            "dod_checks_failed": self.dod_checks_failed,
            "failure_mode_avoided": self.failure_mode_avoided,
            "rollback_successful": self.rollback_successful,
            "execution_time_seconds": self.execution_time_seconds,
            "error_message": self.error_message,
        }


def setup_scenario(scenario: AgentScenario) -> Path:
    """Create a temporary workspace for the scenario.

    Args:
        scenario: The scenario to set up

    Returns:
        Path to the temporary workspace directory
    """
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp(prefix=f"rev_scenario_{scenario.name}_"))

    logger.info(f"Setting up scenario '{scenario.name}' in {temp_dir}")

    try:
        # Create initial file structure
        initial_files = scenario.initial_state.get("files", {})
        for file_path, content in initial_files.items():
            full_path = temp_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            if isinstance(content, str):
                full_path.write_text(content, encoding="utf-8")
            elif isinstance(content, bytes):
                full_path.write_bytes(content)
            else:
                full_path.write_text(str(content), encoding="utf-8")

        # Initialize git repository if needed
        if scenario.initial_state.get("git_enabled", True):
            subprocess.run(
                ["git", "init"],
                cwd=temp_dir,
                capture_output=True,
                check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@rev.dev"],
                cwd=temp_dir,
                capture_output=True,
                check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "REV Test"],
                cwd=temp_dir,
                capture_output=True,
                check=True
            )

            # Add and commit initial files
            if initial_files:
                subprocess.run(
                    ["git", "add", "."],
                    cwd=temp_dir,
                    capture_output=True,
                    check=True
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial state"],
                    cwd=temp_dir,
                    capture_output=True,
                    check=True
                )

        logger.info(f"Scenario setup complete: {temp_dir}")
        return temp_dir

    except Exception as e:
        logger.error(f"Failed to setup scenario '{scenario.name}': {e}")
        # Cleanup on failure
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def run_scenario(scenario: AgentScenario, workspace: Path) -> ScenarioResult:
    """Execute the agent on the scenario and collect results.

    Args:
        scenario: The scenario to run
        workspace: The workspace directory

    Returns:
        ScenarioResult with execution details
    """
    start_time = time.time()

    logger.info(f"Running scenario '{scenario.name}'")

    # Prepare result
    result = ScenarioResult(
        scenario_name=scenario.name,
        passed=False,
        artifacts_created=[],
        artifacts_missing=[],
        dod_checks_passed=[],
        dod_checks_failed=[],
        failure_mode_avoided=False,
        rollback_successful=False,
        execution_time_seconds=0.0,
    )

    try:
        # Run REV on the scenario
        # Note: This is a simplified version. In practice, you'd want to
        # call the orchestrator directly rather than subprocess
        cmd = [
            "python", "-m", "rev.cli",
            scenario.user_request,
            "--no-interactive",
        ]

        process = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            timeout=scenario.timeout_seconds,
            text=True,
        )

        result.agent_output = process.stdout + "\n" + process.stderr

        # Check for artifacts
        for artifact_path in scenario.expected_artifacts:
            full_path = workspace / artifact_path
            if full_path.exists():
                result.artifacts_created.append(artifact_path)
            else:
                result.artifacts_missing.append(artifact_path)

        # Check DoD criteria
        for dod_check in scenario.expected_dod_checks:
            if check_dod_criterion(workspace, dod_check, result.agent_output):
                result.dod_checks_passed.append(dod_check)
            else:
                result.dod_checks_failed.append(dod_check)

        # Check if known failure modes were avoided
        result.failure_mode_avoided = check_failure_modes_avoided(
            scenario.known_failure_modes,
            workspace,
            result.agent_output
        )

        # Determine overall pass/fail
        result.passed = (
            len(result.artifacts_missing) == 0 and
            len(result.dod_checks_failed) == 0 and
            result.failure_mode_avoided
        )

        logger.info(f"Scenario '{scenario.name}' {'PASSED' if result.passed else 'FAILED'}")

    except subprocess.TimeoutExpired:
        result.error_message = f"Scenario timed out after {scenario.timeout_seconds}s"
        logger.error(result.error_message)
    except Exception as e:
        result.error_message = f"Scenario execution failed: {e}"
        logger.error(result.error_message)
    finally:
        result.execution_time_seconds = time.time() - start_time

    return result


def check_dod_criterion(workspace: Path, criterion: str, agent_output: str) -> bool:
    """Check if a Definition of Done criterion is satisfied.

    Args:
        workspace: Workspace directory
        criterion: DoD criterion to check
        agent_output: Agent output text

    Returns:
        True if criterion is satisfied
    """
    criterion_lower = criterion.lower()

    # Tests passed
    if "tests pass" in criterion_lower or "all tests green" in criterion_lower:
        # Check if tests were run and passed
        return "passed" in agent_output.lower() and "failed" not in agent_output.lower()

    # No errors
    if "no errors" in criterion_lower or "error-free" in criterion_lower:
        return "error" not in agent_output.lower()

    # File exists
    if "file exists:" in criterion_lower:
        file_path = criterion.split("file exists:")[-1].strip()
        return (workspace / file_path).exists()

    # Git committed
    if "git commit" in criterion_lower or "changes committed" in criterion_lower:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                cwd=workspace,
                capture_output=True,
                text=True
            )
            return result.returncode == 0 and len(result.stdout.strip()) > 0
        except Exception:
            return False

    # Contains text
    if "output contains:" in criterion_lower:
        expected_text = criterion.split("output contains:")[-1].strip()
        return expected_text in agent_output

    # Default: assume failed if we don't recognize the criterion
    logger.warning(f"Unknown DoD criterion: {criterion}")
    return False


def check_failure_modes_avoided(
    failure_modes: List[str],
    workspace: Path,
    agent_output: str
) -> bool:
    """Check if known failure modes were avoided.

    Args:
        failure_modes: List of failure mode descriptions
        workspace: Workspace directory
        agent_output: Agent output text

    Returns:
        True if all failure modes were avoided
    """
    for failure_mode in failure_modes:
        failure_lower = failure_mode.lower()

        # Check for "reports done but no changes"
        if "reports done but no changes" in failure_lower:
            # Check if agent claimed success but git shows no changes
            if "task_complete" in agent_output.lower() or "done" in agent_output.lower():
                try:
                    result = subprocess.run(
                        ["git", "diff", "--name-only"],
                        cwd=workspace,
                        capture_output=True,
                        text=True
                    )
                    # If agent said done but no files changed, failure mode occurred
                    if result.returncode == 0 and len(result.stdout.strip()) == 0:
                        logger.warning(f"Failure mode detected: {failure_mode}")
                        return False
                except Exception:
                    pass

        # Check for "empty tool result ignored"
        if "empty" in failure_lower and "tool" in failure_lower and "ignored" in failure_lower:
            # Check if agent continued after empty tool results
            if "error" in agent_output.lower() and "empty" in agent_output.lower():
                if "continuing" in agent_output.lower() or "proceeding" in agent_output.lower():
                    logger.warning(f"Failure mode detected: {failure_mode}")
                    return False

        # Check for "test failure ignored"
        if "test" in failure_lower and "fail" in failure_lower and "ignored" in failure_lower:
            if "failed" in agent_output.lower() and "task_complete" in agent_output.lower():
                # Agent claimed completion despite test failures
                logger.warning(f"Failure mode detected: {failure_mode}")
                return False

        # Check for "infinite retry loop"
        if "infinite" in failure_lower and ("retry" in failure_lower or "loop" in failure_lower):
            # Count repeated tool calls in output
            # This is a heuristic - may need refinement
            if agent_output.count("retrying") > 10 or agent_output.count("attempting") > 10:
                logger.warning(f"Failure mode detected: {failure_mode}")
                return False

    return True


def verify_scenario(result: ScenarioResult, scenario: AgentScenario) -> bool:
    """Verify that scenario result meets expectations.

    Args:
        result: The scenario result to verify
        scenario: The original scenario definition

    Returns:
        True if scenario passed verification
    """
    if not result.passed:
        logger.warning(f"Scenario '{scenario.name}' verification FAILED")

        if result.artifacts_missing:
            logger.warning(f"  Missing artifacts: {result.artifacts_missing}")

        if result.dod_checks_failed:
            logger.warning(f"  Failed DoD checks: {result.dod_checks_failed}")

        if not result.failure_mode_avoided:
            logger.warning(f"  Known failure mode occurred")

        if result.error_message:
            logger.warning(f"  Error: {result.error_message}")

        return False

    logger.info(f"Scenario '{scenario.name}' verification PASSED")
    return True


def cleanup_scenario(workspace: Path):
    """Clean up scenario workspace.

    Args:
        workspace: The workspace directory to clean up
    """
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
            logger.info(f"Cleaned up workspace: {workspace}")
    except Exception as e:
        logger.warning(f"Failed to cleanup workspace {workspace}: {e}")


def save_scenario_result(result: ScenarioResult, output_dir: Path):
    """Save scenario result to file.

    Args:
        result: The scenario result to save
        output_dir: Directory to save results
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    result_file = output_dir / f"{result.scenario_name}_result.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    logger.info(f"Saved scenario result to {result_file}")
