"""Uncertainty detection system for Rev.

Detects when Rev is uncertain during planning, execution, or verification
and should request user guidance instead of retrying blindly.
"""

from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import re

from rev.models.task import Task
from rev.execution.quick_verify import VerificationResult


# Uncertainty weights for scoring
UNCERTAINTY_WEIGHTS = {
    "planner_hesitation": 2,
    "multiple_files": 3,
    "repeated_failure": 5,
    "no_tool_calls": 4,
    "verification_inconclusive": 3,
    "missing_files": 2,
    "timeout_unclear": 2,
    "conflicting_signals": 3,
    "no_progress": 4,
}


class UncertaintySignal:
    """Represents a detected uncertainty signal."""

    def __init__(self, signal_type: str, reason: str, score: int, context: Optional[Dict[str, Any]] = None):
        self.signal_type = signal_type
        self.reason = reason
        self.score = score
        self.context = context or {}

    def __repr__(self):
        return f"UncertaintySignal({self.signal_type}, score={self.score}, reason={self.reason[:50]})"


def _detect_planning_uncertainty(
    task_description: str,
    llm_response: Optional[str] = None,
    task: Optional[Task] = None
) -> List[UncertaintySignal]:
    """Detect uncertainty during task planning phase.

    Args:
        task_description: The task description being planned
        llm_response: Optional LLM response text from planner
        task: Optional Task object

    Returns:
        List of uncertainty signals detected
    """
    signals = []

    # Check for hesitation markers in LLM response
    if llm_response:
        hesitation_markers = [
            "could try", "might work", "possibly", "not sure",
            "unclear", "ambiguous", "multiple ways", "depends on",
            "may need to", "should probably", "it's unclear",
            "not certain", "hard to say", "difficult to determine"
        ]

        response_lower = llm_response.lower()
        found_markers = [m for m in hesitation_markers if m in response_lower]

        if found_markers:
            signals.append(UncertaintySignal(
                signal_type="planner_hesitation",
                reason=f"Planner expressed uncertainty: {', '.join(found_markers[:3])}",
                score=UNCERTAINTY_WEIGHTS["planner_hesitation"],
                context={"markers": found_markers}
            ))

    # Check for ambiguous file references
    if task and task.action_type and task.action_type.lower() in ("edit", "refactor", "add"):
        # Extract potential file paths from description
        file_patterns = [
            r'\b(?:src|lib|tests?|components?)/[\w/.-]+\.\w+',
            r'\b[\w-]+\.(?:ts|js|py|tsx|jsx|go|rs|java)\b',
        ]

        potential_files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, task_description, re.IGNORECASE)
            potential_files.extend(matches)

        # If multiple distinct file paths mentioned, might be ambiguous
        unique_files = list(set(potential_files))
        if len(unique_files) > 1:
            signals.append(UncertaintySignal(
                signal_type="multiple_files",
                reason=f"Multiple potential target files: {', '.join(unique_files[:3])}",
                score=UNCERTAINTY_WEIGHTS["multiple_files"],
                context={"files": unique_files}
            ))

    return signals


