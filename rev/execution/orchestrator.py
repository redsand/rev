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
            action_type = match.group(1).lower()
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
        available_actions = AgentRegistry.get_registered_action_types()
        
        prompt = (
            f"Original Request: {user_request}\n\n"
            f"{work_summary}\n\n"
            "Based on the work completed, what is the single next most important action to take? "
            "If a previous action failed, propose a different action to achieve the goal.\n"
            "Constraints to avoid duplicating work:\n"
            "- Do not propose repeating a step that is already complete (e.g., do not re-create a directory that exists).\n"
            "- If the code was split into a package with __init__.py exports, prefer package-export imports at call sites.\n"
            "- Avoid replacing `from pkg import *` with dozens of per-module imports; only import names actually used.\n"
            f"You MUST choose one of the following action types: {available_actions}\n"
            "Your response should be a single line in the format: [ACTION_TYPE] description of the action.\n"
            "Example: [EDIT] refactor the authentication middleware to use the new session manager.\n"
            "If the goal has been achieved, respond with only the text 'GOAL_ACHIEVED'."
        )
        
        response_data = ollama_chat([{"role": "user", "content": prompt}])

        if "error" in response_data:
            print(f"  ❌ LLM Error in lightweight planner: {response_data['error']}")
            return None

        response_content = response_data.get("message", {}).get("content", "")
        if not response_content or response_content.strip().upper() == "GOAL_ACHIEVED":
            return None
        
        match = re.match(r"[\s]*\[(.*?)\]\s*(.*)", response_content.strip())
        if not match:
            return Task(description=response_content.strip(), action_type="general")
        
        action_type = match.group(1).lower()
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
                return True

            work_summary = "No actions taken yet."
            if completed_tasks_log:
                work_summary = "Work Completed So Far:\n" + "\n".join(f"- {log}" for log in completed_tasks_log[-5:])

            next_task = self._determine_next_action(user_request, work_summary, coding_mode)

            if not next_task:
                print("\n✅ Planner determined the goal is achieved.")
                return True

            next_task.task_id = iteration
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
                    m = re.search(r'([A-Za-z0-9_\\-./\\\\]+)', next_task.description)
                    candidate = (m.group(1) if m else "").strip().strip('"').strip("'")
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
                print(f"  -> Verifying execution...")
                verification_result = verify_task_execution(next_task, self.context)
                print(f"    {verification_result}")

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

            action_type = (next_task.action_type or "").lower()
            if next_task.status == TaskStatus.COMPLETED and action_type in {"edit", "add", "refactor", "create_directory"}:
                self.context.set_agent_state("last_code_change_iteration", iteration)

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

        # Alias common actions to the canonical ones the agents expect
        action_aliases = {
            "create": "add",
            "write": "add",
            "refator": "refactor",
            "investigate": "research",
        }
        
        normalized_action_type = task.action_type.lower()
        if normalized_action_type in action_aliases:
            task.action_type = action_aliases[normalized_action_type]

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
            task.result = result
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

