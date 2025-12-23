"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.

Implements Resource-Aware Optimization pattern to track and enforce budgets.

CORE PRINCIPLE - TEST-DRIVEN DEVELOPMENT (TDD):
REV follows TDD as a fundamental practice. All feature development and bug fixes
should follow the Red-Green-Refactor cycle:
1. RED: Write a failing test that specifies desired behavior
2. GREEN: Implement minimal code to make the test pass
3. REFACTOR: Improve code while keeping tests green

The orchestrator ensures that test tasks precede implementation tasks in plans,
and that validation is performed after each implementation step.
"""

import os
import json
import time
import traceback
from typing import Dict, Any, List, Optional, Literal, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

from rev import config
from rev.models.task import ExecutionPlan, TaskStatus, Task
from rev.execution.planner import planning_mode
from rev.execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from rev.execution.validator import (
    validate_execution,
    ValidationStatus,
    ValidationReport,
    format_validation_feedback_for_llm,
)
from rev.execution.researcher import research_codebase, ResearchFindings
from rev.execution.learner import LearningAgent, display_learning_suggestions
from rev.execution.executor import execution_mode, concurrent_execution_mode, fix_validation_failures
from rev.execution.state_manager import StateManager
from rev.execution.prompt_optimizer import optimize_prompt_if_needed
from rev.execution.quick_verify import verify_task_execution, VerificationResult
from rev.execution.anchoring_scorer import AnchoringScorer, AnchoringDecision
from rev.tools.registry import get_available_tools, get_repo_context
from rev.debug_logger import DebugLogger
from rev.config import (
    MAX_PLAN_TASKS,
    MAX_STEPS_PER_RUN,
    MAX_LLM_TOKENS_PER_RUN,
    MAX_WALLCLOCK_SECONDS,
    RESEARCH_DEPTH_DEFAULT,
    VALIDATION_MODE_DEFAULT,
    MAX_ORCHESTRATOR_RETRIES,
    MAX_PLAN_REGEN_RETRIES,
    MAX_ADAPTIVE_REPLANS,
    MAX_VALIDATION_RETRIES,
)
from rev.llm.client import get_token_usage, ollama_chat
from rev.core.context import RevContext, ResourceBudget
from rev.execution.session import SessionTracker
from rev.core.shared_enums import AgentPhase
from rev.core.agent_registry import AgentRegistry
from rev.cache import clear_analysis_caches
import re
from rev.retrieval.context_builder import ContextBuilder
from rev.memory.project_memory import ensure_project_memory_file, maybe_record_known_failure_from_error
from rev.tools.workspace_resolver import resolve_workspace_path
from rev.core.text_tool_shim import maybe_execute_tool_call_from_text
from rev.agents.subagent_io import build_subagent_output
from rev.execution.action_normalizer import normalize_action_type
from rev.terminal.formatting import colorize, Colors, Symbols
from difflib import SequenceMatcher

# Global reference to the currently active context for real-time feedback
_active_context: Optional[RevContext] = None

def push_user_feedback(feedback: str) -> bool:
    """Push user feedback to the currently active orchestrator context.
    
    Returns True if feedback was successfully delivered, False otherwise.
    """
    global _active_context
    if _active_context:
        _active_context.add_user_feedback(feedback)
        return True
    return False


def _format_verification_feedback(result: VerificationResult) -> str:
    """Format verification result for LLM feedback."""
    feedback = f"VERIFICATION FAILED: {result.message or 'Check environment.'}"
    
    details = result.details or {}
    
    # Extract validation command outputs if present (from quick_verify.py)
    validation = details.get("validation") or details.get("strict")
    if isinstance(validation, dict):
        feedback += "\n\nDETAILED OUTPUTS:"
        for label, res in validation.items():
            if not isinstance(res, dict):
                continue
            rc = res.get("rc")
            if rc is not None and rc != 0:
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()
                feedback += f"\n- {label} (rc={rc})"
                if stderr:
                    feedback += "\n  stderr: " + " ".join(stderr.splitlines()[-3:]) # Last 3 lines
                elif stdout:
                    feedback += "\n  stdout: " + " ".join(stdout.splitlines()[-3:])
                else:
                    feedback += "\n(No stdout or stderr output captured from command)"
    
    # Extract debug info if present
    if "debug" in details:
        feedback += f"\n\nDebug Info:\n{json.dumps(details['debug'], indent=2)}"
        
    return feedback


def _extract_file_path_from_description(desc: str) -> Optional[str]:
    """Extract a file path from a task description for read tracking.

    Returns the first path-like string found, or None.
    """
    if not desc:
        return None

    # Match common path patterns
    # Support most common source, config, and data extensions
    ext = r"(py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1)"
    patterns = [
        rf'`([^`]+\.{ext})`',  # backticked paths
        rf'"([^"]+\.{ext})"',  # quoted paths
        rf'\b([A-Za-z]:\\[^\s]+\.{ext})\b',  # Windows absolute
        rf'\b(/[^\s]+\.{ext})\b',  # Unix absolute
        rf'\b([\w./\\-]+\.{ext})\b',  # relative paths
    ]

    for pattern in patterns:
        match = re.search(pattern, desc, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def _extract_line_range_from_description(desc: str) -> Optional[str]:
    """Extract a line range from a task description (e.g., 'lines 95-150').

    Returns the line range string or None.
    """
    if not desc:
        return None

    patterns = [
        r'lines?\s+(\d+)\s*[-–to]+\s*(\d+)',  # "lines 95-150" or "line 95 to 150"
        r'lines?\s+(\d+)',  # "line 95" (single line)
    ]

    for pattern in patterns:
        match = re.search(pattern, desc, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def _compute_task_similarity(desc1: str, desc2: str) -> float:
    """Compute semantic similarity between two task descriptions.

    Uses SequenceMatcher ratio plus keyword overlap.
    Returns a score between 0.0 and 1.0.
    """
    if not desc1 or not desc2:
        return 0.0

    # Normalize descriptions
    d1 = desc1.strip().lower()
    d2 = desc2.strip().lower()

    # Direct sequence matching
    seq_ratio = SequenceMatcher(None, d1, d2).ratio()

    # Check for same file path
    file1 = _extract_file_path_from_description(desc1)
    file2 = _extract_file_path_from_description(desc2)
    same_file = 0.0
    if file1 and file2:
        # Normalize paths
        f1 = file1.replace('\\', '/').lower()
        f2 = file2.replace('\\', '/').lower()
        if f1 == f2 or f1.endswith(f2) or f2.endswith(f1):
            same_file = 0.3  # Bonus for same file

    # Check for same line range
    lines1 = _extract_line_range_from_description(desc1)
    lines2 = _extract_line_range_from_description(desc2)
    same_lines = 0.0
    if lines1 and lines2 and lines1.lower() == lines2.lower():
        same_lines = 0.2  # Bonus for same line range

    # Keywords that suggest similar intent
    intent_keywords = [
        'inspect', 'examine', 'read', 'analyze', 'review', 'check', 'look', 'find',
        'identify', 'understand', 'investigate', 'explore', 'verbatim', 'exact'
    ]

    kw1 = set(word for word in d1.split() if word in intent_keywords)
    kw2 = set(word for word in d2.split() if word in intent_keywords)

    keyword_overlap = 0.0
    if kw1 and kw2:
        overlap = len(kw1 & kw2) / max(len(kw1 | kw2), 1)
        keyword_overlap = overlap * 0.2  # Up to 0.2 bonus

    # Combine scores, capped at 1.0
    return min(1.0, seq_ratio + same_file + same_lines + keyword_overlap)


def _is_semantically_duplicate_task(
    new_desc: str,
    new_action: str,
    completed_tasks: List[str],
    threshold: float = 0.7
) -> bool:
    """Check if a new task is semantically similar to already-completed tasks.

    Args:
        new_desc: Description of the new task
        new_action: Action type of the new task
        completed_tasks: List of completed task log entries
        threshold: Similarity threshold (0.7 = 70% similar)

    Returns:
        True if the task is considered a duplicate
    """
    if not completed_tasks:
        return False

    new_action_lower = (new_action or '').lower()

    # Only check for duplication on read-like actions
    if new_action_lower not in {'read', 'analyze', 'research', 'investigate', 'review'}:
        return False

    similar_count = 0
    for log_entry in completed_tasks:
        # Parse the log entry to extract action type and description
        # Format: [STATUS] description | Output: ...
        match = re.match(r'\[(\w+)\]\s*(.+?)(?:\s*\|.*)?$', log_entry)
        if not match:
            continue

        status = match.group(1).upper()
        desc = match.group(2).strip()

        # Only compare with completed read-like tasks
        if status != 'COMPLETED':
            continue

        # Check for read-like keywords in the description
        desc_lower = desc.lower()
        is_read_like = any(kw in desc_lower for kw in ['read', 'inspect', 'examine', 'analyze'])
        if not is_read_like:
            continue

        similarity = _compute_task_similarity(new_desc, desc)
        if similarity >= threshold:
            similar_count += 1

    # If we found 2+ similar completed tasks, this is a duplicate
    return similar_count >= 2


def _count_file_reads(file_path: str, completed_tasks: List) -> int:
    """Count how many times a file has been read in completed tasks.

    P0-1 Fix: Now uses actual tool_events instead of keyword matching in descriptions.

    Args:
        file_path: The file path to check
        completed_tasks: List of completed Task objects or task log entries (backward compatible)

    Returns:
        Number of times this file was read
    """
    if not file_path or not completed_tasks:
        return 0

    # Normalize the target path
    target = file_path.replace('\\', '/').lower()
    count = 0

    # File reading tools to check for
    FILE_READING_TOOLS = {'read_file', 'read_file_lines', 'search_code', 'list_dir', 'analyze_code_context'}

    for item in completed_tasks:
        # NEW: Check if item is a Task object with tool_events
        if hasattr(item, 'tool_events') and hasattr(item, 'status'):
            # Only count completed tasks
            if hasattr(item.status, 'value'):
                if item.status.value != 'completed':
                    continue
            elif str(item.status).lower() != 'completed':
                continue

            # Check tool_events for file reading operations
            if item.tool_events:
                for event in item.tool_events:
                    tool_name = event.get('tool', '').lower()
                    if tool_name not in FILE_READING_TOOLS:
                        continue

                    # Extract file path from tool arguments
                    args = event.get('args', {})
                    if not isinstance(args, dict):
                        continue

                    # Check various argument names that contain file paths
                    event_file = args.get('file_path') or args.get('path') or args.get('pattern')
                    if event_file:
                        event_normalized = str(event_file).replace('\\', '/').lower()
                        if target == event_normalized or target.endswith(event_normalized) or event_normalized.endswith(target):
                            count += 1

        # BACKWARD COMPATIBLE: Handle string log entries (old format)
        elif isinstance(item, str):
            # Only count completed read-like tasks
            if not item.startswith('[COMPLETED]'):
                continue

            desc_lower = item.lower()
            if not any(kw in desc_lower for kw in ['read', 'inspect', 'examine', 'analyze']):
                continue

            # Extract file path from the log entry
            entry_file = _extract_file_path_from_description(item)
            if entry_file:
                entry_normalized = entry_file.replace('\\', '/').lower()
                if target == entry_normalized or target.endswith(entry_normalized) or entry_normalized.endswith(target):
                    count += 1

    return count


def _check_syntax_error_in_verification(verification_result) -> bool:
    """Check if a verification failure is due to syntax errors.

    Returns True if the failure is caused by syntax errors (F821, E999, etc.)
    that would leave the code in a broken state.
    """
    if not verification_result or not hasattr(verification_result, 'details'):
        return False

    details_str = str(verification_result.details).lower()
    message_str = str(verification_result.message).lower()

    # Check for syntax error indicators
    syntax_indicators = [
        'f821',  # Undefined name
        'e999',  # SyntaxError
        'undefined name',
        'syntaxerror',
        'name error',
        'compilation failed',
        'import error',
        'module not found',
    ]

    combined = f"{details_str} {message_str}"
    return any(indicator in combined for indicator in syntax_indicators)


def _create_syntax_repair_task(failed_task: "Task", verification_result) -> "Task":
    """Create a focused syntax repair task for the LLM.

    Args:
        failed_task: The task that failed with syntax errors
        verification_result: The verification result containing error details

    Returns:
        A new Task focused on fixing the syntax errors
    """
    from rev.models.task import Task

    # Extract file paths from failed task
    affected_files = set()
    if hasattr(failed_task, 'tool_events') and failed_task.tool_events:
        for event in failed_task.tool_events:
            args = event.get('args', {})
            if isinstance(args, dict):
                for key in ['path', 'file_path', 'target', 'source']:
                    if key in args and isinstance(args[key], str):
                        affected_files.add(args[key])

    files_str = ', '.join(affected_files) if affected_files else "the modified file(s)"

    # Extract specific error details from verification result
    error_details = ""
    if hasattr(verification_result, 'details') and verification_result.details:
        details = verification_result.details
        if isinstance(details, dict):
            # Look for ruff or compileall output
            for key in ['ruff', 'compileall', 'strict']:
                if key in details:
                    val = details[key]
                    if isinstance(val, dict) and 'stdout' in val:
                        error_details = val['stdout'][:500]  # Limit to 500 chars
                        break

    # Create focused repair task description
    description = (
        f"Fix the syntax errors in {files_str}. "
        f"CRITICAL: The code currently has undefined names or syntax errors that prevent it from running. "
        f"You MUST fix ALL syntax errors - missing imports, undefined variables, etc. "
    )

    if error_details:
        description += f"\n\nError details:\n{error_details}"

    description += (
        "\n\nIMPORTANT - Error Scope:\n"
        "- Only fix syntax/import errors in the code YOU modified\n"
        "- If errors appear in unrelated parts of the file, IGNORE them (they are pre-existing)\n"
        "- Focus ONLY on making YOUR specific changes syntactically valid\n\n"
        "Focus ONLY on fixing syntax/import errors in your changes. "
        "Do not make other changes. Ensure all imports are present and all names are defined."
    )

    return Task(
        description=description,
        action_type="fix"
    )


def _attempt_git_revert_for_syntax_errors(task: "Task") -> list[str]:
    """Attempt to revert files affected by a task using git checkout.

    Returns list of successfully reverted file paths, or empty list if revert failed.
    """
    from rev.tools.registry import execute_tool

    # Extract file paths from task events
    files_to_revert = set()
    if hasattr(task, 'tool_events') and task.tool_events:
        for event in task.tool_events:
            # Check for file paths in tool arguments
            args = event.get('args', {})
            if isinstance(args, dict):
                for key in ['path', 'file_path', 'target', 'source']:
                    if key in args and isinstance(args[key], str):
                        files_to_revert.add(args[key])

    if not files_to_revert:
        return []

    reverted = []
    for file_path in files_to_revert:
        try:
            # Use git checkout to revert the file
            result = execute_tool("run_cmd", {
                "cmd": f"git checkout HEAD -- {file_path}",
                "timeout": 10
            })
            if result and "error" not in str(result).lower():
                reverted.append(file_path)
        except Exception:
            # Revert failed for this file, continue with others
            pass

    return reverted


def _check_goal_likely_achieved(user_request: str, completed_tasks_log: List[str]) -> bool:
    """Check if the original goal appears to have been achieved based on completed tasks.

    Looks for evidence of successful tool executions that match the user request intent.
    Returns True if goal appears achieved, False otherwise.
    """
    if not completed_tasks_log:
        return False

    request_lower = user_request.lower()

    # Key patterns that indicate goal-completing tool executions
    goal_indicators = []

    # For splitting/breaking out files
    if any(kw in request_lower for kw in ['split', 'break out', 'separate', 'extract']):
        goal_indicators.extend([
            'split_python_module_classes',
            '"classes_split"',
            '"created_files"',
            'classes_split',
        ])

    # For refactoring
    if 'refactor' in request_lower:
        goal_indicators.extend([
            'refactor',
            'write_file',
            'replace_in_file',
        ])

    # For creating directories/packages
    if any(kw in request_lower for kw in ['package', 'directory', 'create']):
        goal_indicators.extend([
            'create_directory',
            '__init__.py',
            'package_init',
        ])

    if not goal_indicators:
        # Can't determine goal type, don't force completion
        return False

    # Check completed tasks for evidence of goal achievement
    completed_count = 0
    goal_evidence = 0

    for log_entry in completed_tasks_log:
        if not log_entry.startswith('[COMPLETED]'):
            continue
        completed_count += 1

        log_lower = log_entry.lower()
        for indicator in goal_indicators:
            if indicator.lower() in log_lower:
                goal_evidence += 1
                break

    # If we have completed tasks with goal evidence, assume goal is achieved
    # Require at least one completed task with goal evidence
    return goal_evidence >= 1 and completed_count >= 1


from rev.tools.workspace_resolver import normalize_path, normalize_to_workspace_relative, WorkspacePathError


def _append_task_tool_event(task: Task, result_payload: Any) -> None:
    """Best-effort: extract tool execution evidence and attach to task.tool_events.

    Sub-agents often return standardized JSON (see rev/agents/subagent_io.py).
    Persisting tool evidence on the Task lets quick_verify validate what actually ran
    instead of guessing from task text or global "last tool call" state.
    """
    payload: Optional[Dict[str, Any]] = None
    if isinstance(result_payload, dict):
        payload = result_payload
    elif isinstance(result_payload, str):
        try:
            parsed = json.loads(result_payload)
            payload = parsed if isinstance(parsed, dict) else None
        except Exception:
            payload = None

    if not payload:
        return

    tool_name = payload.get("tool_name")
    tool_args = payload.get("tool_args")
    tool_output = payload.get("tool_output")
    evidence = payload.get("evidence")

    if not isinstance(tool_name, str) or not tool_name.strip():
        return

    artifact_ref = None
    summary = None
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        artifact_ref = evidence[0].get("artifact_ref")
        summary = evidence[0].get("summary")

    if not hasattr(task, "tool_events") or task.tool_events is None:
        task.tool_events = []

    task.tool_events.append(
        {
            "tool": tool_name,
            "args": tool_args if isinstance(tool_args, dict) else {"args": tool_args},
            "raw_result": tool_output,
            "artifact_ref": artifact_ref,
            "summary": summary,
        }
    )


def _find_workspace_matches_by_basename(*, root: Path, basename: str, limit: int = 25) -> List[str]:
    """Return workspace-relative POSIX paths matching basename."""
    if not basename:
        return []

    basename_lower = basename.lower()
    hits: List[str] = []
    # Avoid scanning transient/internal directories.
    exclude = set(getattr(config, "EXCLUDE_DIRS", set())) | {
        ".rev",
        ".pytest_cache",
        ".pytest_tmp",
        "tmp_test",
        "artifacts",
        "cache",
        "logs",
        "sessions",
        "__pycache__",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place.
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for fn in filenames:
            if fn.lower() != basename_lower:
                continue
            try:
                rel = Path(dirpath, fn).resolve().relative_to(root.resolve()).as_posix()
            except Exception:
                continue
            hits.append(rel)
            if len(hits) >= limit:
                return hits
    return hits


def _choose_best_path_match(*, original: str, matches: List[str]) -> Optional[str]:
    """Pick the most likely intended match, or None if ambiguous."""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    original_lower = original.replace("\\", "/").lower()

    def _score(rel_posix: str) -> tuple[int, int]:
        p = rel_posix.lower()
        score = 0
        
        # Prefer typical source roots.
        # Use dynamic discovery to identify common source patterns.
        source_roots = ["/src/", "/lib/", "/app/", "/core/", "/pkg/"]
        test_roots = ["/tests/", "/test/", "/spec/"]
        
        for root in source_roots:
            if root in f"/{p}/":
                score += 8
                break
        
        for root in test_roots:
            if root in f"/{p}/":
                score -= 5
                break
                
        # Prefer matches that end with the original (e.g., missing prefix).
        if original_lower and p.endswith(original_lower):
            score += 3
        # Slightly prefer shallower paths to avoid deep vendor/test duplicates.
        depth = p.count("/")
        return (score, -depth)

    ranked = sorted(matches, key=_score, reverse=True)
    best = ranked[0]
    if _score(best)[0] == _score(ranked[1])[0]:
        return None
    return best


def _choose_best_path_match_with_context(*, original: str, matches: List[str], description: str) -> Optional[str]:
    """Pick the most likely intended match, using description text to break ties."""
    chosen = _choose_best_path_match(original=original, matches=matches)
    if chosen or not matches or len(matches) == 1:
        return chosen

    desc = (description or "").replace("\\", "/").lower()
    if not desc:
        return None

    def _context_score(rel_posix: str) -> tuple[int, int, int]:
        p = rel_posix.replace("\\", "/").lower()
        parent = Path(p).parent.as_posix().lower()
        score = 0

        # Strongest signal: the full parent path appears in the description.
        if parent and parent != ".":
            needle = f"/{parent.strip('/')}/"
            hay = f"/{desc.strip('/')}/"
            if needle in hay:
                score += 50 + len(parent)

        # Secondary: directory/file names appear in the description.
        for part in Path(p).parts:
            part_l = str(part).lower()
            if part_l and part_l != "." and part_l in desc:
                score += 2

        # Penalize obviously duplicated segment paths.
        parts = Path(p).parts
        for i in range(1, len(parts)):
            if parts[:i] == parts[i : 2 * i] and len(parts) >= 2 * i + 1:
                score -= 25
                break

        depth = p.count("/")
        return (score, depth, len(p))

    ranked = sorted(matches, key=_context_score, reverse=True)
    if _context_score(ranked[0])[0] == _context_score(ranked[1])[0]:
        return None
    return ranked[0]


def _preflight_correct_action_semantics(task: Task) -> tuple[bool, List[str]]:
    """Coerce overloaded actions into read-only vs mutating actions.

    Returns:
        (ok_to_execute, messages)
    """
    action = (task.action_type or "").strip().lower()
    desc = (task.description or "").strip()
    if not action or not desc:
        return True, []

    mutate_actions = {"edit", "add", "create", "create_directory", "refactor", "delete", "rename", "fix"}
    read_actions = {"read", "analyze", "review", "research"}

    # Heuristic intent detection (word-boundary based to avoid false positives like
    # matching "analy" inside "analysis").
    desc_l = desc.lower()
    read_intent = bool(
        re.search(
            r"\b(read|inspect|review|analyze|analysis|understand|locate|find|search|inventory|identify|list|show|explain)\b",
            desc_l,
        )
    )
    write_intent = bool(
        re.search(
            r"\b(edit|update|modify|change|refactor|remove|delete|rename|create|add|write|generate|apply)\b"
            r"|split_python_module_classes|replace_in_file|write_file|apply_patch|append_to_file|create_directory",
            desc_l,
        )
    )

    messages: List[str] = []

    # If action says mutate but description is clearly inspection-only, coerce to READ.
    if action in mutate_actions and read_intent and not write_intent:
        task.action_type = "read"
        messages.append(f"coerced action '{action}' -> 'read' (inspection-only task)")
        return True, messages

    # If action says read-only but description includes mutation verbs, fail fast to replan.
    if action in read_actions and write_intent and not read_intent:
        messages.append(f"action '{action}' conflicts with write intent; choose edit/refactor instead")
        return False, messages

    return True, messages


def _order_available_actions(actions: List[str]) -> List[str]:
    """Return actions ordered to bias the lightweight planner toward READ first."""
    cleaned: List[str] = []
    for a in actions:
        if not isinstance(a, str):
            continue
        a = a.strip().lower()
        if not a:
            continue
        if a not in cleaned:
            cleaned.append(a)

    # Priority buckets: smaller comes earlier.
    priorities: dict[str, int] = {
        # Read-only first (better stability)
        "read": 0,
        "analyze": 1,
        "review": 2,
        "research": 3,
        "investigate": 3,
        "set_workdir": 4,
        # Then mutating actions
        "create_directory": 10,
        "add": 11,
        "edit": 12,
        "refactor": 13,
        "delete": 14,
        "rename": 15,
        "fix": 16,
        # Then execution actions
        "test": 30,
        # Advanced tooling last
        "create_tool": 40,
        "tool": 41,
        # Legacy shim last-last
        "general": 90,
    }

    def _key(a: str) -> tuple[int, int, str]:
        return (priorities.get(a, 50), cleaned.index(a), a)

    return sorted(cleaned, key=_key)


def _is_goal_achieved_response(response: Optional[str]) -> bool:
    """Detect when the planner says the goal is already achieved.
    
    Strictly matches 'GOAL_ACHIEVED' or clear variations like 'Goal achieved'
    while avoiding false positives on rambling text.
    """
    if not response:
        return False
    # Remove brackets, underscores, and extra whitespace
    normalized = re.sub(r"[\[\]_\s]+", " ", response).strip().lower()
    if not normalized:
        return False
    
    # Precise matches only
    if normalized in {"goal achieved", "goal completed", "work complete", "task achieved"}:
        return True
        
    # Allow slightly longer but still very clear success statements
    if normalized.startswith("goal "):
        # Must be exactly 'goal achieved', 'goal is achieved', etc.
        return bool(re.match(r"^goal (is )?(achieved|completed|done|finished)$", normalized))
        
    return normalized == "goal achieved"


def _dedupe_redundant_prefix_path(norm_path: str, project_root: Path) -> Optional[str]:
    """
    Collapse accidental repeated leading segments like
    'src/module/src/module/__init__.py' into the shortest suffix.
    This prevents recursive path drift when planners keep appending the same subpath.
    """
    if not norm_path:
        return None

    parts = list(Path(norm_path.replace("/", os.sep)).parts)
    # Need at least X/Y/X/Y (4 segments) to consider it a duplicated prefix.
    if len(parts) < 4:
        return None

    changed = False
    while len(parts) >= 4:
        reduced = False
        for prefix_len in range(1, len(parts) // 2 + 1):
            prefix = parts[:prefix_len]
            if parts[prefix_len : 2 * prefix_len] == prefix:
                parts = parts[prefix_len:]
                changed = True
                reduced = True
                break
        if not reduced:
            break

    if not changed:
        return None

    candidate = Path(*parts)
    try:
        if not candidate.is_absolute():
            candidate_abs = (project_root / candidate).resolve(strict=False)
        else:
            candidate_abs = candidate
    except Exception:
        return None

    if not candidate_abs.exists():
        return None

    try:
        return normalize_to_workspace_relative(candidate_abs, workspace_root=project_root)
    except Exception:
        return str(candidate_abs).replace("\\", "/")


def _preflight_correct_task_paths(*, task: Task, project_root: Path) -> tuple[bool, List[str]]:
    """Best-effort path correction for lightweight planner outputs.

    Returns:
        (ok_to_execute, messages)
    """
    desc = task.description or ""
    messages: List[str] = []
    action = (task.action_type or "").strip().lower()
    read_actions = {"read", "analyze", "review", "research", "investigate"}

    # Match path candidates with any common source/config extension.
    ext = r"(?:py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1)"
    # A more robust regex to find path-like strings, including those not perfectly formed.
    path_pattern = rf'((?:[A-Za-z]:)?[\\/]?[\w\s._-]*[\\/]+[\w\s._-]+\.{ext}\b|[\w._-]+\.{ext}\b)'
    
    raw_candidates = re.findall(path_pattern, desc)
    
    # Clean up and deduplicate candidates
    candidates = sorted(
        set(
            p.strip() for p in raw_candidates if p.strip()
        )
    )
    if not candidates:
        return True, messages

    def _abs_for_normalized(norm: str) -> Optional[Path]:
        """Resolve a normalized path to an absolute path for existence checks.

        Prefer project_root for relative paths (planner preflight) to avoid
        split-brain issues if Workspace isn't initialized yet.
        """
        p = Path(norm.replace("/", os.sep))
        if not p.is_absolute():
            return (project_root / p).resolve(strict=False)
        try:
            return resolve_workspace_path(norm, purpose="preflight").abs_path
        except WorkspacePathError:
            return None

    existing_any = 0
    missing_unresolved: List[str] = []

    for raw in candidates:
        normalized = normalize_path(raw)

        deduped = _dedupe_redundant_prefix_path(normalized, project_root=project_root)
        if deduped and deduped != normalized:
            if raw in desc:
                desc = desc.replace(raw, deduped)
            if normalized in desc:
                desc = desc.replace(normalized, deduped)
            messages.append(f"normalized duplicated path '{raw}' -> '{deduped}'")
            normalized = deduped

        abs_path = _abs_for_normalized(normalized)
        if abs_path is None:
            # Leave it to the main allowlist error path.
            continue

        if abs_path.exists():
            existing_any += 1
            # Canonicalize absolute paths to workspace-relative for future tool calls.
            rel = normalize_to_workspace_relative(abs_path, workspace_root=project_root)
            if rel and rel != normalized and raw in desc:
                desc = desc.replace(raw, rel)
                messages.append(f"normalized path '{raw}' -> '{rel}'")
            continue

        # Missing path: try to locate by basename.
        basename = Path(normalized.replace("/", os.sep)).name
        basenames = [basename]
        # Common tool behavior: keep backups as *.py.bak
        if basename.lower().endswith(".py") and not basename.lower().endswith(".py.bak"):
            basenames.append(basename + ".bak")
        if basename.lower().endswith(".py.bak"):
            basenames.append(basename[: -len(".bak")])

        # Check if a .py file was split into a package (directory with __init__.py)
        # e.g., src/module.py -> src/module/__init__.py
        package_init_match: Optional[str] = None
        if basename.lower().endswith(".py") and not basename.lower().endswith(".py.bak"):
            # Look for a package directory with the same name (without .py extension)
            parent_dir = Path(normalized.replace("/", os.sep)).parent
            package_name = basename[:-3]  # Remove .py
            package_dir = parent_dir / package_name if str(parent_dir) != "." else Path(package_name)
            package_init = package_dir / "__init__.py"
            package_init_abs = (project_root / package_init).resolve(strict=False)
            if package_init_abs.exists():
                try:
                    package_init_match = normalize_to_workspace_relative(package_init_abs, workspace_root=project_root)
                except Exception:
                    package_init_match = str(package_init).replace("\\", "/")

        matches: List[str] = []
        for bn in basenames:
            matches.extend(_find_workspace_matches_by_basename(root=project_root, basename=bn))
        matches = sorted(set(matches))
        primary_matches = [m for m in matches if not m.endswith(".bak")]
        backup_matches = [m for m in matches if m.endswith(".bak")]

        # Prefer package __init__.py over backup when a file was split into a package
        if package_init_match and not primary_matches:
            chosen = package_init_match
            messages.append(f"resolved missing path to package '{chosen}' (file was split into package)")
            if raw in desc:
                desc = desc.replace(raw, chosen)
            existing_any += 1
            continue

        # Prefer real sources over backups; avoid auto-operating on backups for mutating actions.
        preferred_pool = primary_matches if primary_matches else matches
        chosen = _choose_best_path_match_with_context(original=normalized, matches=preferred_pool, description=desc)

        # If the planner only emitted a bare filename (e.g., "__init__.py") and
        # there are multiple matches in the workspace, avoid "helpfully" picking
        # one and accidentally duplicating a path (src/module/src/module/...).
        if not ("/" in normalized or "\\" in normalized) and len(preferred_pool) > 1 and not chosen:
            missing_unresolved.append(
                f"ambiguous missing path '{raw}' (multiple candidates for bare filename)"
            )
            continue

        if not chosen and backup_matches and not primary_matches and action not in read_actions:
            missing_unresolved.append(
                f"missing path '{raw}' (only backup(s) found: {backup_matches[:3]})"
            )
            continue
        if chosen:
            if chosen.endswith(".bak") and action not in read_actions:
                missing_unresolved.append(
                    f"missing path '{raw}' (only backup found: {chosen}; restore original before mutating)"
                )
                continue

            # If the resolved path already appears in the description, avoid
            # duplicating segments like "src/module/src/module/__init__.py".
            if chosen in desc:
                messages.append(
                    f"resolved missing path to '{chosen}' (already present; left unchanged)"
                )
                existing_any += 1
                continue

            # Check if replacing 'raw' with 'chosen' would create a redundant path.
            # e.g. if desc contains 'src/module.py' and we replace 'module.py' with 'src/module.py'
            # we get 'src/src/module.py'.
            if f"/{raw}" in desc.replace("\\", "/") or f"\\{raw}" in desc:
                # If it's already prefixed by something, check if that prefix matches the 'chosen' path's head.
                # If it does, we should just consider it resolved and not replace.
                if chosen in desc.replace("\\", "/").replace("//", "/"):
                     messages.append(
                        f"resolved missing path to '{chosen}' (already present as suffix; left unchanged)"
                    )
                     existing_any += 1
                     continue

            # Use regex with word boundaries to avoid replacing partial segments of other paths.
            # We escape regex special characters in the raw/normalized strings.
            replaced = False
            for target in sorted({raw, normalized}, key=len, reverse=True):
                if target in desc:
                    pattern = r'(?<![A-Za-z0-9_./\\])' + re.escape(target) + r'(?![A-Za-z0-9_./\\])'
                    new_desc, count = re.subn(pattern, chosen.replace('\\', '\\\\'), desc)
                    if count > 0:
                        desc = new_desc
                        replaced = True
            
            if replaced:
                messages.append(f"resolved missing path to '{chosen}' (requested '{raw}')")
                existing_any += 1
                continue

        if matches:
            missing_unresolved.append(f"ambiguous missing path '{raw}' (matches={matches[:5]})")
        else:
            missing_unresolved.append(f"missing path '{raw}' (no matches found)")

    # Final cleanup pass to dedupe any paths that were constructed during replacement.
    final_candidates = sorted(
        set(
            re.findall(
                r'([A-Za-z]:[\\/][^\s"\'`]+\.py(?:\.bak)?\b|(?:\./)?[A-Za-z0-9_./\\-]+\.py(?:\.bak)?\b)',
                desc,
            )
        )
    )
    for cand in final_candidates:
        deduped = _dedupe_redundant_prefix_path(cand, project_root=project_root)
        if deduped and deduped != cand:
            desc = desc.replace(cand, deduped)
            messages.append(f"cleaned up duplicated path segment in '{cand}' -> '{deduped}'")

    task.description = desc

    if not missing_unresolved:
        return True, messages

    # READ-like tasks should not reference missing files.
    if action in read_actions:
        messages.extend(missing_unresolved[:1])
        return False, messages

    # Mutating tasks commonly mention output paths that don't exist yet; only fail
    # if NONE of the referenced paths could be resolved to an existing file.
    if existing_any == 0:
        messages.extend(missing_unresolved[:1])
        return False, messages

    # Otherwise, allow execution to proceed (best-effort). Avoid spamming logs.
    messages.append("ignored missing output path(s); at least one input path exists")
    return True, messages


def _generate_path_hints(completed_tasks_log: List[str]) -> str:
    """Extract important paths from recent tool outputs to help the planner."""
    if not completed_tasks_log:
        return ""
    
    hints = []
    # Look for paths in the last 5 tasks
    for log in completed_tasks_log[-5:]:
        # Extract paths mentioned in "Output:" segments
        if "Output:" in log:
            output_part = log.split("Output:", 1)[1]
            # Match likely file paths (with common extensions) or directory-looking paths
            # 1. Paths with extensions (py, json, etc)
            # 2. Paths ending in / or \
            # 3. Quoted strings that look like relative paths
            matches = re.findall(r'([A-Za-z0-9_./\\-]+\.(?:py|json|md|txt|csv|bak|log)\b)|([A-Za-z0-9_./\\-]+[/\\])|(?:"|\')(\./[A-Za-z0-9_./\\-]+)(?:"|\')', output_part)
            for m_tuple in matches:
                # findall with multiple groups returns tuples
                for m in m_tuple:
                    if m and ("/" in m or "\\" in m):
                        hints.append(m.strip('"\''))
                    
    if not hints:
        return ""
        
    unique_hints = sorted(set(hints))
    return "\nPATH HINTS (use these exact paths if relevant):\n" + "\n".join(f"- {h}" for h in unique_hints) + "\n"


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    enable_learning: bool = False
    enable_research: bool = True
    enable_review: bool = True
    enable_validation: bool = True
    review_strictness: ReviewStrictness = ReviewStrictness.MODERATE
    enable_action_review: bool = False
    enable_auto_fix: bool = False
    parallel_workers: int = 1
    auto_approve: bool = True
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT
    validation_mode: Literal["none", "smoke", "targeted", "full"] = VALIDATION_MODE_DEFAULT
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES
    validation_retries: int = MAX_VALIDATION_RETRIES
    adaptive_replan_attempts: int = MAX_ADAPTIVE_REPLANS
    # Prompt optimization
    enable_prompt_optimization: bool = True
    auto_optimize_prompt: bool = False
    # ContextGuard configuration
    enable_context_guard: bool = True
    context_guard_interactive: bool = True
    context_guard_threshold: float = 0.3
    # Back-compat shim (legacy)
    max_retries: Optional[int] = None
    max_plan_tasks: int = MAX_PLAN_TASKS
    max_planning_iterations: int = config.MAX_PLANNING_TOOL_ITERATIONS

    def __post_init__(self):
        if self.parallel_workers != 1:
            self.parallel_workers = 1
        
        if self.max_retries is not None:
            self.orchestrator_retries = self.max_retries
            self.plan_regen_retries = self.max_retries
            self.validation_retries = self.max_retries
            self.adaptive_replan_attempts = self.max_retries


@dataclass
class OrchestratorResult:
    """Result of an orchestrated execution."""
    success: bool
    phase_reached: AgentPhase
    plan: Optional[ExecutionPlan] = None
    research_findings: Optional[ResearchFindings] = None
    review_decision: Optional[ReviewDecision] = None
    validation_status: Optional[ValidationStatus] = None
    execution_time: float = 0.0
    resource_budget: Optional[ResourceBudget] = None
    agent_insights: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    no_retry: bool = False
    run_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "phase_reached": self.phase_reached.value,
            "review_decision": self.review_decision.value if self.review_decision else None,
            "validation_status": self.validation_status.value if self.validation_status else None,
            "execution_time": self.execution_time,
            "resource_budget": self.resource_budget.to_dict() if self.resource_budget else None,
            "agent_insights": self.agent_insights,
            "errors": self.errors
        }


class Orchestrator:
    """Coordinates all agents for autonomous task execution."""

    def __init__(self, project_root: Path, config: Optional[OrchestratorConfig] = None):
        self.project_root = project_root
        self._user_config_provided = config is not None
        self.config = config or OrchestratorConfig()
        self.context: Optional[RevContext] = None
        self.learning_agent = LearningAgent(project_root) if self.config.enable_learning else None
        self.debug_logger = DebugLogger.get_instance()
        self._context_builder: Optional[ContextBuilder] = None

    def _update_phase(self, new_phase: AgentPhase):
        if self.context:
            self.context.set_current_phase(new_phase)
            if config.EXECUTION_MODE != 'sub-agent':
                print(f"\nðŸ”¸ Entering phase: {new_phase.value}")

    def _transform_redundant_action(self, task: Task, action_sig: str, count: int) -> Task:
        """Transform a redundant action into one that produces new evidence."""
        desc = task.description.lower()
        file_path = _extract_file_path_from_description(task.description)
        
        print(f"  ⚠️  Redundant action detected ({count}x): {action_sig}")
        
        if task.action_type in {"read", "analyze"} and file_path:
            # If reading the same file, try searching for usages instead
            symbol_match = re.search(r'class\s+(\w+)|def\s+(\w+)', desc)
            symbol = symbol_match.group(1) or symbol_match.group(2) if symbol_match else None
            
            if symbol:
                print(f"  → Transforming to symbol usage search: {symbol}")
                return Task(
                    description=f"Find all usages of symbol '{symbol}' in the codebase to understand its context",
                    action_type="analyze"
                )
            else:
                print(f"  → Transforming to git diff check")
                return Task(
                    description=f"Check git diff for {file_path} to see recent changes and identify potential issues",
                    action_type="analyze"
                )
        
        if task.action_type == "edit" and file_path:
            print(f"  → Transforming stuck EDIT to READ for re-synchronization: {file_path}")
            return Task(
                description=f"Read the current content of {file_path} to identify why previous edits failed to match. Pay close attention to exact whitespace and indentation.",
                action_type="read"
            )
        
        if task.action_type == "test":
            print(f"  → Transforming to build/compile check")
            return Task(
                description="Run a full build or compilation check to ensure structural integrity",
                action_type="test"
            )
            
        # Generic transformation: search for related patterns
        print(f"  → Transforming to generic pattern search")
        return Task(
            description=f"Search for patterns related to: {task.description[:50]}",
            action_type="analyze"
        )

    def _display_prompt_optimization(self, original: str, optimized: str) -> None:
        """Display original vs improved prompts for transparency."""
        original_lines = original.strip().splitlines() or [original]
        optimized_lines = optimized.strip().splitlines() or [optimized]

        print("  Original request:")
        for line in original_lines:
            print(f"    {line}")

        print("  Optimized request:")
        for line in optimized_lines:
            print(f"    {line}")

    def _maybe_optimize_user_request(self) -> bool:
        """Optimize the current user request and log visibility when enabled."""
        if not self.config.enable_prompt_optimization or not self.context:
            return False

        original_request = self.context.user_request
        optimized_request, was_optimized = optimize_prompt_if_needed(
            original_request,
            auto_optimize=self.config.auto_optimize_prompt
        )
        if not was_optimized:
            if self.config.auto_optimize_prompt:
                print("\n[OK] Request already optimized; using original text")
                # Still show the final prompt for transparency (it's identical).
                self._display_prompt_optimization(original_request, original_request)
            return False

        print(f"\n[OK] Request optimized for clarity")
        self._display_prompt_optimization(original_request, optimized_request)
        self.context.user_request = optimized_request
        self.context.add_insight("optimization", "prompt_optimized", True)
        self.context.agent_insights["prompt_optimization"] = {
            "optimized": True,
            "original": original_request[:100],
            "improved": optimized_request[:100],
        }
        self.debug_logger.log(
            "orchestrator",
            "PROMPT_OPTIMIZED",
            {
                "auto_optimize": self.config.auto_optimize_prompt,
                "original_request": original_request,
                "optimized_request": optimized_request,
            },
        )
        return True

    def _collect_repo_stats(self) -> Dict[str, Any]:
        repo_context_raw = get_repo_context()
        repo_context = {} if isinstance(repo_context_raw, str) else repo_context_raw
        return {
            "file_count": len(repo_context.get("all_files", [])),
            "estimated_complexity": 5,
            "last_commit_age_days": 7,
            "has_tests_dir": os.path.isdir(self.project_root / "tests"),
            "has_docs_dir": os.path.isdir(self.project_root / "docs"),
            "has_examples_dir": os.path.isdir(self.project_root / "examples"),
        }

    def execute(self, user_request: str, resume: bool = False) -> OrchestratorResult:
        """Execute a task through the full agent pipeline."""
        global _active_context
        aggregate_errors: List[str] = []
        last_result: Optional[OrchestratorResult] = None
        self.context = RevContext(user_request=user_request, resume=resume)
        _active_context = self.context
        ensure_project_memory_file()
        # Keep repo_context minimal; sub-agents will retrieve focused context via ContextBuilder.
        self.context.repo_context = ""

        try:
            for attempt in range(self.config.orchestrator_retries + 1):
                if attempt > 0:
                    print(f"\n\n🔄 Orchestrator retry {attempt}/{self.config.orchestrator_retries}")
                    self.context.plan = None
                    self.context.state_manager = None
                    self.context.errors = []

                result = self._run_single_attempt(user_request)
                aggregate_errors.extend([f"Attempt {attempt + 1}: {err}" for err in self.context.errors])

                if result.success or result.no_retry:
                    result.errors = aggregate_errors
                    result.agent_insights = self.context.agent_insights
                    return result

                last_result = result
                last_result.errors.extend(self.context.errors)

            if last_result:
                last_result.errors = aggregate_errors
                last_result.agent_insights = self.context.agent_insights
                return last_result

            return OrchestratorResult(
                success=False,
                phase_reached=AgentPhase.FAILED,
                errors=["Unknown orchestrator failure"],
                agent_insights=self.context.agent_insights
            )
        finally:
            _active_context = None
        
    def _run_single_attempt(self, user_request: str) -> OrchestratorResult:
        """Run a single orchestration attempt."""
        execution_mode_val = config.EXECUTION_MODE
        if execution_mode_val != 'sub-agent':
            print("\n" + "=" * 60)
            print("ORCHESTRATOR - MULTI-AGENT COORDINATION")
            print("=" * 60)
            print(f"Task: {user_request[:100]}...")
            print(f"Execution Mode: {execution_mode_val.upper()}")

        self.context.user_request = user_request
        self.context.auto_approve = self.config.auto_approve
        self.context.resource_budget = ResourceBudget()
        self._maybe_optimize_user_request()
        user_request = self.context.user_request
        start_time = time.time()

        from rev.execution.router import TaskRouter
        router = TaskRouter()
        route = router.route(self.context.user_request, repo_stats=self._collect_repo_stats())
        run_mode = route.mode

        result = OrchestratorResult(
            success=False, phase_reached=self.context.current_phase, plan=None,
            resource_budget=self.context.resource_budget, agent_insights=self.context.agent_insights,
            errors=self.context.errors, run_mode=run_mode,
        )

        coding_modes = {"quick_edit", "focused_feature", "full_feature", "refactor", "test_focus"}
        coding_mode = route.mode in coding_modes

        try:
            if execution_mode_val == 'sub-agent':
                self._update_phase(AgentPhase.EXECUTION)
                execution_success = self._continuous_sub_agent_execution(user_request, coding_mode)
                result.success = execution_success
                result.phase_reached = AgentPhase.COMPLETE if execution_success else AgentPhase.FAILED
                result.no_retry = bool(self.context.agent_state.get("no_retry")) if self.context else False
                if not execution_success:
                    result.errors.append("Sub-agent execution failed or was halted.")
            else:
                self._execute_heavy_path(user_request, coding_mode, result)
        
        except KeyboardInterrupt:
            if self.context:
                try:
                    self.context.save_history()
                except Exception:
                    pass
            if self.context.plan and self.context.state_manager:
                try:
                    self.context.state_manager.on_interrupt(token_usage=get_token_usage())
                except Exception as exc:
                    print(f"⚠️  Warning: could not save checkpoint on interrupt ({exc})")
            raise
        except Exception as e:
            failure_phase = self.context.current_phase or AgentPhase.FAILED
            tb = traceback.format_exc()
            print(f"\n❌ Exception during {failure_phase.value} phase: {e}\n{tb}")
            result.success = False
            result.phase_reached = failure_phase
            result.errors.append(f"{failure_phase.value} phase error: {e}")

        result.execution_time = time.time() - start_time
        self.context.resource_budget.tokens_used = get_token_usage().get("total", 0)
        self.context.resource_budget.update_time()

        if execution_mode_val != 'sub-agent':
            print(f"\n📊 Resource Usage Summary:")
            print(f"   {self.context.resource_budget.get_usage_summary()}")
        
        self._emit_run_metrics(result.plan, result, self.context.resource_budget)
        self._display_summary(result)
        return result

    def _execute_heavy_path(self, user_request: str, coding_mode: bool, result: OrchestratorResult):
        # Phase 2: Research (optional)
        research_findings = None
        if self.config.enable_research:
            self._update_phase(AgentPhase.RESEARCH)
            research_findings = research_codebase(
                user_request,
                quick_mode=False,
                search_depth=self.config.research_depth
            )
            if research_findings:
                result.research_findings = research_findings
                self.context.add_insight("research", "findings_obtained", True)

        # Phase 2b: Prompt Optimization (optional)
        # Phase 2c: ContextGuard (optional)
        if self.config.enable_context_guard and research_findings:
            self._update_phase(AgentPhase.CONTEXT_GUARD)
            from rev.execution.context_guard import run_context_guard

            guard_result = run_context_guard(
                user_request=self.context.user_request,
                research_findings=research_findings,
                interactive=self.config.context_guard_interactive,
                threshold=self.config.context_guard_threshold,
                budget=self.context.resource_budget
            )

            # Store results in context
            self.context.context_sufficiency = guard_result.sufficiency
            self.context.purified_context = guard_result.filtered_context
            self.context.add_insight("context_guard", "action", guard_result.action_taken)
            self.context.add_insight("context_guard", "tokens_saved", guard_result.filtered_context.tokens_saved)

            # Handle insufficiency
            if guard_result.action_taken == "insufficient":
                self.context.add_error(f"ContextGuard: Insufficient context for safe planning")
                raise Exception(f"Insufficient context. Gaps: {[g.description for g in guard_result.sufficiency.gaps]}")

        self._update_phase(AgentPhase.PLANNING)
        plan = planning_mode(
            self.context.user_request, coding_mode=coding_mode,
            max_plan_tasks=self.config.max_plan_tasks, max_planning_iterations=self.config.max_planning_iterations,
        )
        self.context.update_plan(plan)
        result.plan = self.context.plan
        self.context.set_state_manager(StateManager(self.context.plan))

        if not self.context.plan.tasks:
            raise Exception("Planning agent produced no tasks.")

        if self.config.enable_review:
            self._update_phase(AgentPhase.REVIEW)

        self._update_phase(AgentPhase.EXECUTION)
        execution_mode(
            self.context.plan, auto_approve=self.config.auto_approve, tools=get_available_tools(),
            enable_action_review=self.config.enable_action_review, coding_mode=coding_mode,
            state_manager=self.context.state_manager, budget=self.context.resource_budget,
        )

        if self.config.enable_validation:
            self._update_phase(AgentPhase.VALIDATION)
        
        all_tasks_handled = all(t.status == TaskStatus.COMPLETED for t in self.context.plan.tasks)
        validation_ok = True
        result.success = all_tasks_handled and validation_ok
        result.phase_reached = AgentPhase.COMPLETE if result.success else AgentPhase.VALIDATION

    def _decompose_extraction_task(self, failed_task: Task) -> Optional[Task]:
        """
        When a task fails, ask the LLM if it can be decomposed into more granular steps.

        Rather than using brittle keyword detection, we let the LLM evaluate the failed
        task and suggest a decomposition strategy if one exists.
        """
        decomposition_prompt = (
            f"A task has failed: {failed_task.description}\n\n"
            f"Error: {failed_task.error if failed_task.error else 'Unknown'}\n\n"
            f"Can this task be decomposed into smaller, more specific subtasks that might succeed?\n"
            f"If yes, describe the first subtask that should be attempted next in detail.\n"
            f"If no, just respond with 'CANNOT_DECOMPOSE'.\n\n"
            "CRITICAL - Error Scope:\n"
            "- Only fix errors that are DIRECTLY RELATED to your changes\n"
            "- If validation shows errors in unrelated parts of the file, IGNORE them\n"
            "- Pre-existing errors in other functions/sections should NOT be fixed by you\n"
            "- Focus ONLY on making your specific change work correctly\n\n"
            "Important import strategy note (avoid churn):\n"
            "- If a refactor split creates a package (directory with __init__.py exports), update call sites/tests to\n"
            "  import from the package exports (e.g., `from package import ExportedSymbol`).\n"
            "- Do NOT expand `from pkg import *` into dozens of per-module imports.\n\n"
            f"Important: Be specific about what concrete action the next task should take. "
            f"Use [ACTION_TYPE] format like [CREATE] or [EDIT] or [REFACTOR]."
        )

        response_data = ollama_chat([{"role": "user", "content": decomposition_prompt}])

        if "error" in response_data or not response_data.get("message", {}).get("content"):
            return None

        response_content = response_data.get("message", {}).get("content", "").strip()

        if "CANNOT_DECOMPOSE" in response_content.upper():
            return None

        # Robust parsing: find the first instance of [ACTION_TYPE] anywhere in the response
        match = re.search(r"\[([A-Z_]+)\]\s*(.*)", response_content, re.DOTALL)
        if match:
            action_raw = match.group(1)
            description = match.group(2).strip()
            
            # Clean up: if there's a second action block, stop there
            next_action_pattern = r'\[[A-Z_]+\]'
            match_next = re.search(next_action_pattern, description)
            if match_next:
                description = description[:match_next.start()].strip()

            action_type = normalize_action_type(
                action_raw,
                available_actions=AgentRegistry.get_registered_action_types(),
            )

            print(f"\n  [DECOMPOSITION] Parsed suggested subtask:")
            print(f"    Action: {action_type}")
            print(f"    Task: {description[:100]}...")
            return Task(description=description, action_type=action_type)
        else:
            # Fallback: if no brackets found, try to find keywords or use the first line
            lines = [l.strip() for l in response_content.splitlines() if l.strip()]
            first_meaningful = ""
            for line in lines:
                if not any(kw in line.lower() for kw in ["yes", "decompose", "fail", "error", "subtask"]):
                    first_meaningful = line
                    break
            
            desc = first_meaningful or (lines[0] if lines else response_content)
            print(f"\n  [DECOMPOSITION] Fallback suggestion: {desc[:100]}...")
            return Task(
                description=desc,
                action_type="edit" # Default to edit for repair
            )

    def _determine_next_action(self, user_request: str, work_summary: str, coding_mode: bool, iteration: int = 1, failure_notes: str = "", path_hints: str = "", agent_notes: str = "") -> Optional[Task]:
        """A truly lightweight planner that makes a direct LLM call."""
        available_actions = _order_available_actions(AgentRegistry.get_registered_action_types())

        blocked_note = ""
        if self.context:
            blocked_tests = bool(self.context.agent_state.get("tests_blocked_no_changes"))
            last_test_rc = self.context.agent_state.get("last_test_rc")
            if blocked_tests and isinstance(last_test_rc, int) and last_test_rc != 0:
                blocked_note = (
                    "Important: The last [TEST] was skipped because no code changed since the last failing test run.\n"
                    "Do NOT propose another [TEST] until a code-changing step (e.g. [EDIT]/[REFACTOR]) is completed.\n\n"
                )
        
        history_note = ""
        if iteration == 1 and work_summary != "No actions taken yet.":
            history_note = (
                "Important: You are resuming a previous session. Do NOT declare GOAL_ACHIEVED on your very first turn. "
                "Instead, perform a [READ] or [ANALYZE] step to verify that the work from the previous session is still correct and consistent with the current filesystem state.\n\n"
            )

        feedback_note = ""
        if self.context and self.context.user_feedback:
            feedback_note = "\nDIRECT USER GUIDANCE (Priority - follow these instructions now):\n"
            for fb in self.context.user_feedback:
                feedback_note += f"- {fb}\n"
            feedback_note += "\n"
            # Clear feedback after incorporating it into the prompt
            self.context.user_feedback = []

        prompt = (
            f"Original Request: {user_request}\n\n"
            f"{feedback_note}"
            f"{work_summary}\n\n"
            f"{path_hints}\n"
            f"{agent_notes}\n"
            f"{failure_notes}\n"
            f"{blocked_note}"
            f"{history_note}"
            "Based on the work completed, what is the single next most important action to take? "
            "If a previous action failed, propose a different action to achieve the goal.\n"
            "\n"
            "ACTION SEMANTICS (critical):\n"
            "- Use [READ] or [ANALYZE] when the next step is inspection only (open files, search, inventory imports, understand structure).\n"
            "- Use [EDIT]/[ADD]/[CREATE_DIRECTORY]/[REFACTOR] only when you will perform a repo-changing tool call in this step.\n"
            "- Use [TOOL] only to execute an existing built-in tool (e.g., `split_python_module_classes`).\n"
            "- Use [CREATE_TOOL] only when no existing tool can do the job and you must create a new tool.\n"
            "- If unsure whether a path exists, choose [READ] first to locate the correct file path(s).\n"
            "\n"
             "Constraints to avoid duplicating work:\n"
             "- CRITICAL: Check the file tree in the history. If the project is already organized into subdirectories, USE THEM. Do NOT create duplicate files or project roots in the top-level directory.\n"
             "- Do not propose repeating a step that is already complete (e.g., do not re-create a directory that exists).\n"
             "- CRITICAL: If you have already completed 2+ READ/ANALYZE steps on the same file, you MUST now use [EDIT] to make changes. Do NOT propose another read.\n"
             "- If the same file/lines have been inspected multiple times, transition to [EDIT] immediately.\n"
             "- If you are going to use `split_python_module_classes`, do not hand-author the package `__init__.py` first; let the tool generate it.\n"
             "- After `split_python_module_classes` runs, treat the directory as the source of truth; prefer editing the package files rather than the original monolithic module.\n"
             "- If a source file was split into a package (directory with __init__.py) and the original single-file path no longer exists, do NOT propose edits to that missing file; operate on the package files that actually exist.\n"
             "- If the code was split into a package with __init__.py exports, prefer package-export imports at call sites.\n"
             "- Avoid replacing `from pkg import *` with dozens of per-module imports; only import names actually used.\n"
             "- Prefer `from package import ExportedSymbol` over `from package.module import ExportedSymbol` when the package exports it.\n"
             "- SECURITY: Always propose security-minded actions. Never store secrets in plain text. Use proper input validation.\n"
             "\n"
             "TEST-DRIVEN DEVELOPMENT (TDD) PRINCIPLES (MANDATORY):\n"
             "- Write tests BEFORE implementation code. This is non-negotiable.\n"
             "- If the request involves new functionality, your first few actions must be to [ADD] test files and [TEST] them (expecting failure).\n"
             "- Only after tests are written and verified as failing should you [EDIT] implementation code.\n"
             "- Use [TEST] frequently to verify progress. If a test fails, your next action should be to [ANALYZE] the failure or [EDIT] the code to fix it.\n"
             "\n"
             "FAILURE RECOVERY GUIDANCE:\n"
             "- If an [EDIT] or [REFACTOR] action failed because a tool (like replace_in_file) made no changes (replaced=0), do NOT repeat the same action.\n"
             "- Instead, use [READ] to inspect the file again and identify why the match failed (check whitespace, indentation, or if the code has changed).\n"
             "- If a [TEST] fails, read the test output carefully and use [ANALYZE] or [READ] to find the bug before attempting another [EDIT].\n"
             "\n"
             "- If history shows work but you haven't inspected it in this run, VERIFY IT FIRST.\n"
             "- DEPENDENCIES: If you modify a dependency file (e.g. `package.json`, `requirements.txt`), your very next step should be a [TEST] or [ADD] task to INSTALL the dependencies (e.g. `npm install`).\n"
             f"You MUST choose one of the following action types: {available_actions}\n"
             "\n"
             "RESPONSE FORMAT (CRITICAL - follow exactly):\n"
             "- Respond with EXACTLY ONE action on a SINGLE LINE\n"
             "- Format: [ACTION_TYPE] brief description of what to do\n"
             "- Do NOT output multiple actions or a plan - only the SINGLE NEXT step\n"
             "- Do NOT chain actions like '[READ] file [ANALYZE] content' - pick ONE\n"
             "- Example: [EDIT] refactor the authentication middleware to use the new session manager\n"
             "- If the goal has been achieved, respond with only: GOAL_ACHIEVED"
        )
        
        response_data = ollama_chat([{"role": "user", "content": prompt}])

        if "error" in response_data:
            print(f"  ❌ LLM Error in lightweight planner: {response_data['error']}")
            if self.context:
                self.context.set_agent_state("planner_error", response_data["error"])
                self.context.add_error(f"Lightweight planner LLM error: {response_data['error']}")
            return None

        response_content = response_data.get("message", {}).get("content", "")
        if hasattr(self, "debug_logger") and self.debug_logger:
            self.debug_logger.log("orchestrator", "PLANNER_RESPONSE_RAW", {
                "content": response_content
            }, "DEBUG")

        if _is_goal_achieved_response(response_content):
            print(f"  [i] Goal achieved detected in response: \"{response_content.strip()}\"")
            if hasattr(self, "debug_logger") and self.debug_logger:
                self.debug_logger.log("orchestrator", "GOAL_ACHIEVED_DETECTED", {
                    "raw_content": response_content
                }, "INFO")
            return None
        
        if not response_content or response_content.strip().upper() == "GOAL_ACHIEVED":
            print(f"  [i] Empty response or explicit GOAL_ACHIEVED detected.")
            if hasattr(self, "debug_logger") and self.debug_logger:
                self.debug_logger.log("orchestrator", "EMPTY_OR_GOAL_ACHIEVED_RAW", {
                    "content": response_content
                }, "INFO")
            return None
        
        match = re.match(r"[\s]*\[(.*?)\]\s*(.*)", response_content.strip())
        if not match:
            print(f"  [!] No action brackets found. Raw response: \"{response_content.strip()}\"")
            if hasattr(self, "debug_logger") and self.debug_logger:
                self.debug_logger.log("orchestrator", "NO_BRACKET_MATCH", {
                    "content": response_content
                }, "DEBUG")
            return Task(description=response_content.strip(), action_type="general")

        action_raw = match.group(1)
        action_type = normalize_action_type(
            action_raw,
            available_actions=available_actions,
        )
        description = match.group(2).strip()

        if hasattr(self, "debug_logger") and self.debug_logger:
            self.debug_logger.log("orchestrator", "PARSED_ACTION_TYPE", {
                "raw": action_raw,
                "normalized": action_type
            }, "DEBUG")

        # Clean up malformed LLM output that contains multiple actions concatenated
        # e.g. "Open file.[READ] another[ANALYZE] more" -> "Open file."
        # Use regex to find potential start of next action tag (e.g. [READ], [EDIT], etc.)
        # We look for [UPPERCASE_ACTION] to distinguish from filename patterns like [id]
        action_pattern = r'\[\s*(?:' + '|'.join(re.escape(a.upper()) for a in available_actions) + r')\s*\]'
        match_next = re.search(action_pattern, description)
        if match_next:
            description = description[:match_next.start()].strip()

        # Also clean up trailing brackets like "src/module]"
        description = re.sub(r'\]$', '', description).strip()

        task = Task(description=description, action_type=action_type)
        if hasattr(self, "debug_logger") and self.debug_logger:
            # Log to standard debug log
            self.debug_logger.log("orchestrator", "TASK_DETERMINED", {
                "action_type": task.action_type,
                "description": task.description,
                "raw_response": response_content
            }, "DEBUG")
            
            # Log to transaction log for centralized review
            self.debug_logger.log_transaction_event("ORCHESTRATOR_DECISION", {
                "action_type": task.action_type,
                "description": task.description,
                "raw_response": response_content
            })

        return task

    def _extract_claims_from_log(self, log_entry: str) -> List[str]:
        """Extract high-level intent/claims from a task description."""
        # A claim is essentially what the agent is asserting it will do or find.
        # For simplicity, we treat the description as a single claim for now.
        return [log_entry.split('|')[0].strip()]

    def _evaluate_anchoring(self, user_request: str, completed_tasks_log: List[str]) -> AnchoringDecision:
        """Evaluate the current anchoring score to drive coordination decisions."""
        if not completed_tasks_log:
            return AnchoringDecision.RE_SEARCH

        scorer = AnchoringScorer()
        
        all_claims = []
        citations = set()
        test_outputs = []
        unresolved_symbols = []
        missing_files = []
        total_tools = 0

        for log in completed_tasks_log:
            # 1. Collect claims
            all_claims.extend(self._extract_claims_from_log(log))
            
            # 2. Extract citations (files mentioned in log or output)
            file_match = _extract_file_path_from_description(log)
            if file_match:
                citations.add(file_match)
            
            # 3. Collect test results
            if "[COMPLETED]" in log and "test" in log.lower():
                test_outputs.append(log)
            
            # 4. Collect errors/mismatches
            if "[FAILED]" in log:
                # Every failed task is a risk
                unresolved_symbols.append(log)
                if "missing path" in log.lower() or "not exist" in log.lower():
                    missing_files.append(log)
                if "undefined" in log.lower() or "unresolved" in log.lower():
                    # already added to unresolved_symbols, but can add specifically if needed
                    pass
            
            # 5. Track tool usage
            if "Output:" in log:
                total_tools += 1

        metrics = scorer.compute_anchoring_score(
            claims=all_claims,
            repo_citations=list(citations),
            test_outputs=test_outputs,
            unresolved_symbols=unresolved_symbols,
            missing_files=missing_files,
            tools_used_count=total_tools
        )

        print(f"\n  [UCCT] Anchoring Score: {metrics.raw_score:.2f} | Density: {metrics.evidence_density:.2f} | Risk: {metrics.mismatch_risk}")
        print(f"  [UCCT] Coordination Decision: {metrics.decision.value}")
        
        if hasattr(self, "debug_logger") and self.debug_logger:
            self.debug_logger.log("orchestrator", "ANCHORING_EVALUATION", metrics.__dict__, "INFO")

        return metrics.decision

    def _is_completion_grounded(self, completed_tasks_log: List[str]) -> Tuple[bool, str]:
        """Verify that the completion is grounded in concrete artifacts/evidence."""
        if not completed_tasks_log:
            return False, "No work history to verify."

        # A completion must reference:
        # 1. File diffs/writes
        # 2. Test output/artifact IDs
        # 3. Search results
        # 4. Runtime checks
        
        evidence_found = {
            "files": False,
            "tests": False,
            "search": False,
            "runtime": False
        }

        for log in completed_tasks_log:
            log_l = log.lower()
            # 1. File diffs/writes
            if any(k in log_l for k in ["wrote", "replaced", "created file", "modified", "diff", "write_file", "replace_in_file", "apply_patch"]):
                evidence_found["files"] = True
            # 2. Test outputs
            if any(k in log_l for k in ["passed", "failed", "test suite", "pytest", "run_tests", "run_cmd"]):
                evidence_found["tests"] = True
            # 3. Search results
            if any(k in log_l for k in ["found", "matches", "listing", "search", "read file", "list_dir", "read_file", "search_code", "rag_search"]):
                evidence_found["search"] = True
            # 4. Runtime checks
            if any(k in log_l for k in ["runtime", "log", "executed", "status", "exit code", "analyze_runtime_logs"]):
                evidence_found["runtime"] = True

        # Require at least Search (knowing what's there) AND either File/Test/Runtime (doing something)
        has_research = evidence_found["search"]
        has_action = evidence_found["files"] or evidence_found["tests"] or evidence_found["runtime"]
        
        # TDD Check: If the request mentioned "test" or "application", require test evidence
        request_lower = user_request.lower()
        needs_tests = any(kw in request_lower for kw in ["test", "verify", "check", "application", "tdd"])
        if needs_tests and not evidence_found["tests"]:
            return False, "Completion rejected: The request implies test-driven development, but no test execution evidence was found."

        if not has_research:
            return False, "Completion rejected: No research/search evidence found. Agent acted without reading."
        if not has_action:
            return False, "Completion rejected: No concrete action (file edit, test run, or runtime check) verified."
            
        return True, "Completion grounded in artifacts."

    def _continuous_sub_agent_execution(self, user_request: str, coding_mode: bool) -> bool:
        """Executes a task by continuously calling a lightweight planner for the next action.

        Implements the proper workflow:
        1. Plan next action (unless forced_next_task is set)
        2. Execute action
        3. VERIFY execution actually succeeded
        4. Report results
        5. Re-plan if needed
        """
        print(f"\n◈ {colorize('Sub-agent Orchestrator', Colors.BRIGHT_CYAN, bold=True)} active")

        from rev.execution.ledger import get_ledger
        ledger = get_ledger()

        # Persistence: load previous work history
        completed_tasks_log = self.context.load_history()
        if completed_tasks_log:
            print(f"  ✓ Loaded {len(completed_tasks_log)} tasks from history")

        # Track completed Task objects (separate from string-based logs)
        completed_tasks: List[Task] = []

        # Ensure we have a persistent plan and state manager for checkpoints
        if not self.context.plan:
            if self.context.resume:
                latest = StateManager.find_latest_checkpoint()
                if latest:
                    try:
                        self.context.plan = StateManager.load_from_checkpoint(latest)
                        print(f"  ✓ Loaded cumulative plan from checkpoint: {latest}")
                        # Populate completed_tasks from the plan
                        for task in self.context.plan.tasks:
                            if task.status == TaskStatus.COMPLETED:
                                completed_tasks.append(task)
                                # If history log is empty, reconstruct it from plan
                                if not completed_tasks_log:
                                    status_tag = f"[{task.status.name}]"
                                    log_entry = f"{status_tag} {task.description}"
                                    if task.result and isinstance(task.result, str):
                                        try:
                                            res = json.loads(task.result)
                                            if isinstance(res, dict) and "summary" in res:
                                                log_entry += f" | Output: {res['summary']}"
                                        except: pass
                                    completed_tasks_log.append(log_entry)
                            elif task.status == TaskStatus.FAILED and not completed_tasks_log:
                                completed_tasks_log.append(f"[{task.status.name}] {task.description} | Reason: {task.error}")
                        
                        if completed_tasks_log:
                            self.context.work_history = completed_tasks_log
                    except Exception as e:
                        print(f"  ⚠️  Failed to load checkpoint: {e}")
                        self.context.plan = ExecutionPlan(tasks=[])
                else:
                    self.context.plan = ExecutionPlan(tasks=[])
            else:
                self.context.plan = ExecutionPlan(tasks=[])

        if not self.context.state_manager:
            self.context.set_state_manager(StateManager(self.context.plan))

        iteration = len(self.context.plan.tasks)
        action_counts: Dict[str, int] = defaultdict(int)
        # Re-populate action counts from history
        for task in self.context.plan.tasks:
            action_sig = f"{(task.action_type or '').strip().lower()}::{task.description.strip().lower()}"
            action_counts[action_sig] += 1

        failure_counts: Dict[str, int] = defaultdict(int)
        last_task_signature: Optional[str] = None
        repeat_same_action: int = 0
        forced_next_task: Optional[Task] = None
        budget_warning_shown: bool = False

        while True:
            iteration += 1
            self.context.set_agent_state("current_iteration", iteration)
            self.context.resource_budget.update_step()
            self.context.resource_budget.tokens_used = get_token_usage().get("total", 0)

            # MANDATORY: Force initial workspace examination on first iteration
            if iteration == 1 and forced_next_task is None:
                # Check if workspace has already been examined
                workspace_examination_ops = ["tree_view", "list_dir", "git_status", "git_diff", "read_file", "inspect", "examine"]
                has_examined = any(
                    any(op in str(log_entry).lower() for op in workspace_examination_ops)
                    for log_entry in completed_tasks_log
                )

                if not has_examined:
                    # Force initial research task before any action
                    forced_next_task = Task(
                        description="Examine current workspace state using tree_view and git_status to understand what already exists",
                        action_type="read"
                    )
                    forced_next_task.task_id = 0
                    print(f"  {colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {colorize('Analyzing workspace structure...', Colors.BRIGHT_BLACK)}")

            if self.context.resource_budget.is_exceeded() and not budget_warning_shown:
                exceeded = self.context.resource_budget.get_exceeded_resources()
                exceeded_str = ", ".join(exceeded)
                print(f"\n⚠️ Resource budget exceeded at step {iteration}: {exceeded_str}")
                print(f"   Usage: {self.context.resource_budget.get_usage_summary()}")
                print(f"   To increase limits, set environment variables:")
                print(f"   - REV_MAX_STEPS (current: {self.context.resource_budget.max_steps})")
                print(f"   - REV_MAX_TOKENS (current: {self.context.resource_budget.max_tokens:,})")
                print(f"   - REV_MAX_SECONDS (current: {self.context.resource_budget.max_seconds:.0f})")
                print(f"   Continuing anyway...")
                budget_warning_shown = True
                # Don't halt - just warn and continue
                # self.context.set_agent_state("no_retry", True)
                # self.context.add_error(f"Resource budget exceeded: {exceeded_str}")
                # return False

            if forced_next_task:
                next_task = forced_next_task
                forced_next_task = None
                print(f"  -> Using injected task: [{next_task.action_type.upper()}] {next_task.description[:80]}")
            else:
                work_summary = "No actions taken yet."
                if completed_tasks_log:
                    # Start with high-level statistics for full session context
                    total_tasks = len(completed_tasks_log)
                    completed_count = sum(1 for log in completed_tasks_log if log.startswith('[COMPLETED]'))
                    failed_count = sum(1 for log in completed_tasks_log if log.startswith('[FAILED]'))

                    work_summary = f"Work Completed So Far ({total_tasks} total tasks: {completed_count} completed, {failed_count} failed):\n"

                    # Add file read/inspection summary FIRST to establish what's been inspected
                    file_read_counts = ledger.get_files_inspected()

                    if file_read_counts:
                        work_summary += "\n📄 Files Already Inspected (DO NOT re-read these files unless absolutely necessary):\n"
                        for filename, count in sorted(file_read_counts.items(), key=lambda x: (-x[1], x[0])):
                            marker = "⚠️ STOP READING" if count >= 2 else "✓"
                            work_summary += f"  {marker} {filename}: read {count}x"
                            if count >= 2:
                                work_summary += " - MUST use [EDIT] or [CREATE] now, NOT another [READ]"
                            work_summary += "\n"
                        work_summary += "\n"

                    # Then provide a condensed view of the history
                    # Keep the first task (usually workspace examination) and the last 5
                    if total_tasks > 6:
                        work_summary += f"\n[History Truncated: showing first task and last 5 of {total_tasks}]\n"
                        work_summary += f"- {completed_tasks_log[0]}\n"
                        work_summary += "  ...\n"
                        work_summary += "\n".join(f"- {log}" for log in completed_tasks_log[-5:])
                    else:
                        work_summary += "All Tasks:\n"
                        work_summary += "\n".join(f"- {log}" for log in completed_tasks_log)

                    if hasattr(self, "debug_logger") and self.debug_logger:
                        self.debug_logger.log("orchestrator", "WORK_SUMMARY_GENERATED", {
                            "history_count": len(completed_tasks_log),
                            "summary_length": len(work_summary),
                            "files_inspected": len(file_read_counts)
                        }, "DEBUG")

                # Calculate repetitive failure notes for the planner
                failure_notes = []

                # Add the most recent failure prominently if the last task failed
                if completed_tasks_log:
                    last_entry = completed_tasks_log[-1]
                    if last_entry.startswith('[FAILED]'):
                        failure_notes.append("❌ LAST TASK FAILED:")
                        failure_notes.append(f"  {last_entry}")
                        failure_notes.append("")

                # P0-2: Add blocked actions to failure notes
                if self.context:
                    blocked_sigs = ledger.get_blocked_action_sigs()
                    if blocked_sigs:
                        failure_notes.append("🚫 BLOCKED ACTIONS (DO NOT propose any of these):")
                        for blocked_sig in blocked_sigs:
                            failure_notes.append(f"  ❌ BLOCKED: [{blocked_sig}]")
                        failure_notes.append("")  # Blank line for readability

                if action_counts:
                    for sig, count in action_counts.items():
                        if count >= 2:
                            failure_notes.append(f"⚠️ REPETITION: Action '[{sig}]' proposed {count}x. It is not progressing. DO NOT REPEAT. Try a different tool or inspect code again.")

                failure_notes_str = "\n".join(failure_notes)
                path_hints = _generate_path_hints(completed_tasks_log)

                # Collect and format pending agent requests (recovery instructions)
                agent_notes = ""
                if self.context and self.context.agent_requests:
                    notes = []
                    for req in self.context.agent_requests:
                        details = req.get("details", {})
                        reason = details.get("reason", "unknown")
                        detailed = details.get("detailed_reason", "")
                        agent = details.get("agent", "Agent")
                        note = f"⚠️ {agent} REQUEST: {reason}"
                        if detailed:
                            note += f"\n  Instruction: {detailed}"
                        notes.append(note)
                    agent_notes = "\n".join(notes)
                    # Clear requests after collecting them for the prompt
                    self.context.agent_requests = []

                next_task = self._determine_next_action(
                    user_request, work_summary, coding_mode, 
                    iteration=iteration, failure_notes=failure_notes_str,
                    path_hints=path_hints, agent_notes=agent_notes
                )

                if not next_task:
                    planner_error = self.context.get_agent_state("planner_error") if self.context else None
                    if isinstance(planner_error, str) and planner_error.strip():
                        self.context.set_agent_state("no_retry", True)
                        print("\n❌ Planner failed to produce a next action (LLM error).")
                        print(f"  Error: {planner_error}")
                        return False
                    
                    # UCCT Anchoring check before declaring victory
                    anchoring_decision = self._evaluate_anchoring(user_request, completed_tasks_log)
                    if anchoring_decision == AnchoringDecision.RE_SEARCH:
                        print("\n  [UCCT] Goal may be achieved, but evidence density is low. Forcing one more search.")
                        forced_next_task = Task(description="Verify the implemented changes by listing the affected files and confirming their content matches the request.", action_type="read")
                        continue
                    elif anchoring_decision == AnchoringDecision.DEBATE:
                        print("\n  [UCCT] High mismatch risk detected. Verifying structural consistency before stopping.")
                        forced_next_task = Task(description="Run a structural consistency check on the modified modules to ensure no unresolved symbols remain.", action_type="analyze")
                        continue

                    # Grounded Completion Check (Bait Density)
                    is_grounded, grounding_msg = self._is_completion_grounded(completed_tasks_log)
                    if not is_grounded:
                        print(f"\n  {colorize(Symbols.INFO, Colors.BRIGHT_BLUE)} {colorize(grounding_msg + ' Forcing verification.', Colors.BRIGHT_BLACK)}")
                        forced_next_task = Task(description="Provide concrete evidence of the work completed by running tests and inspecting the modified files.", action_type="test")
                        continue

                    print(f"\n{colorize(Symbols.CHECK, Colors.BRIGHT_GREEN)} {colorize('Goal achieved.', Colors.BRIGHT_GREEN, bold=True)}")
                    return True

                # FORWARD PROGRESS RULE: Check for redundant actions
                action_sig = f"{next_task.action_type}:{next_task.description}"
                if action_counts[action_sig] >= 2:
                    next_task = self._transform_redundant_action(next_task, action_sig, action_counts[action_sig])

                next_task.task_id = iteration
                try:
                    # Ensure validation_steps are always present so quick_verify can enforce them.
                    next_task.validation_steps = ExecutionPlan().generate_validation_steps(next_task)
                except Exception:
                    pass

                # ACTION LOGGING: Concise and consistent
                action_type = (next_task.action_type or "general").upper()
                print(f"\n{colorize(str(iteration), Colors.BRIGHT_BLACK)}. {colorize(action_type, Colors.BRIGHT_CYAN, bold=True)} {next_task.description}")

            if config.PREFLIGHT_ENABLED:
                ok, sem_msgs = _preflight_correct_action_semantics(next_task)
                for msg in sem_msgs:
                    print(f"  [preflight] {msg}")
                if not ok:
                    self.context.add_error("Preflight failed: " + "; ".join(sem_msgs))
                    completed_tasks_log.append(f"[FAILED] Preflight: {'; '.join(sem_msgs)}")
                    if any("conflicts with write intent" in msg for msg in sem_msgs):
                        self.context.add_agent_request(
                            "REPLAN_REQUEST",
                            {
                                "agent": "Orchestrator",
                                "reason": "preflight read/write mismatch",
                                "detailed_reason": sem_msgs[0],
                            },
                        )
                    sig = f"action_semantics::{(next_task.action_type or '').strip().lower()}::{';'.join(sem_msgs).strip().lower()}"
                    failure_counts[sig] += 1
                    if failure_counts[sig] >= 3:
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating preflight action semantics failure")
                        print("\n" + "=" * 70)
                        print("CIRCUIT BREAKER - PREFLIGHT FAILURE")
                        print("=" * 70)
                        print(f"Repeated preflight failure {failure_counts[sig]}x: {'; '.join(sem_msgs)}")
                        print("Blocking issue: planner is not producing an executable action; refusing to loop.\n")
                        return False
                    continue
                ok, preflight_msgs = _preflight_correct_task_paths(task=next_task, project_root=self.project_root)
                for msg in preflight_msgs:
                    print(f"  [preflight] {msg}")
                if not ok:
                    # Do not execute with missing/ambiguous paths; feed this back into planning.
                    self.context.add_error("Preflight failed: " + "; ".join(preflight_msgs))
                    completed_tasks_log.append(f"[FAILED] Preflight: {'; '.join(preflight_msgs)}")
                    key_msg = preflight_msgs[0] if preflight_msgs else "unknown"
                    sig = f"paths::{(next_task.action_type or '').strip().lower()}::{key_msg.strip().lower()}"
                    failure_counts[sig] += 1
                    if failure_counts[sig] >= 3:
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating preflight path failure")
                        print("\n" + "=" * 70)
                        print("CIRCUIT BREAKER - PREFLIGHT FAILURE")
                        print("=" * 70)
                        print(f"Repeated preflight failure {failure_counts[sig]}x: {key_msg}")
                        print("Blocking issue: planner is not producing an executable action; refusing to loop.\n")
                        return False
                    continue

            # SEMANTIC DEDUPLICATION: Warn if this is a semantically duplicate read task
            action_type_lower = (next_task.action_type or '').lower()
            if action_type_lower in {'read', 'analyze', 'research', 'investigate', 'review'}:
                if _is_semantically_duplicate_task(
                    next_task.description,
                    next_task.action_type,
                    completed_tasks_log,
                    threshold=0.65  # 65% similarity threshold
                ):
                    print("  [semantic-dedup] Warning: similar read already completed.")

            # Append to cumulative plan instead of overwriting
            if next_task not in self.context.plan.tasks:
                self.context.plan.tasks.append(next_task)

            if self.context.state_manager:
                self.context.state_manager.on_task_started(next_task)

            # P0-2 & P0-3: Anti-loop with blocked actions and streak-based circuit breaker
            action_sig = f"{(next_task.action_type or '').strip().lower()}::{next_task.description.strip().lower()}"
            action_counts[action_sig] += 1  # Total count (for statistics)

            # P0-3: Track consecutive repetitions (streak-based)
            if action_sig == last_task_signature:
                repeat_same_action += 1
            else:
                repeat_same_action = 1  # Reset streak
                last_task_signature = action_sig

            # Get or initialize blocked_action_sigs from context
            if self.context:
                blocked_sigs = self.context.get_agent_state("blocked_action_sigs", set())
                if not isinstance(blocked_sigs, set):
                    blocked_sigs = set()
            else:
                blocked_sigs = set()

            # Check if this action is blocked
            if action_sig in blocked_sigs:
                print(f"  [blocked-action] This action is blocked due to previous repetition: {action_sig[:100]}...")
                # Auto-rewrite to a diagnostic fallback
                next_task.action_type = "analyze"
                next_task.description = (
                    f"BLOCKED: Previous approach failed repeatedly. "
                    f"Instead, analyze the root cause by running diagnostic tests or examining related code. "
                    f"Do NOT repeat: [{action_sig[:80]}...]"
                )
                print(f"  [blocked-action] Rewriting to: {next_task.description[:100]}...")
                # Reset streak since we rewrote the task
                repeat_same_action = 1
                last_task_signature = f"analyze::{next_task.description.strip().lower()}"

            # P0-3: Circuit breaker based on CONSECUTIVE streak, not total count
            if repeat_same_action >= 3:
                # Before failing, check if the goal was actually achieved
                action_lower = (next_task.action_type or "").lower()
                is_read_action = action_lower in {"read", "analyze", "research", "investigate", "review"}

                if is_read_action:
                    goal_achieved = _check_goal_likely_achieved(user_request, completed_tasks_log)
                    if goal_achieved:
                        print("\n" + "=" * 70)
                        print("CIRCUIT BREAKER - GOAL ACHIEVED")
                        print("=" * 70)
                        print(f"Repeated verification action {action_counts[action_sig]}x, but goal appears achieved.")
                        print("Forcing successful completion.\n")
                        return True

                self.context.set_agent_state("no_retry", True)
                self.context.add_error(f"Circuit breaker: repeating action '{next_task.action_type}'")
                print("\n" + "=" * 70)
                print("🛑 CIRCUIT BREAKER TRIGGERED: REPEATED ACTION")
                print("=" * 70)
                print(f"Repeated action {repeat_same_action}x consecutively (total {action_counts[action_sig]}x): [{(next_task.action_type or '').upper()}] {next_task.description}")
                
                # Enhanced circuit-breaker message
                recent_ledger_actions = ledger.get_recent_actions(5)
                last_verification = ledger.get_last_verification_status()
                blocked_sigs = ledger.get_blocked_action_sigs()
                
                print("\n--- DEBUG CONTEXT ---")
                print(f"Action Signature: {action_sig}")
                
                if recent_ledger_actions:
                    print("\nLast 5 Tool Calls:")
                    for i, a in enumerate(recent_ledger_actions, 1):
                        print(f"  {i}. {a['tool']}({json.dumps(a['arguments'])}) -> {a['status']}")
                
                if last_verification:
                    print("\nLast Verification Status:")
                    print(json.dumps(last_verification, indent=2)[:500])
                
                if blocked_sigs:
                    print("\nBlocked Signatures:")
                    for sig in blocked_sigs:
                        print(f"  - {sig}")
                
                print("\n---------------------\n")
                
                print("Blocking issue: planner is not making forward progress; refusing to repeat the same step.")
                return False
            if (
                config.LOOP_GUARD_ENABLED
                and action_counts[action_sig] == 2
                and (next_task.action_type or "").lower() in {"read", "analyze", "research"}
            ):
                print("  [loop-guard] Repeated READ/ANALYZE detected; checking if goal is achieved.")

                # P0-2: Block this action from being proposed again
                blocked_sigs.add(action_sig)
                if self.context:
                    self.context.set_agent_state("blocked_action_sigs", blocked_sigs)
                print(f"  [loop-guard] Blocked action signature: {action_sig[:100]}...")

                # P0-4: Track which files are being read repeatedly (language-agnostic)
                # Support common file extensions: Python, JS, TS, Vue, JSON, YAML, Markdown, etc.
                read_file_pattern = r'(?:\.\/)?([a-zA-Z0-9_/\\\-\.]+\.(?:py|js|ts|tsx|jsx|vue|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1))'
                recent_read_files = []
                for task in reversed(completed_tasks[-5:]):  # Look at last 5 completed Task objects
                    if (task.action_type or "").lower() in {"read", "analyze", "research"}:
                        matches = re.findall(read_file_pattern, task.description or "", re.IGNORECASE)
                        recent_read_files.extend(matches)

                # Check if the same file has been read 3+ times
                from collections import Counter
                file_counts = Counter(recent_read_files)
                most_read_file, read_count = file_counts.most_common(1)[0] if file_counts else (None, 0)

                if read_count >= 3:
                    print(f"  [loop-guard] File '{most_read_file}' has been read {read_count} times - suggesting alternative approach.")
                    next_task.action_type = "debug"
                    next_task.description = (
                        f"The file {most_read_file} has been read {read_count} times without progress. "
                        f"Instead of reading it again, use run_python_diagnostic to test the actual runtime behavior. "
                        f"For example, test module imports, inspect object attributes, or verify auto-registration logic. "
                        f"This will reveal runtime issues that static code reading cannot detect."
                    )
                    print(f"  [loop-guard] Injecting diagnostic suggestion: {next_task.description[:100]}...")
                    return False  # Continue execution with the diagnostic task

                # Check if the goal appears to be achieved
                goal_achieved = _check_goal_likely_achieved(user_request, completed_tasks_log)
                if goal_achieved:
                    # Don't force completion without verification - inject verification task instead
                    print("  [loop-guard] Goal appears achieved - verifying completion before ending execution.")

                    # Check if we've already attempted final verification
                    loop_guard_verification_attempted = self.context.agent_state.get("loop_guard_verification_attempted", False)

                    if not loop_guard_verification_attempted:
                        # First time: inject a verification task
                        self.context.set_agent_state("loop_guard_verification_attempted", True)
                        next_task.action_type = "read"
                        next_task.description = (
                            "Perform final verification: list the target directory to confirm all expected files exist, "
                            "then run a quick syntax check (python -m compileall) and import test to ensure the refactoring works correctly."
                        )
                        print(f"  [loop-guard] Injecting final verification task: {next_task.description[:80]}...")
                    else:
                        # Already attempted verification - now we can safely complete
                        print("  [loop-guard] Verification already attempted - forcing completion.")
                        return True
                else:
                    # P0-5: Replace generic list_dir fallback with targeted, progress-making actions
                    target_path = _extract_file_path_from_description(next_task.description)
                    if target_path:
                        # Determine file type to suggest appropriate validation
                        file_ext = target_path.split('.')[-1].lower() if '.' in target_path else ''

                        if file_ext in ['js', 'ts', 'jsx', 'tsx', 'vue']:
                            # Frontend file - suggest build/lint
                            next_task.action_type = "test"
                            next_task.description = (
                                f"Instead of re-reading {target_path}, validate it by running: "
                                f"1) npm run lint (if available) to check syntax, or "
                                f"2) npm run build to verify it compiles correctly. "
                                f"This will reveal actual issues rather than just reading the same file again."
                            )
                        elif file_ext in ['py']:
                            # Python file - suggest syntax check or relevant tests
                            next_task.action_type = "test"
                            next_task.description = (
                                f"Instead of re-reading {target_path}, validate it by running: "
                                f"1) python -m py_compile {target_path} to check syntax, or "
                                f"2) Run relevant unit tests for this module. "
                                f"This will reveal actual issues rather than static reading."
                            )
                        else:
                            # Generic file - analyze using cached contents
                            next_task.action_type = "analyze"
                            next_task.description = (
                                f"Instead of re-reading {target_path}, analyze the cached file contents to: "
                                f"1) Summarize what the file currently contains, "
                                f"2) Identify what changes are still needed to satisfy acceptance criteria, "
                                f"3) Determine if the implementation is actually complete or if specific issues remain."
                            )
                    else:
                        # No specific file - suggest running tests or verification
                        next_task.action_type = "test"
                        next_task.description = (
                            "Instead of re-reading files, validate the current state by running tests: "
                            "Use pytest for Python code, npm test for JavaScript, or appropriate linting/build commands. "
                            "This will reveal actual blocking issues that need to be fixed."
                        )
                    print(f"  [loop-guard] Injecting targeted fallback: {next_task.description[:100]}...")

            # Fast-path: don't dispatch a no-op create_directory if it already exists.
            if (next_task.action_type or "").lower() == "create_directory":
                try:
                    desc = next_task.description or ""
                    candidate = ""

                    # Prefer explicit "directory <path>" phrasing.
                    m = re.search(r"directory\s+([^\s]+)", desc, flags=re.IGNORECASE)
                    if m:
                        candidate = m.group(1)

                    # Windows absolute path (drive letter).
                    if not candidate:
                        m = re.search(r"([A-Za-z]:\\\\[^\s]+)", desc)
                        if m:
                            candidate = m.group(1)

                    # Fallback: first path-ish token (includes ':' for Windows).
                    if not candidate:
                        m = re.search(r'([A-Za-z0-9_:\\-./\\\\]+)', desc)
                        if m:
                            candidate = m.group(1)

                    candidate = candidate.strip().strip('"').strip("'")
                    if candidate:
                        resolved = resolve_workspace_path(candidate, purpose="check create_directory preflight")
                        if resolved.abs_path.exists() and resolved.abs_path.is_dir():
                            next_task.status = TaskStatus.COMPLETED
                            next_task.result = json.dumps(
                                {
                                    "skipped": True,
                                    "reason": "directory already exists",
                                    "directory_abs": str(resolved.abs_path),
                                    "directory_rel": resolved.rel_path.replace("\\", "/"),
                                }
                            )
                            log_entry = f"[COMPLETED] (skipped) {next_task.description}"
                            completed_tasks_log.append(log_entry)
                            self.context.work_history = completed_tasks_log
                            print(f"  ✓ {log_entry}")
                            continue
                except Exception:
                    pass

            # STEP 2: EXECUTE
            execution_success = self._dispatch_to_sub_agents(self.context, next_task)

            # STEP 3: VERIFY - This is the critical addition
            verification_result = None
            if execution_success:
                # Only verify actions we have a handler for; otherwise skip verification noise.
                verifiable_actions = {
                    "refactor",
                    "add",
                    "create",
                    "edit",
                    "create_directory",
                    "test",
                    "read",
                    "analyze",
                    "research",
                    "investigate",
                }
                action_type = (next_task.action_type or "").lower()
                if action_type in verifiable_actions:
                    print(f"  {colorize('◌', Colors.BRIGHT_BLACK)} {colorize('Verifying...', Colors.BRIGHT_BLACK)}")
                    verification_result = verify_task_execution(next_task, self.context)
                    # Don't print the raw result object, just handle the outcome
                else:
                    verification_result = VerificationResult(
                        passed=True,
                        message="Verification skipped",
                        details={"action_type": action_type, "skipped": True},
                    )

                # If tests are being skipped because nothing has changed since a failure,
                # don't treat this as a verification failure (it causes loops). Instead,
                # bias planning toward a code-changing step.
                if (
                    (next_task.action_type or "").lower() == "test"
                    and verification_result.passed
                    and isinstance(getattr(verification_result, "details", None), dict)
                    and verification_result.details.get("blocked") is True
                ):
                    self.context.set_agent_state("tests_blocked_no_changes", True)
                    print(f"  {colorize(Symbols.WARNING, Colors.BRIGHT_YELLOW)} {colorize('Skipped re-running tests: no code changes detected.', Colors.BRIGHT_BLACK)}")

                if not verification_result.passed:
                    # Verification failed - mark task as failed and mark for re-planning
                    next_task.status = TaskStatus.FAILED
                    next_task.error = _format_verification_feedback(verification_result)
                    execution_success = False
                    
                    # Display detailed debug information
                    self._handle_verification_failure(verification_result)

                    # Anti-loop: stop if the same verification failure repeats.
                    first_line = verification_result.message.splitlines()[0].strip() if verification_result.message else ""
                    failure_sig = f"{(next_task.action_type or '').lower()}::{first_line}"
                    failure_counts[failure_sig] += 1

                    # Track syntax repair attempts separately
                    syntax_repair_key = f"syntax_repair::{failure_sig}"
                    syntax_repair_attempts = self.context.agent_state.get(syntax_repair_key, 0)

                    if failure_counts[failure_sig] >= 3:
                        # SYNTAX RECOVERY: Check if this is a syntax error
                        is_syntax_error = _check_syntax_error_in_verification(verification_result)

                        if is_syntax_error and syntax_repair_attempts < 5:
                            # Enter syntax repair mode - give LLM focused attempts to fix
                            print(f"  {colorize(Symbols.WARNING, Colors.BRIGHT_YELLOW)} {colorize('Syntax error detected. Entering focused repair mode (attempt ' + str(syntax_repair_attempts + 1) + '/5)', Colors.BRIGHT_WHITE)}")

                            # Increment syntax repair counter
                            self.context.set_agent_state(syntax_repair_key, syntax_repair_attempts + 1)

                            # Create a focused syntax repair task
                            syntax_repair_task = _create_syntax_repair_task(next_task, verification_result)

                            # Reset general failure count to allow more attempts
                            failure_counts[failure_sig] = 0

                            # Replace the failed task with the repair task
                            forced_next_task = syntax_repair_task
                            iteration -= 1  # Don't count this as a regular iteration

                        elif is_syntax_error and syntax_repair_attempts >= 5:
                            # Exhausted syntax repair attempts - try auto-revert as last resort
                            print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Repair exhausted. Reverting changes...', Colors.BRIGHT_WHITE)}")

                            reverted_files = _attempt_git_revert_for_syntax_errors(next_task)
                            if reverted_files:
                                print(f"  {colorize(Symbols.CHECK, Colors.BRIGHT_GREEN)} {colorize('Auto-reverted: ' + ', '.join(reverted_files), Colors.BRIGHT_BLACK)}")
                                # Clear syntax repair counter
                                self.context.set_agent_state(syntax_repair_key, 0)
                                return False  # Stop execution, but code is in working state
                            else:
                                print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Auto-revert failed. Manual intervention required.', Colors.BRIGHT_RED)}")

                        # Non-syntax errors or revert failed - use original circuit breaker
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating verification failure")
                        print(f"  {colorize(Symbols.CROSS, Colors.BRIGHT_RED)} {colorize('Circuit Breaker: repeated failure ' + str(failure_counts[failure_sig]) + 'x. Stopping loop.', Colors.BRIGHT_RED)}")
                        return False

                    # Try to decompose the failed task into more granular steps.
                    # Decomposing test failures is usually counterproductive (it tends to produce vague edits);
                    # let the planner pick a focused debug/fix step instead.
                    if verification_result.should_replan and (next_task.action_type or "").lower() != "test":
                        decomposed_task = self._decompose_extraction_task(next_task)
                        if decomposed_task:
                            print(f"  [RETRY] Using decomposed task for next iteration")
                            forced_next_task = decomposed_task
                            iteration -= 1  # Don't count failed task as an iteration
                else:
                    # If we've just verified a successful test and no code has changed since,
                    # treat this as "goal achieved" to prevent endless test loops.
                    if (next_task.action_type or "").lower() == "test":
                        last_test_rc = self.context.agent_state.get("last_test_rc")
                        last_test_iteration = self.context.agent_state.get("last_test_iteration", -1)
                        last_code_change_iteration = self.context.agent_state.get("last_code_change_iteration", -1)
                        if (
                            last_test_rc == 0
                            and isinstance(last_test_iteration, int)
                            and isinstance(last_code_change_iteration, int)
                            and last_code_change_iteration != -1
                            and last_code_change_iteration <= last_test_iteration
                        ):
                            print("\n[OK] Verification passed and no code changed since; stopping to avoid repeated tests.")
                            return True

            action_type = (next_task.action_type or "").lower()
            if next_task.status == TaskStatus.COMPLETED and action_type in {"edit", "add", "refactor", "create_directory"}:
                # Check if this was an actual code change or just a cosmetic/no-op edit
                # Look at verification details or task result to confirm real changes
                is_real_change = True

                # Check verification details for evidence of actual changes
                if hasattr(verification_result, 'details') and isinstance(verification_result.details, dict):
                    # For edits: check if replace_in_file actually replaced something
                    # Check tool events from task
                    events = getattr(next_task, "tool_events", None) or []
                    for ev in reversed(list(events)):
                        tool = str(ev.get("tool") or "").lower()
                        if tool in {"replace_in_file", "write_file", "apply_patch"}:
                            raw_result = ev.get("raw_result")
                            if isinstance(raw_result, str):
                                try:
                                    import json
                                    payload = json.loads(raw_result)
                                    if isinstance(payload, dict):
                                        # Check if no actual changes were made
                                        replaced = payload.get("replaced", 1)  # Default to 1 (assume change)
                                        if replaced == 0:
                                            is_real_change = False
                                            print(f"  [!] Edit task completed but made no actual changes (cosmetic only)")
                                            break
                                except Exception:
                                    pass

                if is_real_change:
                    self.context.set_agent_state("last_code_change_iteration", iteration)
                    self.context.set_agent_state("tests_blocked_no_changes", False)
                else:
                    print(f"  [!] Skipping last_code_change_iteration update - no real changes detected")

            # STEP 4: REPORT
            if next_task.status == TaskStatus.COMPLETED:
                if self.context.state_manager:
                    self.context.state_manager.on_task_completed(next_task)
            elif next_task.status == TaskStatus.FAILED:
                if self.context.state_manager:
                    self.context.state_manager.on_task_failed(next_task)

            status_tag = f"[{next_task.status.name}]"
            log_entry = f"{status_tag} {next_task.description}"
            
            error_detail = ""
            if next_task.status == TaskStatus.FAILED and next_task.error:
                error_detail = str(next_task.error)
            
            # Add a summary of the tool output to the log
            output_detail = ""
            if hasattr(next_task, 'tool_events') and next_task.tool_events:
                # Summarize the result of the last tool event
                event = next_task.tool_events[-1]
                tool_output = event.get('raw_result')
                if isinstance(tool_output, str):
                    summary = tool_output.strip()
                    # If the error is already in the summary, don't repeat it
                    if error_detail and error_detail in summary:
                        output_detail = summary
                        error_detail = ""
                    else:
                        output_detail = summary
                    
                    if len(output_detail) > 300:
                        output_detail = output_detail[:300] + '...'

            if error_detail:
                log_entry += f" | Reason: {error_detail}"
            if output_detail:
                log_entry += f" | Output: {output_detail}"
            
            if verification_result and not verification_result.passed:
                # Only add verification message if it's not redundant with error/output
                v_msg = verification_result.message
                if v_msg and v_msg not in log_entry:
                    log_entry += f" | Verification: {v_msg}"

            completed_tasks_log.append(log_entry)
            completed_tasks.append(next_task)  # Track actual Task object
            self.context.work_history = completed_tasks_log  # Sync to context for logging/visibility
            self.context.save_history()

            try:
                recent = self.context.agent_state.get("recent_tasks", [])
                if not isinstance(recent, list):
                    recent = []
                recent.append(f"{next_task.action_type or '?'}: {next_task.description}")
                self.context.agent_state["recent_tasks"] = recent[-8:]
            except Exception:
                pass

            # Filter output from console display unless debug is enabled
            display_entry = log_entry
            if not self.debug_logger.enabled and "| Output:" in display_entry:
                # Split by output marker
                parts = display_entry.split(" | Output:")
                base_part = parts[0]
                
                # Check if we need to preserve verification part which comes after output
                verification_part = ""
                if len(parts) > 1 and " | Verification:" in parts[1]:
                    # Extract verification part from the second chunk
                    v_split = parts[1].split(" | Verification:", 1)
                    if len(v_split) > 1:
                        verification_part = " | Verification:" + v_split[1]
                
                display_entry = base_part + verification_part

            print(f"  {'✓' if next_task.status == TaskStatus.COMPLETED else '✗'} {display_entry}")

            self.context.update_repo_context()
            clear_analysis_caches()

        return False

    def _handle_verification_failure(self, verification_result: VerificationResult):
        """Handle and display detailed information about verification failures."""
        print(f"\n{colorize('  ' + Symbols.CROSS + ' Verification Details', Colors.BRIGHT_RED, bold=True)}")

        # Display main message (which includes issue descriptions)
        if verification_result.message:
            print(f"    {colorize(verification_result.message, Colors.BRIGHT_RED)}")

        # Display debug information if available
        if verification_result.details and "debug" in verification_result.details:
            debug_info = verification_result.details["debug"]
            for key, value in debug_info.items():
                print(f"    {colorize(key + ':', Colors.BRIGHT_BLACK)} {value}")

        # Display strict/validation command outputs (compileall/pytest/etc)
        details = verification_result.details or {}
        for block_key in ("strict", "validation"):
            block = details.get(block_key)
            if not isinstance(block, dict) or not block:
                continue
            for label, res in block.items():
                if not isinstance(res, dict):
                    continue
                rc = res.get("rc")
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()
                
                if rc is not None and rc != 0:
                    print(f"    {colorize('[' + label + '] failed (rc=' + str(rc) + ')', Colors.BRIGHT_YELLOW)}")
                    if stdout:
                        for line in str(stdout).splitlines()[-5:]: # Only show last 5 lines
                            print(f"      {colorize('stdout:', Colors.BRIGHT_BLACK)} {line}")
                    if stderr:
                        for line in str(stderr).splitlines()[-5:]:
                            print(f"      {colorize('stderr:', Colors.BRIGHT_BLACK)} {line}")

        print("\n" + "=" * 70)
        print("NEXT ACTION: Re-planning with different approach...")
        print("=" * 70 + "\n")

    def _dispatch_to_sub_agents(self, context: RevContext, task: Optional[Task] = None) -> bool:
        """Dispatches tasks to appropriate sub-agents."""
        if task is None:
            if not context.plan or not context.plan.tasks:
                return False
            task = context.plan.tasks[0]

        if task.status == TaskStatus.COMPLETED:
            return True

        # Guardrail: if the planner accidentally schedules a file creation as a directory creation
        # (common in decomposed tasks like "create __init__.py"), coerce to `add` so we can use write_file.
        if (task.action_type or "").lower() == "create_directory" and re.search(r"\.py\b", task.description, re.IGNORECASE):
            task.action_type = "add"

        # Normalize action types (aliases + fuzzy typos) before registry lookup.
        task.action_type = normalize_action_type(
            task.action_type,
            available_actions=AgentRegistry.get_registered_action_types(),
        )

        if task.action_type not in AgentRegistry.get_registered_action_types():
            task.status = TaskStatus.FAILED
            task.error = f"No agent available to handle action type: '{task.action_type}'"
            return False

        task.status = TaskStatus.IN_PROGRESS
        try:
            # Build a focused context snapshot (selection pipeline); agents will also
            # use this same pipeline when selecting tools and composing prompts.
            if self._context_builder is None:
                self._context_builder = ContextBuilder(self.project_root)
            try:
                tool_names = [t.get("function", {}).get("name") for t in get_available_tools() if isinstance(t, dict)]
                bundle = self._context_builder.build(
                    query=f"{context.user_request}\n\n{task.action_type}: {task.description}",
                    tool_universe=get_available_tools(),
                    tool_candidates=[n for n in tool_names if isinstance(n, str)],
                    top_k_tools=7,
                )
                context.agent_insights["context_builder"] = {
                    "selected_tools": [t.name for t in bundle.selected_tool_schemas],
                    "selected_code": [c.location for c in bundle.selected_code_chunks],
                    "selected_docs": [d.location for d in bundle.selected_docs_chunks],
                }
            except Exception:
                # Best-effort: never fail dispatch due to context retrieval.
                pass

            agent = AgentRegistry.get_agent_instance(task.action_type)
            result = agent.execute(task, context)

            # Global recovery: if an agent returns a tool-call payload as plain text, execute it here.
            # This avoids "death spirals" where the model can describe a tool call but fails to emit
            # structured tool_calls for the runtime adapter.
            if isinstance(result, str):
                try:
                    allowed = [
                        t.get("function", {}).get("name")
                        for t in get_available_tools()
                        if isinstance(t, dict)
                    ]
                    executed = maybe_execute_tool_call_from_text(result, allowed_tools=[n for n in allowed if isinstance(n, str)])
                except Exception:
                    executed = None

                if executed is not None:
                    print(f"  -> Recovered tool call from text output: {executed.tool_name}")
                    result = build_subagent_output(
                        agent_name=agent.__class__.__name__,
                        tool_name=executed.tool_name,
                        tool_args=executed.tool_args,
                        tool_output=executed.tool_output,
                        context=context,
                        task_id=task.task_id,
                    )

            task.result = result
            try:
                _append_task_tool_event(task, result)
            except Exception:
                pass
            # If sub-agent reported tool error, fail the task and replan.
            try:
                if isinstance(result, str):
                    parsed = json.loads(result)
                    ev = None
                    if isinstance(parsed, dict):
                        ev_list = parsed.get("evidence") or []
                        if isinstance(ev_list, list) and ev_list:
                            ev = ev_list[0]
                    if ev and ev.get("result") == "error":
                        task.status = TaskStatus.FAILED
                        task.error = ev.get("summary") or "tool error"
                        return False
            except Exception:
                pass
            if isinstance(result, str) and (result.startswith("[RECOVERY_REQUESTED]") or result.startswith("[FINAL_FAILURE]") or result.startswith("[USER_REJECTED]")):
                if result.startswith("[RECOVERY_REQUESTED]"):
                    task.status = TaskStatus.FAILED
                    task.error = result[len("[RECOVERY_REQUESTED]"):]
                elif result.startswith("[FINAL_FAILURE]"):
                    task.status = TaskStatus.FAILED
                    task.error = result[len("[FINAL_FAILURE]"):]
                    context.add_error(f"Task {task.task_id}: {task.error}")
                else:
                    task.status = TaskStatus.STOPPED
                    task.error = result[len("[USER_REJECTED]"):]
                return False
            else:
                task.status = TaskStatus.COMPLETED
                try:
                    # If the agent produced tool evidence, it may include artifact refs.
                    if isinstance(task.result, str) and "outside allowed workspace roots" in task.result.lower():
                        maybe_record_known_failure_from_error(error_text=task.result)
                except Exception:
                    pass
                return True
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            context.add_error(f"Sub-agent execution exception for task {task.task_id}: {e}")
            return False
    
    def _emit_run_metrics(self, plan: Optional[ExecutionPlan], result: OrchestratorResult, budget: ResourceBudget):
        if config.EXECUTION_MODE != 'sub-agent':
            print(f"\n🔥 Emitting run metrics...")
    
    def _display_summary(self, result: OrchestratorResult):
        """Display a final execution summary."""
        if config.EXECUTION_MODE == 'sub-agent':
            # Sub-agent mode has its own summary logic or is more streamlined
            return

        print("\n" + "=" * 60)
        print("ORCHESTRATOR - EXECUTION SUMMARY")
        print("=" * 60)
        
        status = "SUCCESS" if result.success else "FAILED"
        print(f"Status: {status}")
        print(f"Phase Reached: {result.phase_reached.value}")
        print(f"Time Taken: {result.execution_time:.2f} seconds")
        
        # Display UCCT Anchoring metrics if available in insights
        if "anchoring_evaluation" in self.context.agent_insights:
            metrics = self.context.agent_insights["anchoring_evaluation"]
            print("\n📊 Measurable Coordination (UCCT):")
            print(f"   Anchoring Score: {metrics.get('raw_score', 0):.2f}")
            print(f"   Evidence Density: {metrics.get('evidence_density', 0):.2f}")
            print(f"   Mismatch Risk: {metrics.get('mismatch_risk', 0)}")
            print(f"   Anchor Budget (k): {metrics.get('anchor_budget', 0)}")
            print(f"   Decision: {metrics.get('decision', 'N/A')}")

        if result.plan:
            print(f"\nTasks: {result.plan.get_summary()}")
            
        if result.errors:
            print("\nErrors:")
            for err in result.errors:
                print(f"  - {err}")
        
        print("=" * 60)

def run_orchestrated(
    user_request: str,
    project_root: Path,
    enable_learning: bool = False,
    enable_research: bool = True,
    enable_review: bool = True,
    enable_validation: bool = True,
    review_strictness: str = "moderate",
    enable_action_review: bool = False,
    enable_auto_fix: bool = False,
    parallel_workers: int = 1,
    auto_approve: bool = True,
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT,
    validation_mode: Literal["none", "smoke", "targeted", "full"] = "targeted",
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES,
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES,
    validation_retries: int = MAX_VALIDATION_RETRIES,
    enable_prompt_optimization: bool = True,
    auto_optimize_prompt: bool = False,
    enable_context_guard: bool = True,
    context_guard_interactive: bool = True,
    context_guard_threshold: float = 0.3,
    resume: bool = False,
) -> OrchestratorResult:
    config_obj = OrchestratorConfig(
        enable_learning=enable_learning,
        enable_research=enable_research,
        enable_review=enable_review,
        enable_validation=enable_validation,
        review_strictness=ReviewStrictness(review_strictness),
        enable_action_review=enable_action_review,
        enable_auto_fix=enable_auto_fix,
        parallel_workers=parallel_workers,
        auto_approve=auto_approve,
        research_depth=research_depth,
        validation_mode=validation_mode,
        orchestrator_retries=orchestrator_retries,
        plan_regen_retries=plan_regen_retries,
        validation_retries=validation_retries,
        enable_prompt_optimization=enable_prompt_optimization,
        auto_optimize_prompt=auto_optimize_prompt,
        enable_context_guard=enable_context_guard,
        context_guard_interactive=context_guard_interactive,
        context_guard_threshold=context_guard_threshold,
    )

    orchestrator = Orchestrator(project_root, config_obj)
    return orchestrator.execute(user_request, resume=resume)