def _detect_execution_uncertainty(
    task: Task,
    retry_count: int,
    last_error: Optional[str] = None,
    previous_errors: Optional[List[str]] = None
) -> List[UncertaintySignal]:
    """Detect uncertainty during task execution phase.

    Args:
        task: The task being executed
        retry_count: Number of retry attempts so far
        last_error: Most recent error message
        previous_errors: List of previous error messages

    Returns:
        List of uncertainty signals detected
    """
    signals = []

    # Repeated failures with identical error
    if retry_count >= 3 and last_error:
        # Check if error is identical to previous attempts
        if previous_errors:
            identical_count = sum(1 for err in previous_errors if err == last_error)
            if identical_count >= 2:
                signals.append(UncertaintySignal(
                    signal_type="repeated_failure",
                    reason=f"Task failed {retry_count} times with identical error: {last_error[:100]}",
                    score=UNCERTAINTY_WEIGHTS["repeated_failure"],
                    context={"retry_count": retry_count, "error": last_error}
                ))
        else:
            # Assume repeated if retry_count >= 3
            signals.append(UncertaintySignal(
                signal_type="repeated_failure",
                reason=f"Task failed {retry_count} times: {last_error[:100]}",
                score=UNCERTAINTY_WEIGHTS["repeated_failure"],
                context={"retry_count": retry_count, "error": last_error}
            ))

    # No tool calls (agent returning text instead of using tools)
    if hasattr(task, 'tool_events'):
        tool_events = getattr(task, 'tool_events', None) or []
        if retry_count > 0 and len(tool_events) == 0:
            signals.append(UncertaintySignal(
                signal_type="no_tool_calls",
                reason="Agent not executing tools, only returning text responses",
                score=UNCERTAINTY_WEIGHTS["no_tool_calls"],
                context={"retry_count": retry_count}
            ))

    # No progress (same error across multiple attempts)
    if retry_count >= 2 and previous_errors and len(set(previous_errors)) == 1:
        signals.append(UncertaintySignal(
            signal_type="no_progress",
            reason="No progress - same error on every attempt",
            score=UNCERTAINTY_WEIGHTS["no_progress"],
            context={"attempts": retry_count + 1}
        ))

    return signals


def _detect_verification_uncertainty(
    result: VerificationResult,
    task: Optional[Task] = None
) -> List[UncertaintySignal]:
    """Detect uncertainty during verification phase.

    Args:
        result: Verification result to analyze
        task: Optional task being verified

    Returns:
        List of uncertainty signals detected
    """
    signals = []

    # Check for inconclusive verification
    if hasattr(result, 'inconclusive') and result.inconclusive:
        signals.append(UncertaintySignal(
            signal_type="verification_inconclusive",
            reason="Verification inconclusive - cannot determine if task succeeded",
            score=UNCERTAINTY_WEIGHTS["verification_inconclusive"],
            context={"message": result.message}
        ))

    # Timeout with unclear cause
    if result.details and isinstance(result.details, dict):
        details = result.details

        # Check for timeout without clear diagnosis
        if details.get("rc") == -1 or "timeout" in (result.message or "").lower():
            timeout_diag = details.get("timeout_diagnosis")
            if not timeout_diag or not timeout_diag.get("is_watch_mode"):
                # Timeout but unclear why
                signals.append(UncertaintySignal(
                    signal_type="timeout_unclear",
                    reason="Command timed out but cause is unclear",
                    score=UNCERTAINTY_WEIGHTS["timeout_unclear"],
                    context={"message": result.message}
                ))

        # Check for conflicting signals (tests pass but other validations fail)
        if result.passed and details.get("validation"):
            validation = details["validation"]
            if isinstance(validation, dict):
                # Check if validation has failures
                for key, val in validation.items():
                    if isinstance(val, dict) and val.get("rc") not in (None, 0):
                        signals.append(UncertaintySignal(
                            signal_type="conflicting_signals",
                            reason=f"Tests pass but {key} validation failed",
                            score=UNCERTAINTY_WEIGHTS["conflicting_signals"],
                            context={"validation": key}
                        ))
                        break

    return signals


