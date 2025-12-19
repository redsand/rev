"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.

Implements Resource-Aware Optimization pattern to track and enforce budgets.
"""

import os
import json
import time
import traceback
from typing import Dict, Any, List, Optional, Literal
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
        if "/lib/" in f"/{p}/":
            score += 10
        if "/src/" in f"/{p}/":
            score += 8
        if "/app/" in f"/{p}/":
            score += 6
        if "/tests/" in f"/{p}/":
            score -= 5
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
    # matching "analy" inside "analysts").
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


def _preflight_correct_task_paths(*, task: Task, project_root: Path) -> tuple[bool, List[str]]:
    """Best-effort path correction for lightweight planner outputs.

    Returns:
        (ok_to_execute, messages)
    """
    desc = task.description or ""
    messages: List[str] = []
    action = (task.action_type or "").strip().lower()
    read_actions = {"read", "analyze", "review", "research", "investigate"}

    # Focus on Python path mistakes first.
    # Keep this regex intentionally simple to avoid escaping bugs.
    candidates = sorted(
        set(
            re.findall(
                r'([A-Za-z]:[\\/][^\s"\'`]+\.py(?:\.bak)?\b|(?:\./)?[A-Za-z0-9_./\\-]+\.py(?:\.bak)?\b)',
                desc,
            )
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
        # Avoid truncating "__init__.py" -> "__init__" in later heuristics.
        if normalized.lower().endswith("/__init__.py"):
            continue

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

        matches: List[str] = []
        for bn in basenames:
            matches.extend(_find_workspace_matches_by_basename(root=project_root, basename=bn))
        matches = sorted(set(matches))
        chosen = _choose_best_path_match(original=normalized, matches=matches)
        if chosen:
            # Replace occurrences of the raw token as well as its normalized variant.
            if raw in desc:
                desc = desc.replace(raw, chosen)
            if normalized in desc:
                desc = desc.replace(normalized, chosen)
            messages.append(f"corrected missing path '{raw}' -> '{chosen}'")
            existing_any += 1
            continue

        if matches:
            missing_unresolved.append(f"ambiguous missing path '{raw}' (matches={matches[:5]})")
        else:
            missing_unresolved.append(f"missing path '{raw}' (no matches found)")

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

    def execute(self, user_request: str) -> OrchestratorResult:
        """Execute a task through the full agent pipeline."""
        aggregate_errors: List[str] = []
        last_result: Optional[OrchestratorResult] = None
        self.context = RevContext(user_request=user_request)
        ensure_project_memory_file()
        # Keep repo_context minimal; sub-agents will retrieve focused context via ContextBuilder.
        self.context.repo_context = ""

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
            "Important import strategy note (avoid churn):\n"
            "- If a refactor split creates a package (directory with __init__.py exports), update call sites/tests to\n"
            "  import from the package exports (e.g., `from lib.analysts import BreakoutAnalyst`).\n"
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

        # Try to parse the decomposed task format [ACTION_TYPE] description
        match = re.match(r"[\s]*\[(.*?)\]\s*(.*)", response_content)
        if match:
            action_type = normalize_action_type(
                match.group(1),
                available_actions=AgentRegistry.get_registered_action_types(),
            )
            description = match.group(2).strip()
            print(f"\n  [DECOMPOSITION] LLM suggested decomposition:")
            print(f"    Action: {action_type}")
            print(f"    Task: {description}")
            return Task(description=description, action_type=action_type)
        else:
            # If LLM didn't follow format, create a generic refactor task with its suggestion
            print(f"\n  [DECOMPOSITION] LLM suggestion: {response_content[:100]}")
            return Task(
                description=response_content,
                action_type="refactor"
            )

    def _determine_next_action(self, user_request: str, work_summary: str, coding_mode: bool) -> Optional[Task]:
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
        
        prompt = (
            f"Original Request: {user_request}\n\n"
            f"{work_summary}\n\n"
            f"{blocked_note}"
            "Based on the work completed, what is the single next most important action to take? "
            "If a previous action failed, propose a different action to achieve the goal.\n"
            "\n"
            "ACTION SEMANTICS (critical):\n"
            "- Use [READ] or [ANALYZE] when the next step is inspection only (open files, search, inventory imports, understand structure).\n"
            "- Use [EDIT]/[ADD]/[CREATE_DIRECTORY]/[REFACTOR] only when you will perform a repo-changing tool call in this step.\n"
            "- If unsure whether a path exists, choose [READ] first to locate the correct file path(s).\n"
            "\n"
            "Constraints to avoid duplicating work:\n"
            "- Do not propose repeating a step that is already complete (e.g., do not re-create a directory that exists).\n"
            "- If you are going to use `split_python_module_classes`, do not hand-author `lib/analysts/__init__.py` first; let the tool generate it.\n"
            "- After `split_python_module_classes` runs, the source file is renamed to `*.py.bak`. Do not try to edit the old `*.py` path.\n"
            "- If a source file was split into a package (directory with __init__.py) and the original single-file path no longer exists, do NOT propose edits to that missing file; operate on the package files that actually exist.\n"
            "- If the code was split into a package with __init__.py exports, prefer package-export imports at call sites.\n"
            "- Avoid replacing `from pkg import *` with dozens of per-module imports; only import names actually used.\n"
            "- Prefer `from lib.analysts import SomeAnalyst` over `from lib.analysts.some_file import SomeAnalyst` when `lib/analysts/__init__.py` exports it.\n"
            f"You MUST choose one of the following action types: {available_actions}\n"
            "Your response should be a single line in the format: [ACTION_TYPE] description of the action.\n"
            "Example: [EDIT] refactor the authentication middleware to use the new session manager.\n"
            "If the goal has been achieved, respond with only the text 'GOAL_ACHIEVED'."
        )
        
        response_data = ollama_chat([{"role": "user", "content": prompt}])

        if "error" in response_data:
            print(f"  ❌ LLM Error in lightweight planner: {response_data['error']}")
            if self.context:
                self.context.set_agent_state("planner_error", response_data["error"])
                self.context.add_error(f"Lightweight planner LLM error: {response_data['error']}")
            return None

        response_content = response_data.get("message", {}).get("content", "")
        if not response_content or response_content.strip().upper() == "GOAL_ACHIEVED":
            return None
        
        match = re.match(r"[\s]*\[(.*?)\]\s*(.*)", response_content.strip())
        if not match:
            return Task(description=response_content.strip(), action_type="general")
        
        action_type = normalize_action_type(
            match.group(1),
            available_actions=available_actions,
        )
        description = match.group(2).strip()
        return Task(description=description, action_type=action_type)

    def _continuous_sub_agent_execution(self, user_request: str, coding_mode: bool) -> bool:
        """Executes a task by continuously calling a lightweight planner for the next action.

        Implements the proper workflow:
        1. Plan next action
        2. Execute action
        3. VERIFY execution actually succeeded
        4. Report results
        5. Re-plan if needed
        """
        print("\n" + "=" * 60)
        print("CONTINUOUS SUB-AGENT MODE (REPL-Style with Verification)")
        print("=" * 60)

        completed_tasks_log: List[str] = []
        iteration = 0
        action_counts: Dict[str, int] = defaultdict(int)
        failure_counts: Dict[str, int] = defaultdict(int)

        while True:
            iteration += 1
            self.context.set_agent_state("current_iteration", iteration)
            self.context.resource_budget.update_step()
            if self.context.resource_budget.is_exceeded():
                print(f"\n⚠️ Resource budget exceeded at step {iteration}")
                self.context.set_agent_state("no_retry", True)
                self.context.add_error(f"Resource budget exceeded at step {iteration}")
                return False

            work_summary = "No actions taken yet."
            if completed_tasks_log:
                work_summary = "Work Completed So Far:\n" + "\n".join(f"- {log}" for log in completed_tasks_log[-5:])

            next_task = self._determine_next_action(user_request, work_summary, coding_mode)

            if not next_task:
                planner_error = self.context.get_agent_state("planner_error") if self.context else None
                if isinstance(planner_error, str) and planner_error.strip():
                    self.context.set_agent_state("no_retry", True)
                    print("\n❌ Planner failed to produce a next action (LLM error).")
                    print(f"  Error: {planner_error}")
                    return False
                print("\n✅ Planner determined the goal is achieved.")
                return True

            next_task.task_id = iteration
            try:
                # Ensure validation_steps are always present so quick_verify can enforce them.
                next_task.validation_steps = ExecutionPlan().generate_validation_steps(next_task)
            except Exception:
                pass
            ok, sem_msgs = _preflight_correct_action_semantics(next_task)
            for msg in sem_msgs:
                print(f"  [preflight] {msg}")
            if not ok:
                self.context.add_error("Preflight failed: " + "; ".join(sem_msgs))
                completed_tasks_log.append(f"[FAILED] Preflight: {'; '.join(sem_msgs)}")
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
            print(f"  â†' Next action: [{next_task.action_type.upper()}] {next_task.description[:80]}")

            self.context.plan = ExecutionPlan(tasks=[next_task])

            # Anti-loop: stop if the planner repeats the same action too many times.
            action_sig = f"{(next_task.action_type or '').strip().lower()}::{next_task.description.strip().lower()}"
            action_counts[action_sig] += 1
            if action_counts[action_sig] >= 3:
                self.context.set_agent_state("no_retry", True)
                self.context.add_error(f"Circuit breaker: repeating action '{next_task.action_type}'")
                print("\n" + "=" * 70)
                print("CIRCUIT BREAKER - REPEATED ACTION")
                print("=" * 70)
                print(f"Repeated action {action_counts[action_sig]}x: [{(next_task.action_type or '').upper()}] {next_task.description}")
                print("Blocking issue: planner is not making forward progress; refusing to repeat the same step.")
                print("Next step: run with `--debug` and share the last verification failure + tool args.\n")
                return False

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
                            print(f"  ✓ {log_entry}")
                            continue
                except Exception:
                    pass

            # STEP 2: EXECUTE
            execution_success = self._dispatch_to_sub_agents(self.context)

            # STEP 3: VERIFY - This is the critical addition
            verification_result = None
            if execution_success:
                # Only verify actions we have a handler for; otherwise skip verification noise.
                verifiable_actions = {"refactor", "add", "create", "edit", "create_directory", "test"}
                action_type = (next_task.action_type or "").lower()
                if action_type in verifiable_actions:
                    print(f"  -> Verifying execution...")
                    verification_result = verify_task_execution(next_task, self.context)
                    print(f"    {verification_result}")
                else:
                    verification_result = VerificationResult(
                        passed=True,
                        message="Verification skipped",
                        details={"action_type": action_type, "skipped": True},
                    )
                    # Only log skip details when debug logging is enabled.
                    if self.context and getattr(self.context, "debug", False):
                        print(f"    {verification_result}")

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
                    print("  [!] Skipped re-running tests: no code changes since the last failing run.")

                if not verification_result.passed:
                    # Verification failed - mark task as failed and mark for re-planning
                    next_task.status = TaskStatus.FAILED
                    next_task.error = verification_result.message
                    execution_success = False
                    print(f"  [!] Verification failed, marking for re-planning")

                    # Display detailed debug information
                    self._handle_verification_failure(verification_result)

                    # Anti-loop: stop if the same verification failure repeats.
                    first_line = verification_result.message.splitlines()[0].strip() if verification_result.message else ""
                    failure_sig = f"{(next_task.action_type or '').lower()}::{first_line}"
                    failure_counts[failure_sig] += 1
                    if failure_counts[failure_sig] >= 3:
                        self.context.set_agent_state("no_retry", True)
                        self.context.add_error("Circuit breaker: repeating verification failure")
                        print("\n" + "=" * 70)
                        print("CIRCUIT BREAKER - REPEATED VERIFICATION FAILURE")
                        print("=" * 70)
                        print(f"Repeated failure {failure_counts[failure_sig]}x: {first_line}")
                        print("Blocking issue: verification is failing the same way repeatedly; refusing to loop.")
                        print("Next step: fix the blocking issue shown above, then re-run.\n")
                        return False

                    # Try to decompose the failed task into more granular steps.
                    # Decomposing test failures is usually counterproductive (it tends to produce vague edits);
                    # let the planner pick a focused debug/fix step instead.
                    if verification_result.should_replan and (next_task.action_type or "").lower() != "test":
                        decomposed_task = self._decompose_extraction_task(next_task)
                        if decomposed_task:
                            print(f"  [RETRY] Using decomposed task for next iteration")
                            next_task = decomposed_task
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
                self.context.set_agent_state("last_code_change_iteration", iteration)
                self.context.set_agent_state("tests_blocked_no_changes", False)

            # STEP 4: REPORT
            log_entry = f"[{next_task.status.name}] {next_task.description}"
            if next_task.status == TaskStatus.FAILED:
                log_entry += f" | Reason: {next_task.error}"
            if verification_result and not verification_result.passed:
                log_entry += f" | Verification: {verification_result.message}"

            completed_tasks_log.append(log_entry)
            print(f"  {'âœ ভारী' if next_task.status == TaskStatus.COMPLETED else '✗'} {log_entry}")

            self.context.update_repo_context()
            clear_analysis_caches()

        return False

    def _handle_verification_failure(self, verification_result: VerificationResult):
        """Handle and display detailed information about verification failures."""
        print("\n" + "=" * 70)
        print("VERIFICATION FAILURE - DEBUG INFORMATION")
        print("=" * 70)

        # Display main message (which includes issue descriptions)
        if verification_result.message:
            print(f"\n{verification_result.message}")

        # Display debug information if available
        if verification_result.details and "debug" in verification_result.details:
            debug_info = verification_result.details["debug"]
            print("\nDebug Information:")
            print("-" * 70)
            for key, value in debug_info.items():
                if isinstance(value, list):
                    print(f"  {key}:")
                    for item in value:
                        print(f"    - {item}")
                elif isinstance(value, dict):
                    print(f"  {key}:")
                    for k, v in value.items():
                        print(f"    {k}: {v}")
                else:
                    print(f"  {key}: {value}")

        # Display strict/validation command outputs (compileall/pytest/etc)
        details = verification_result.details or {}
        for block_key in ("strict", "validation"):
            block = details.get(block_key)
            if not isinstance(block, dict) or not block:
                continue
            print(f"\n{block_key.upper()} OUTPUTS:")
            print("-" * 70)
            for label, res in block.items():
                if not isinstance(res, dict):
                    continue
                cmd = res.get("cmd")
                rc = res.get("rc")
                stdout = (res.get("stdout") or "").strip()
                stderr = (res.get("stderr") or "").strip()
                stdout_log = res.get("stdout_log")
                stderr_log = res.get("stderr_log")
                print(f"  [{label}] rc={rc} cmd={cmd}")
                if stdout:
                    print("    stdout:")
                    for line in str(stdout).splitlines()[-25:]:
                        print(f"      {line}")
                if stderr:
                    print("    stderr:")
                    for line in str(stderr).splitlines()[-25:]:
                        print(f"      {line}")
                if stdout_log or stderr_log:
                    print(f"    logs: stdout_log={stdout_log} stderr_log={stderr_log}")

        print("\n" + "=" * 70)
        print("NEXT ACTION: Re-planning with different approach...")
        print("=" * 70 + "\n")

    def _dispatch_to_sub_agents(self, context: RevContext) -> bool:
        """Dispatches tasks to appropriate sub-agents."""
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
        if config.EXECUTION_MODE != 'sub-agent':
            print("\n" + "=" * 60)
            print("ORCHESTRATOR - EXECUTION SUMMARY")
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
    return orchestrator.execute(user_request)