def _detect_missing_files_uncertainty(
    task: Task,
    file_paths: Optional[List[str]] = None
) -> List[UncertaintySignal]:
    """Detect uncertainty due to missing or ambiguous files.

    Args:
        task: The task being analyzed
        file_paths: Optional list of file paths to check

    Returns:
        List of uncertainty signals detected
    """
    signals = []

    if not file_paths:
        # Try to extract from task description
        desc = task.description or ""
        file_patterns = [
            r'\b(?:src|lib|tests?|components?)/[\w/.-]+\.\w+',
            r'\b[\w-]+\.(?:ts|js|py|tsx|jsx|go|rs|java)\b',
        ]

        file_paths = []
        for pattern in file_patterns:
            matches = re.findall(pattern, desc, re.IGNORECASE)
            file_paths.extend(matches)

    if file_paths:
        # Check if files exist
        from rev import config
        root = config.ROOT or Path.cwd()

        missing_files = []
        for file_path in file_paths:
            full_path = root / file_path
            if not full_path.exists():
                missing_files.append(file_path)

        if missing_files:
            signals.append(UncertaintySignal(
                signal_type="missing_files",
                reason=f"Referenced files do not exist: {', '.join(missing_files[:3])}",
                score=UNCERTAINTY_WEIGHTS["missing_files"],
                context={"missing_files": missing_files}
            ))

    return signals


def detect_uncertainty(
    task: Task,
    retry_count: int = 0,
    verification_result: Optional[VerificationResult] = None,
    llm_response: Optional[str] = None,
    previous_errors: Optional[List[str]] = None
) -> Tuple[int, List[UncertaintySignal]]:
    """Comprehensive uncertainty detection across all phases.

    Args:
        task: Task being executed
        retry_count: Number of retry attempts
        verification_result: Optional verification result
        llm_response: Optional LLM response from planning
        previous_errors: Optional list of previous error messages

    Returns:
        Tuple of (total_uncertainty_score, list_of_signals)
    """
    all_signals = []

    # Planning uncertainty (on first attempt)
    if retry_count == 0:
        planning_signals = _detect_planning_uncertainty(
            task.description or "",
            llm_response=llm_response,
            task=task
        )
        all_signals.extend(planning_signals)

    # Execution uncertainty
    if retry_count > 0:
        execution_signals = _detect_execution_uncertainty(
            task,
            retry_count,
            last_error=task.error,
            previous_errors=previous_errors
        )
        all_signals.extend(execution_signals)

    # Verification uncertainty
    if verification_result:
        verification_signals = _detect_verification_uncertainty(
            verification_result,
            task=task
        )
        all_signals.extend(verification_signals)

    # Missing files uncertainty
    missing_signals = _detect_missing_files_uncertainty(task)
    all_signals.extend(missing_signals)

    # Calculate total score
    total_score = sum(signal.score for signal in all_signals)

    # Reduce uncertainty score for research/read tasks (they're exploratory by nature)
    research_action_types = {"read", "analyze", "research", "investigate", "general", "verify"}
    task_action = (task.action_type or "").lower()
    if task_action in research_action_types:
        # Reduce score by 40% for research tasks
        total_score = int(total_score * 0.6)
        # Also add a note about research context
        if all_signals:
            all_signals.append(UncertaintySignal(
                signal_type="research_context",
                reason="Research task - uncertainty scores reduced",
                score=0,
                context={"action_type": task_action}
            ))

    return total_score, all_signals


def format_uncertainty_reasons(signals: List[UncertaintySignal]) -> str:
    """Format uncertainty signals into human-readable string.

    Args:
        signals: List of uncertainty signals

    Returns:
        Formatted string describing all uncertainty reasons
    """
    if not signals:
        return "Unknown uncertainty"

    reasons = []
    for signal in signals:
        reasons.append(f"• {signal.reason}")

    return "\n".join(reasons)


def should_request_guidance(
    uncertainty_score: int,
    threshold: int = 5,
    auto_skip_threshold: int = 10
) -> Tuple[bool, str]:
    """Determine if user guidance should be requested.

    Args:
        uncertainty_score: Calculated uncertainty score
        threshold: Score threshold to trigger guidance request
        auto_skip_threshold: Score to auto-skip task without asking

    Returns:
        Tuple of (should_request, action)
        action is "request" or "auto_skip"
    """
    if uncertainty_score >= auto_skip_threshold:
        return True, "auto_skip"
    elif uncertainty_score >= threshold:
        return True, "request"
    else:
        return False, "continue"
