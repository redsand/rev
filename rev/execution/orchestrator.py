"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.

Implements Resource-Aware Optimization pattern to track and enforce budgets.
"""

import os
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
from rev.tools.registry import get_available_tools, get_repo_context
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
from rev.llm.client import get_token_usage
from rev.core.context import RevContext, ResourceBudget # Import ResourceBudget from context
from rev.core.shared_enums import AgentPhase # Import AgentPhase from shared_enums
from rev.core.agent_registry import AgentRegistry # Import AgentRegistry
from rev.cache import clear_analysis_caches # Clear analysis caches between iterations


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
    # Back-compat shim (legacy)
    max_retries: Optional[int] = None
    max_plan_tasks: int = MAX_PLAN_TASKS
    max_planning_iterations: int = config.MAX_PLANNING_TOOL_ITERATIONS

    def __post_init__(self):
        # Enforce strictly sequential execution (single worker only)
        if self.parallel_workers != 1:
            self.parallel_workers = 1
        
        # If legacy max_retries is provided, apply to all retry knobs for backward compatibility
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
        """Initialize the orchestrator.

        Args:
            project_root: Root path of the project
            config: Orchestrator configuration
        """
        self.project_root = project_root
        self._user_config_provided = config is not None
        self.config = config or OrchestratorConfig()
        self.context: Optional[RevContext] = None # Will be initialized in _run_single_attempt
        self.learning_agent = LearningAgent(project_root) if self.config.enable_learning else None

    def _update_phase(self, new_phase: AgentPhase):
        """Updates the current phase and logs the transition."""
        if self.context:
            self.context.set_current_phase(new_phase)
            print(f"\nðŸ”¸ Entering phase: {new_phase.value}")

    def _collect_repo_stats(self) -> Dict[str, Any]:
        """Collects relevant repository statistics for routing decisions."""
        # Placeholder implementation - can be expanded to use more sophisticated git/file analysis
        repo_context_raw = get_repo_context()
        repo_context = {} if isinstance(repo_context_raw, str) else repo_context_raw

        stats = {
            "file_count": len(repo_context.get("all_files", [])),
            "estimated_complexity": 5, # Placeholder: Medium complexity
            "last_commit_age_days": 7, # Placeholder: 7 days old
            "has_tests_dir": os.path.isdir(self.project_root / "tests"),
            "has_docs_dir": os.path.isdir(self.project_root / "docs"),
            "has_examples_dir": os.path.isdir(self.project_root / "examples"),
        }
        return stats

    def execute(self, user_request: str) -> OrchestratorResult:
        """Execute a task through the full agent pipeline.

        Args:
            user_request: The user's task request

        Returns:
            OrchestratorResult with execution outcome
        """
        aggregate_errors: List[str] = []
        last_result: Optional[OrchestratorResult] = None

        # Initialize global context for this run
        self.context = RevContext(user_request=user_request)
        self.context.repo_context = get_repo_context() # Initial repo context

        for attempt in range(self.config.orchestrator_retries + 1):
            if attempt > 0:
                print(f"\n\n🔄 Orchestrator retry {attempt}/{self.config.orchestrator_retries}")
                # Reset plan-specific state for retry
                self.context.plan = None
                self.context.state_manager = None
                self.context.errors = []
                # Note: We preserve agent_insights across retries to track all attempts

            result = self._run_single_attempt(user_request)
            aggregate_errors.extend([f"Attempt {attempt + 1}: {err}" for err in self.context.errors])

            if result.success:
                result.errors = aggregate_errors
                result.agent_insights = self.context.agent_insights # Collect final insights
                return result
            if result.no_retry: # no_retry will be set by the orchestrator (e.g. max retries exceeded)
                result.errors = aggregate_errors
                result.agent_insights = self.context.agent_insights
                return result

            last_result = result
            last_result.errors.extend(self.context.errors) # Accumulate errors from context

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
        
    def _format_review_feedback_for_planning(self, review: ReviewDecision, user_request: str) -> str:
        """
        Format review feedback for the planning agent.

        Args:
            review: The PlanReview object containing feedback.
            user_request: The original user request.

        Returns:
            A formatted string containing actionable feedback for the planner.
        """
        feedback_parts = []

        # Add issues
        if review.issues:
            feedback_parts.append("ISSUES TO ADDRESS:")
            for i, issue in enumerate(review.issues, 1):
                if isinstance(issue, dict):
                    severity = issue.get('severity', 'unknown')
                    description = issue.get('description', str(issue))
                    feedback_parts.append(f"  {i}. [{severity.upper()}] {description}")
                else:
                    feedback_parts.append(f"  {i}. {issue}")

        # Add security concerns
        if review.security_concerns:
            feedback_parts.append("\nSECURITY CONCERNS:")
            for i, concern in enumerate(review.security_concerns, 1):
                feedback_parts.append(f"  {i}. {concern}")

        # Add missing tasks
        if review.missing_tasks:
            feedback_parts.append("\nMISSING TASKS:")
            for i, task in enumerate(review.missing_tasks, 1):
                feedback_parts.append(f"  {i}. {task}")

        # Add suggestions
        if review.suggestions:
            feedback_parts.append("\nSUGGESTIONS:")
            for i, suggestion in enumerate(review.suggestions, 1):
                feedback_parts.append(f"  {i}. {suggestion}")

        # Add overall assessment
        if review.overall_assessment:
            feedback_parts.append(f"\nOVERALL ASSESSMENT:")
            feedback_parts.append(f"  {review.overall_assessment}")

        # Add confidence score
        feedback_parts.append(f"\nReview confidence: {review.confidence_score:.0%}")

        return "\n".join(feedback_parts) if feedback_parts else "No specific feedback provided."

    def _regenerate_followup_plan(self, prompt: str, original_plan: ExecutionPlan, coding_mode: bool) -> Optional[ExecutionPlan]:
            """Regenerates a follow-up plan based on execution feedback or agent requests.
            """
            print(f"\n🔄 Regenerating follow-up plan: {prompt[:100]}...")
            try:
                followup_plan = planning_mode(
                    prompt,
                    coding_mode=coding_mode,
                    max_plan_tasks=self.config.max_plan_tasks,
                    max_planning_iterations=self.config.max_planning_iterations,
                )
                if not followup_plan or not followup_plan.tasks:
                    self.context.add_error("Follow-up planning agent produced no tasks or an invalid plan.")
                    return None
                print(f"  ✓ Follow-up plan generated with {len(followup_plan.tasks)} tasks.")
                return followup_plan
            except Exception as e:
                self.context.add_error(f"Follow-up planning failed: {e}")
                traceback.print_exc()
                return None
   
    def _wait_for_user_resume(self) -> bool:
        """
        Wait for user to signal they're ready to resume execution.

        Returns:
            True if user wants to resume, False if they want to abort.
        """
        print("\n" + "=" * 60)
        print("EXECUTION PAUSED - AWAITING USER ACTION")
        print("=" * 60)
        print("Type 'resume' to continue, or 'abort' to stop execution:")
        print("=" * 60)

        while True:
            try:
                user_input = input("> ").strip().lower()

                if user_input == "resume":
                    print("[OK] Resuming execution...")
                    return True
                elif user_input == "abort":
                    print("[ABORT] Aborting execution...")
                    return False
                else:
                    print("Invalid input. Type 'resume' or 'abort':")
            except (EOFError, KeyboardInterrupt):
                print("\n[ABORT] User interrupted - aborting execution")
                return False

    def _prompt_user_on_stuck_execution(self, failed_tasks: list, user_request: str) -> bool:
        """
        Prompt user when system detects it's stuck in a loop (same tasks failing repeatedly).

        Args:
            failed_tasks: List of Task objects that are failing
            user_request: Original user request

        Returns:
            True if user wants to continue, False to abort
        """
        print("\n" + "=" * 60)
        print("SYSTEM APPEARS STUCK")
        print("=" * 60)
        print(f"The same {len(failed_tasks)} task(s) have failed multiple times:")
        for task in failed_tasks:
            print(f"  • {task.description[:70]}")
            if task.error:
                print(f"    Error: {task.error[:80]}")
        print("\nOptions:")
        print("  'continue' - Try different approach (replan)")
        print("  'skip' - Skip these tasks and move forward")
        print("  'abort' - Stop execution and accept partial results")
        print("=" * 60)

        while True:
            try:
                user_input = input("> ").strip().lower()

                if user_input == "continue":
                    print("✓ Continuing with new strategy...")
                    return True
                elif user_input == "skip":
                    print("✓ Skipping failed tasks...")
                    # Mark failed tasks as STOPPED so they won't be retried
                    for task in failed_tasks:
                        task.status = TaskStatus.STOPPED
                    return True
                elif user_input == "abort":
                    print("✗ Aborting execution...")
                    return False
                else:
                    print("Invalid input. Type 'continue', 'skip', or 'abort':")
            except (EOFError, KeyboardInterrupt):
                print("\n✗ User interrupted - stopping execution")
                return False

    def _prompt_user_on_max_iterations(self, failed_count: int) -> bool:
        """
        Prompt user when max iterations reached with some failed tasks.

        Args:
            failed_count: Number of failed tasks

        Returns:
            True to continue trying, False to stop
        """
        print("\n" + "=" * 60)
        print("MAXIMUM ITERATIONS REACHED")
        print("=" * 60)
        print(f"Execution hit max iterations with {failed_count} task(s) still failing.")
        print("The system has tried its best to recover but some tasks remain incomplete.")
        print("\nOptions:")
        print("  'accept' - Accept partial completion and move to validation")
        print("  'skip' - Skip failed tasks and move forward")
        print("=" * 60)

        while True:
            try:
                user_input = input("> ").strip().lower()

                if user_input in ["accept", "skip"]:
                    if user_input == "skip":
                        print("✓ Marking remaining failed tasks as stopped...")
                        # Will be marked as STOPPED by calling code
                    else:
                        print("✓ Accepting partial completion...")
                    return True
                else:
                    print("Invalid input. Type 'accept' or 'skip':")
            except (EOFError, KeyboardInterrupt):
                print("\n✗ User interrupted - stopping execution")
                return False

    def _hold_and_retry_validation(
        self,
        plan: ExecutionPlan,
        user_request: str,
        validation: ValidationReport
    ) -> ValidationReport:
        """
        Enter an interactive hold for validation failures, allowing user to manually fix issues.

        Args:
            plan: The execution plan.
            user_request: The original user request.
            validation: The current validation report.

        Returns:
            Updated ValidationReport after user intervention and re-validation.
        """
        max_manual_retries = 3
        manual_retry_count = 0
        current_validation = validation

        while manual_retry_count < max_manual_retries:
            manual_retry_count += 1

            print("\n" + "=" * 60)
            print("VALIDATION HOLD - MANUAL INTERVENTION REQUIRED")
            print("=" * 60)
            print(f"Validation failed ({manual_retry_count}/{max_manual_retries} manual retry attempt)")
            print("\nFailed checks:")
            for i, result in enumerate(current_validation.results, 1):
                if result.status == ValidationStatus.FAILED:
                    print(f"  {i}. {result.name}: {result.message}")
            print("\nPlease manually fix the issues and type 'resume' to retry validation.")
            print("Type 'abort' to give up on validation and return to main prompt.")
            print("=" * 60)

            # Wait for user to signal they're ready
            should_resume = self._wait_for_user_resume()

            if not should_resume:
                print("  → User aborted validation. Returning to main prompt.")
                return current_validation

            # Re-run validation
            print("\n  → Re-running validation after user intervention...")
            current_validation = validate_execution(
                plan,
                user_request,
                run_tests=True,
                run_linter=True,
                check_syntax=True,
                enable_auto_fix=False,
                validation_mode=self.config.validation_mode,
            )

            if current_validation.overall_status != ValidationStatus.FAILED:
                print("  ✓ Validation passed after user intervention!")
                return current_validation
            else:
                print(f"  ⚠️ Validation still failing. ({manual_retry_count}/{max_manual_retries} attempts)")
                if manual_retry_count >= max_manual_retries:
                    print(f"  → Max manual retry attempts ({max_manual_retries}) reached.")
                    break

        print(f"\n  → Giving up on manual validation after {manual_retry_count} attempt(s).")
        return current_validation

    def _emit_run_metrics(self, plan: Optional[ExecutionPlan], result: OrchestratorResult, budget: ResourceBudget):
        """Emits run metrics for logging and analysis."""
        print(f"\n🔥 Emitting run metrics...")
        # Placeholder for actual metrics emission (e.g., to a file, dashboard, or telemetry system)
        metrics = {
            "run_id": self.context.run_id,
            "user_request": result.run_mode,
            "success": result.success,
            "phase_reached": result.phase_reached.value,
            "execution_time": result.execution_time,
            "total_steps": budget.steps_used,
            "total_tokens": budget.tokens_used,
            "total_cost": 0.0, # Placeholder
            "errors": result.errors,
            "agent_insights": result.agent_insights,
        }
        print(f"   Metrics: {metrics}")
   
    def _dispatch_to_sub_agents(self, context: RevContext) -> bool:
        """
        Dispatch tasks to appropriate sub-agents based on action_type.

        Args:
            context: The RevContext containing the plan and shared state.

        Returns:
            True if all sub-agent tasks were executed successfully, False otherwise.
        """
        if not context.plan or not context.plan.tasks:
            print("  ⚠️ No tasks in plan to dispatch")
            return False

        # Get registered action types
        registered_action_types = AgentRegistry.get_registered_action_types()
        print(f"  → Registered action types: {', '.join(registered_action_types)}")

        # Filter tasks that can be handled by sub-agents
        agent_tasks = [task for task in context.plan.tasks if task.action_type in registered_action_types]

        if not agent_tasks:
            print(f"  ⚠️ No tasks found matching registered action types")
            return False

        print(f"  → Found {len(agent_tasks)} task(s) for sub-agent execution")

        overall_success = True

        for task in agent_tasks:
            # Skip completed tasks
            if task.status == TaskStatus.COMPLETED:
                continue

            # For failed tasks, skip unless in recovery mode (will be replanned)
            if task.status == TaskStatus.FAILED:
                print(f"  ⏭️  Skipping task {task.task_id}: already failed, awaiting replan")
                continue

            # Check dependencies
            if task.dependencies:
                deps_met = all(
                    context.plan.tasks[dep_idx].status == TaskStatus.COMPLETED
                    for dep_idx in task.dependencies
                    if dep_idx < len(context.plan.tasks)
                )
                if not deps_met:
                    failed_deps = [str(context.plan.tasks[dep_idx].task_id)
                                 for dep_idx in task.dependencies
                                 if dep_idx < len(context.plan.tasks) and context.plan.tasks[dep_idx].status != TaskStatus.COMPLETED]
                    print(f"  ⏭️  Skipping task {task.task_id}: dependencies not met (blocked by: {', '.join(failed_deps)})")
                    task.status = TaskStatus.STOPPED
                    continue

            # Update task status
            task.status = TaskStatus.IN_PROGRESS
            print(f"\n  🤖 Dispatching task {task.task_id} ({task.action_type}): {task.description}")

            try:
                # Get the appropriate agent for this action type
                agent = AgentRegistry.get_agent_instance(task.action_type)

                # Execute the task
                result = agent.execute(task, context)

                # Update task with result and check for agent signals
                task.result = result

                # Check if agent signaled recovery or failure
                if isinstance(result, str):
                    if result.startswith("[RECOVERY_REQUESTED]"):
                        # Agent needs replanning - don't mark complete
                        task.status = TaskStatus.FAILED
                        task.error = result[len("[RECOVERY_REQUESTED]"):].strip()
                        print(f"  ⚠️ Task {task.task_id} requested recovery: {task.error[:100]}")
                        overall_success = False
                    elif result.startswith("[FINAL_FAILURE]"):
                        # Agent exhausted recovery attempts
                        task.status = TaskStatus.FAILED
                        task.error = result[len("[FINAL_FAILURE]"):].strip()
                        print(f"  ✗ Task {task.task_id} failed after recovery attempts: {task.error[:100]}")
                        context.add_error(f"Task {task.task_id}: {task.error}")
                        overall_success = False
                    elif result.startswith("[USER_REJECTED]"):
                        # User rejected the change
                        task.status = TaskStatus.STOPPED
                        task.error = result[len("[USER_REJECTED]"):].strip()
                        print(f"  ⏭️  Task {task.task_id} rejected by user: {task.error[:100]}")
                        overall_success = False
                    else:
                        # Normal success
                        task.status = TaskStatus.COMPLETED
                        print(f"  ✓ Task {task.task_id} completed successfully")

                else:
                    # Non-string result = execution error
                    task.status = TaskStatus.FAILED
                    task.error = f"Invalid result type: {type(result)}"
                    print(f"  ✗ Task {task.task_id} returned invalid result: {task.error}")
                    overall_success = False

            except Exception as e:
                error_msg = f"Sub-agent execution exception for task {task.task_id}: {e}"
                print(f"  ✗ {error_msg}")
                task.status = TaskStatus.FAILED
                task.error = str(e)
                context.add_error(error_msg)
                overall_success = False

                # Continue to next task unless this was a critical failure
                continue

        # Determine overall success
        completed_tasks = [t for t in agent_tasks if t.status == TaskStatus.COMPLETED]
        failed_tasks = [t for t in agent_tasks if t.status == TaskStatus.FAILED]

        print(f"\n  📊 Sub-agent execution summary: {len(completed_tasks)}/{len(agent_tasks)} completed, {len(failed_tasks)} failed")

        return overall_success and len(failed_tasks) == 0


    def _should_adaptively_replan(self, plan: ExecutionPlan, execution_success: bool, budget: ResourceBudget, adaptive_attempt: int) -> bool:
        """Determines if adaptive replanning should be triggered.

            Args:
                plan: The current execution plan.
                execution_success: Whether the execution phase was successful.
                budget: The current resource budget.
                adaptive_attempt: The current adaptive replanning attempt number.

            Returns:
            True if adaptive replanning should be triggered, False otherwise.
        """
        if execution_success:
            return False # No need to replan if execution was successful

        if budget.is_exceeded():
            print(f"\n⚠️ Resource budget exceeded. Cannot adaptively replan. Usage: {budget.get_usage_summary()}")
            return False # Cannot replan if budget is exceeded

        if adaptive_attempt >= self.config.adaptive_replan_attempts:
            print(f"\n❌ Max adaptive replan attempts ({self.config.adaptive_replan_attempts}) exhausted.")
            return False # Max attempts reached

        # Replan if execution failed or an agent requested replanning
        if not execution_success or self.context.agent_requests:
            return True

        return False # Default to no replan

    def _continuous_sub_agent_execution(self, user_request: str, coding_mode: bool) -> bool:
        """
        Execute tasks using step-by-step "next action" determination.

        Similar to Claude Code and Codex, this mode:
        1. Analyzes the user request (no upfront planning)
        2. Determines the SINGLE next action to take
        3. Executes that action
        4. Checks if goal is achieved
        5. Repeats until done

        This avoids the problem of generating 60+ tasks upfront and instead
        makes incremental decisions based on actual current state.

        Args:
            user_request: The original user request
            coding_mode: Whether coding mode is enabled

        Returns:
            True if goal achieved or max iterations reached, False only on critical error
        """
        from rev.execution.planner import analyze_request_mode, determine_next_action

        max_iterations = 10  # Allow more iterations since each one is a single task
        iteration = 0
        completed_tasks = []  # Track completed task descriptions

        # Initial analysis of the request (no upfront planning)
        print("\n" + "=" * 60)
        print("STEP-BY-STEP TASK EXECUTION MODE (Claude Code Style)")
        print("=" * 60)
        analysis = analyze_request_mode(user_request, coding_mode=coding_mode)
        self.context.plan = ExecutionPlan()  # Start with empty plan

        while iteration < max_iterations:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"Step {iteration}/{max_iterations}")
            print(f"{'='*60}")

            # Build summary of completed work
            completed_summary = ""
            if completed_tasks:
                completed_summary = "✓ Completed:\n"
                for desc in completed_tasks[-5:]:  # Show last 5 completed tasks
                    completed_summary += f"  - {desc[:70]}\n"
            else:
                completed_summary = "(Starting - no tasks completed yet)"

            # Get current file state
            self.context.update_repo_context()
            current_file_state = {
                "files_changed": len([f for f in self.context.repo_context.get("status", "").split('\n') if f.strip().startswith('M ')]),
                "files_created": len([f for f in self.context.repo_context.get("status", "").split('\n') if f.strip().startswith('?? ')]),
            }

            # Determine next single action
            print(f"  → Determining next action...")
            next_task = determine_next_action(
                user_request=user_request,
                completed_work=completed_summary,
                current_file_state=current_file_state,
                analysis_context=analysis,
            )

            # Check if goal is achieved
            if next_task.description.strip().upper() == "GOAL_ACHIEVED":
                print(f"  ✓ Goal achieved!")
                return True

            print(f"  → Next action: [{next_task.action_type.upper()}] {next_task.description[:70]}")

            # Execute the single task
            task_index = len(self.context.plan.tasks)
            next_task.task_id = task_index
            self.context.plan.tasks.append(next_task)

            print(f"  → Executing task...")
            success = self._dispatch_to_sub_agents(self.context, [next_task])

            # Update state
            self.context.update_repo_context()
            clear_analysis_caches()

            # Check for task completion
            if next_task.status == TaskStatus.COMPLETED:
                print(f"  ✓ Task completed successfully")
                completed_tasks.append(next_task.description)
            elif next_task.status == TaskStatus.FAILED:
                print(f"  ✗ Task failed: {next_task.error}")
                # Continue anyway - next action determination will factor this in
            else:
                print(f"  ⚠ Task status: {next_task.status.value}")

            # Check resource budget
            if self.context.resource_budget.is_exceeded():
                print(f"\n⚠️ Resource budget exceeded at step {iteration}")
                return True

        # Reached max iterations
        print(f"\n⚠️ Reached maximum steps ({max_iterations})")
        print(f"   Completed: {len(completed_tasks)} tasks")

        return True

    def _run_single_attempt(self, user_request: str) -> OrchestratorResult:
        """Run a single orchestration attempt."""
        print("\n" + "=" * 60)
        print("ORCHESTRATOR - MULTI-AGENT COORDINATION")
        print("=" * 60)
        print(f"Task: {user_request[:100]}...")
        print(f"Execution Mode: {config.EXECUTION_MODE.upper()}")

        # Update context with current request and resource budget
        self.context.user_request = user_request # Ensure context has latest request
        self.context.resource_budget = ResourceBudget() # New budget for each attempt
        start_time = time.time() # Moved this line outside the try block

        # NEW: Route the request to determine optimal configuration
        from rev.execution.router import TaskRouter
        router = TaskRouter()
        repo_stats = self._collect_repo_stats()
        route = router.route(self.context.user_request, repo_stats=repo_stats)
        run_mode = route.mode

        # Initialize result object with default values
        result = OrchestratorResult( 
            success=False,
            phase_reached=self.context.current_phase,
            plan=self.context.plan,
            resource_budget=self.context.resource_budget,
            agent_insights=self.context.agent_insights,
            errors=self.context.errors,
            run_mode=run_mode,
        )


        # Apply routing decision to config (if not explicitly overridden)
        print(f"\n🔀 Routing Decision: {route.mode}")
        print(f"   Reasoning: {route.reasoning}")

        route_research_depth = getattr(route, "research_depth", None)
        if not self._user_config_provided:
            self.config.validation_mode = getattr(route, "validation_mode", self.config.validation_mode)

        # Update config based on route (only if using default config)
        coding_modes = {"quick_edit", "focused_feature", "full_feature", "refactor", "test_focus"}
        coding_mode = route.mode in coding_modes
        if not self._user_config_provided:
            self.config.enable_learning = route.enable_learning
            self.config.enable_research = route.enable_research
            self.config.enable_review = route.enable_review
            self.config.enable_validation = route.enable_validation
            self.config.review_strictness = ReviewStrictness(route.review_strictness)
            self.config.parallel_workers = route.parallel_workers
            self.config.enable_action_review = route.enable_action_review
            self.config.auto_approve = getattr(route, "auto_approve", self.config.auto_approve)
            self.config.orchestrator_retries = route.max_retries
            self.config.plan_regen_retries = route.max_retries
            self.config.validation_retries = route.max_retries
            self.config.enable_auto_fix = getattr(route, "enable_auto_fix", self.config.enable_auto_fix)
            route_plan_cap = getattr(route, "max_plan_tasks", None)
            if route_plan_cap:
                self.config.max_plan_tasks = route_plan_cap
            # Mode-based agent toggles
            if route.mode in {"quick_edit", "test_focus"}:
                self.config.enable_learning = False
                self.config.enable_validation = True
                if route_research_depth not in {"shallow", "off"}:
                    self.config.enable_research = False
                    route_research_depth = "off"
                if not getattr(route, "validation_mode", None):
                    self.config.validation_mode = "smoke"
            elif route.mode == "exploration":
                self.config.enable_learning = True
                self.config.enable_research = True
                self.config.enable_validation = False

        self.config.research_depth = route_research_depth or self.config.research_depth or RESEARCH_DEPTH_DEFAULT
        print(f"   Mode: {route.mode} | Research depth: {self.config.research_depth}")
        print(f"   Plan task cap: {self.config.max_plan_tasks}")
        print(f"   Planning tool-iterations cap: {self.config.max_planning_iterations}")
        print(f"   Validation mode: {self.config.validation_mode}")

        # Parallel execution is disabled globally; enforce single worker
        self.config.parallel_workers = 1

        route_agents = []
        if route.enable_learning:
            route_agents.append("Learning")
        if route.enable_research:
            route_agents.append("Research")
        route_agents.append("Planning")
        if route.enable_review:
            route_agents.append("Review")
        route_agents.append("Execution")
        if route.enable_validation:
            route_agents.append("Validation")
        print(f"   Router agents: {', '.join(route_agents)}")

        print(f"\nAgents enabled: ", end="")
        agents = []
        if self.config.enable_learning:
            agents.append("Learning")
        if self.config.enable_research:
            agents.append("Research")
        agents.append("Planning")
        if self.config.enable_review:
            agents.append("Review")
        agents.append("Execution")
        if self.config.enable_validation:
            agents.append("Validation")
        print(", ".join(agents))
        if coding_mode:
            print("   🔧 Coding mode: ENABLED (test + doc enforcement)")
        print("=" * 60)

        # Initialize resource budget tracking
        self.context.set_current_phase(AgentPhase.LEARNING)
        self.context.resource_budget = ResourceBudget()

        # Display resource budgets
        print(f"\n📊 Resource Budgets:")
        print(f"   Steps: {self.context.resource_budget.max_steps} | Tokens: {self.context.resource_budget.max_tokens} | Time: {self.context.resource_budget.max_seconds}s")

        try:
            # Phase 1: Learning Agent - Get historical insights
            if self.config.enable_learning and self.learning_agent:
                self._update_phase(AgentPhase.LEARNING)
                self.context.resource_budget.update_step()  # Track phase transition
                if self.context.resource_budget.is_exceeded():
                    self.context.add_error(f"Resource budget exceeded during learning phase! Usage: {self.context.resource_budget.get_usage_summary()}")
                    raise Exception("Resource budget exceeded.")
                suggestions = self.learning_agent.get_suggestions(self.context.user_request)
                if suggestions["similar_patterns"]:
                    display_learning_suggestions(suggestions, self.context.user_request)
                self.context.agent_insights["learning"] = suggestions

            # Phase 2: Research Agent - Explore codebase
            if self.config.enable_research:
                self._update_phase(AgentPhase.RESEARCH)
                self.context.resource_budget.update_step()
                if self.context.resource_budget.is_exceeded():
                    self.context.add_error(f"Resource budget exceeded during research phase! Usage: {self.context.resource_budget.get_usage_summary()}")
                    raise Exception("Resource budget exceeded.")
                quick_mode = self.config.research_depth == "shallow"
                research_findings = research_codebase(
                    self.context.user_request,
                    quick_mode=quick_mode,
                    search_depth=self.config.research_depth,
                    repo_stats=repo_stats,
                    budget=self.context.resource_budget,
                )
                if not research_findings:
                    research_findings = ResearchFindings()
                self.context.add_insight("research", "files_found", len(research_findings.relevant_files))
                self.context.add_insight("research", "complexity", research_findings.estimated_complexity)
                self.context.add_insight("research", "warnings", len(research_findings.warnings))
                self.context.agent_insights["research"] = {
                    "files_found": len(research_findings.relevant_files),
                    "complexity": research_findings.estimated_complexity,
                    "warnings": len(research_findings.warnings)
                }

            # Phase 2b: Prompt Optimization (optional)
            if self.config.enable_prompt_optimization:
                original_request = self.context.user_request
                optimized_request, was_optimized = optimize_prompt_if_needed(
                    self.context.user_request,
                    auto_optimize=self.config.auto_optimize_prompt
                )
                if was_optimized:
                    print(f"\n✓ Request optimized for clarity")
                    self.context.user_request = optimized_request
                    self.context.add_insight("optimization", "prompt_optimized", True)
                    self.context.agent_insights["prompt_optimization"] = {
                        "optimized": True,
                        "original": original_request[:100],
                        "improved": optimized_request[:100]
                    }

            # Phase 3: Planning Agent - Create execution plan
            self._update_phase(AgentPhase.PLANNING)
            self.context.resource_budget.update_step()
            if self.context.resource_budget.is_exceeded():
                self.context.add_error(f"Resource budget exceeded during planning phase! Usage: {self.context.resource_budget.get_usage_summary()}")
                raise Exception("Resource budget exceeded.")

            plan = planning_mode(
                self.context.user_request,
                coding_mode=coding_mode,
                max_plan_tasks=self.config.max_plan_tasks,
                max_planning_iterations=self.config.max_planning_iterations,
            )
            self.context.update_plan(plan)
            result.plan = self.context.plan # Update result.plan here
            self.context.set_state_manager(StateManager(self.context.plan))

            if not self.context.plan.tasks:
                self.context.add_error("Planning agent produced no tasks")
                self.context.set_current_phase(AgentPhase.FAILED)
                raise Exception("Planning agent produced no tasks.")

            # Phase 4: Review Agent - Validate plan with retry loop
            review = None  # Will store the review decision
            if self.config.enable_review:
                self._update_phase(AgentPhase.REVIEW)
                self.context.resource_budget.update_step()
                if self.context.resource_budget.is_exceeded():
                    self.context.add_error(f"Resource budget exceeded during review phase! Usage: {self.context.resource_budget.get_usage_summary()}")
                    raise Exception("Resource budget exceeded.")

                # Retry loop for plan regeneration
                planning_retry_count = 0
                max_plan_retries = max(1, self.config.plan_regen_retries)
                min_plan_tasks = 1 if route.mode == "quick_edit" else 2
                while planning_retry_count <= max_plan_retries:
                    if len(self.context.plan.tasks) < min_plan_tasks:
                        if planning_retry_count >= max_plan_retries:
                            print(f"\n❌ Plan too small after {max_plan_retries} regeneration attempt(s) (tasks: {len(self.context.plan.tasks)})")
                            self.context.add_error(f"Plan contained fewer than {min_plan_tasks} tasks after regeneration")
                            self.context.set_current_phase(AgentPhase.REVIEW)
                            raise Exception("Plan too small after regeneration.")

                        planning_retry_count += 1
                        print(f"\n⚠️  Plan too small (only {len(self.context.plan.tasks)} task(s)); regenerating {planning_retry_count}/{max_plan_retries}")
                        plan = planning_mode(
                            f"""{self.context.user_request}\n\nRegenerate the plan with at least {min_plan_tasks} distinct tasks and explicit dependencies. Avoid collapsing multi-step work into one task.""",
                            coding_mode=coding_mode,
                            max_plan_tasks=self.config.max_plan_tasks,
                            max_planning_iterations=self.config.max_planning_iterations,
                        )
                        self.context.update_plan(plan)
                        self.context.set_state_manager(StateManager(self.context.plan)) # Ensure state manager has the latest plan

                        if not self.context.plan.tasks:
                            self.context.add_error("Plan regeneration failed")
                            self.context.set_current_phase(AgentPhase.FAILED)
                            raise Exception("Plan regeneration failed.")
                        continue

                    review = review_execution_plan(
                        self.context.plan,
                        self.context.user_request,
                        strictness=self.config.review_strictness,
                        auto_approve_low_risk=True
                    )
                    
                    review_key = "review" if planning_retry_count == 0 else f"review_retry_{planning_retry_count}"
                    self.context.agent_insights[review_key] = {
                        "decision": review.decision.value,
                        "confidence": review.confidence_score,
                        "issues": len(review.issues),
                        "suggestions": len(review.suggestions)
                    }


                    # Handle review decision
                    if review.decision == ReviewDecision.REJECTED:
                        print("\n❌ Plan rejected by review agent")
                        self.context.add_error("Plan rejected by review agent")
                        self.context.set_current_phase(AgentPhase.REVIEW)
                        raise Exception("Plan rejected by review agent.")

                    if review.decision == ReviewDecision.REQUIRES_CHANGES:
                        print(f"\n⚠️  Plan requires changes (attempt {planning_retry_count + 1}/{self.config.plan_regen_retries + 1})")
                        print(f"   Review confidence: {review.confidence_score:.0%}")
                        print(f"   Issues found: {len(review.issues)}")
                        print(f"   Security concerns: {len(review.security_concerns)}")
                        if review.suggestions:
                            print(f"   Suggestions: {len(review.suggestions)}")

                        # Check if we've exhausted retries
                        if planning_retry_count >= max_plan_retries:
                            print(f"\n❌ Plan still requires changes after {max_plan_retries} regeneration attempt(s)")
                            self.context.add_error(f"Plan requires changes after {max_plan_retries} regeneration attempts")
                            self.context.set_current_phase(AgentPhase.REVIEW)
                            raise Exception("Plan still requires changes after max regeneration attempts.")

                        # Regenerate plan with review feedback
                        planning_retry_count += 1
                        print(f"\n🔄 Plan Regeneration {planning_retry_count}/{max_plan_retries}")
                        print("  → Incorporating review feedback...")

                        # Format review feedback for planning agent
                        feedback = self._format_review_feedback_for_planning(review, self.context.user_request)

                        # Regenerate plan with feedback
                        plan = planning_mode(
                            f"""{self.context.user_request}\n\nIMPORTANT - Address the following review feedback:\n{feedback}""",
                            coding_mode=coding_mode,
                            max_plan_tasks=self.config.max_plan_tasks,
                            max_planning_iterations=self.config.max_planning_iterations,
                        )
                        self.context.update_plan(plan)
                        self.context.set_state_manager(StateManager(self.context.plan)) # Ensure state manager has the latest plan

                        if not self.context.plan.tasks:
                            self.context.add_error("Plan regeneration failed")
                            self.context.set_current_phase(AgentPhase.FAILED)
                            raise Exception("Plan regeneration failed.")

                        print(f"  ✓ Generated new plan with {len(self.context.plan.tasks)} tasks")
                        # Continue to next iteration for re-review

                    else:
                        # Plan approved or approved with suggestions - proceed
                        if planning_retry_count > 0:
                            print(f"\n✓ Plan approved after {planning_retry_count} regeneration attempt(s)!")
                        break

            adaptive_attempt = 0
            while True:
                # Phase 5: Execution Agent - Execute the plan
                self._update_phase(AgentPhase.EXECUTION)
                self.context.resource_budget.update_step()
                if self.context.resource_budget.is_exceeded():
                    self.context.add_error(f"Resource budget exceeded before execution phase! Usage: {self.context.resource_budget.get_usage_summary()}")
                    raise Exception("Resource budget exceeded.")
                
                tools = get_available_tools()

                if config.EXECUTION_MODE == 'sub-agent':
                    print("  → Executing with Sub-Agent architecture (continuous mode)...")
                    execution_success = self._continuous_sub_agent_execution(user_request, coding_mode)
                    if execution_success:
                        print(f"  ✓ Sub-Agent execution phase complete. Success: {execution_success}")
                        # After continuous sub-agent execution, ensure tasks are marked as completed if no errors occurred
                        if not self.context.agent_requests:
                            for task in self.context.plan.tasks:
                                if task.status != TaskStatus.FAILED and task.action_type in AgentRegistry.get_registered_action_types():
                                    task.status = TaskStatus.COMPLETED
                    else:
                        print(f"  ⚠️ Sub-Agent execution stopped by user")
                        self.context.add_error("Sub-agent execution stopped by user")
                    # In continuous mode, we handle replanning internally, so skip adaptive replan
                    # Just validate the results and move on
                    break
                elif self.config.parallel_workers > 1:
                    execution_success = concurrent_execution_mode(
                        self.context.plan,
                        max_workers=self.config.parallel_workers,
                        auto_approve=self.config.auto_approve,
                        tools=tools,
                        enable_action_review=self.config.enable_action_review,
                        coding_mode=coding_mode,
                        state_manager=self.context.state_manager,
                        budget=self.context.resource_budget,
                    )
                else:
                    execution_success = execution_mode(
                        self.context.plan,
                        auto_approve=self.config.auto_approve,
                        tools=tools,
                        enable_action_review=self.config.enable_action_review,
                        coding_mode=coding_mode,
                        state_manager=self.context.state_manager,
                        budget=self.context.resource_budget,
                    )

                # Check for agent requests before adaptive replan
                if self.context.agent_requests:
                    print(f"\n⚠️ Agent requests detected: {self.context.agent_requests}")
                    # For now, any agent request triggers replanning
                    execution_success = False 
                    # Use the first request found. In a real system, a more sophisticated
                    # request handling mechanism would be needed.
                    first_request = self.context.agent_requests[0]
                    self.context.add_insight("orchestrator", "agent_request_triggered_replan", first_request.get("details", {}))
                    self.context.add_insight("orchestrator", "adaptive_replan_count", adaptive_attempt + 1)
                    # Clear requests to avoid re-triggering immediately
                    self.context.agent_requests = []
                    # Do not break from while loop, continue to adaptive replan

                if not self._should_adaptively_replan(self.context.plan, execution_success, self.context.resource_budget, adaptive_attempt):
                    break

                adaptive_attempt += 1
                print(f"\n🔄 Adaptive plan regeneration ({adaptive_attempt}/{self.config.adaptive_replan_attempts})")
                followup_prompt_suffix = ""
                # Incorporate agent request details into followup prompt if available
                if "agent_request_triggered_replan" in self.context.agent_insights.get("orchestrator", {}):
                    request_details = self.context.agent_insights["orchestrator"]["agent_request_triggered_replan"]
                    followup_prompt_suffix += f"\n\nPrevious execution was interrupted by an agent request for replanning due to: {request_details.get('reason', 'unspecified reason')}"

                followup_plan = self._regenerate_followup_plan(
                    f"""{self.context.user_request}{followup_prompt_suffix}""", 
                    self.context.plan,
                    coding_mode,
                )

                if not followup_plan or not followup_plan.tasks:
                    print("  ✗ Adaptive regeneration did not produce a usable plan")
                    self.context.add_error("Adaptive regeneration did not produce a usable plan.")
                    break

                self.context.update_plan(followup_plan)
                # Continue loop to execute regenerated plan
                continue

            # Phase 6: Validation Agent - Verify results
            validation = None
            if self.config.enable_validation:
                self._update_phase(AgentPhase.VALIDATION)
                self.context.resource_budget.update_step()
                if self.context.resource_budget.is_exceeded():
                    self.context.add_error(f"Resource budget exceeded during validation phase! Usage: {self.context.resource_budget.get_usage_summary()} (continuing)")
                    # Do not raise an exception, allow validation to proceed but mark as potential issue
                validation = validate_execution(
                    self.context.plan,
                    self.context.user_request,
                    run_tests=True,
                    run_linter=True,
                    check_syntax=True,
                    enable_auto_fix=self.config.enable_auto_fix,
                    validation_mode=self.config.validation_mode,
                )
                if validation:
                    self.context.agent_insights["validation"] = {
                        "status": validation.overall_status.value,
                        "checks_passed": sum(1 for r in validation.results if r.status == ValidationStatus.PASSED),
                        "checks_failed": sum(1 for r in validation.results if r.status == ValidationStatus.FAILED),
                        "auto_fixed": validation.auto_fixed,
                        "commands": validation.details.get("commands_run", []),
                    }
                else:
                    print("⚠️ Validation returned no result; marking as skipped")
                    self.context.add_insight("validation", "status", ValidationStatus.SKIPPED.value)
                    self.context.add_insight("validation", "reason", "validation_returned_none")
                    validation = ValidationReport(overall_status=ValidationStatus.SKIPPED, results=[])

                # Auto-fix loop for validation failures
                if validation.overall_status == ValidationStatus.FAILED:
                    self.context.add_error("Initial validation failed")

                    retry_count = 0
                    while retry_count < self.config.validation_retries and validation.overall_status == ValidationStatus.FAILED:
                        retry_count += 1
                        print(f"\n🔄 Validation Retry {retry_count}/{self.config.validation_retries}")

                        # Format validation feedback for LLM
                        feedback = format_validation_feedback_for_llm(validation, self.context.user_request)
                        if not feedback:
                            print("  → No specific feedback to provide")
                            break

                        # Attempt to fix validation failures
                        print("  → Attempting auto-fix...")
                        tools = get_available_tools()
                        fix_success = fix_validation_failures(
                            validation_feedback=feedback,
                            user_request=self.context.user_request,
                            tools=tools,
                            enable_action_review=self.config.enable_action_review,
                            max_fix_attempts=3,
                            coding_mode=coding_mode
                        )

                        if not fix_success:
                            print("  ✗ Auto-fix failed")
                            break

                        # Re-run validation to check if fixes worked
                        print("  → Re-running validation...")
                        validation = validate_execution(
                            self.context.plan,
                            self.context.user_request,
                            run_tests=True,
                            run_linter=True,
                            check_syntax=True,
                            enable_auto_fix=False,  # Don't auto-fix during retry validation
                            validation_mode=self.config.validation_mode,
                        )

                        self.context.add_insight("validation", f"retry_{retry_count}_status", validation.overall_status.value)
                        self.context.add_insight("validation", f"retry_{retry_count}_checks_passed", sum(1 for r in validation.results if r.status == ValidationStatus.PASSED))
                        self.context.add_insight("validation", f"retry_{retry_count}_checks_failed", sum(1 for r in validation.results if r.status == ValidationStatus.FAILED))


                        if validation.overall_status == ValidationStatus.FAILED:
                            print(f"  ⚠️  Validation still failing after retry {retry_count}")
                        else:
                            print(f"  ✓ Validation passed after {retry_count} fix attempt(s)!")
                            self.context.errors = [e for e in self.context.errors if e != "Initial validation failed"]
                            break

                    if validation.overall_status == ValidationStatus.FAILED:
                        print(f"\n❌ Validation failed after {retry_count} retry attempt(s)")
                        self.context.add_error(f"Validation failed after {retry_count} retry attempts")

                        # Persist checkpoint before blocking for manual intervention
                        if self.context.state_manager:
                            checkpoint_path = self.context.state_manager.save_checkpoint(reason="validation_failed", force=True)
                            if checkpoint_path:
                                print(f"  ✓ Checkpoint saved to: {checkpoint_path}")
                                print("  The run will pause until you confirm a retry.")

                        # Enter an interactive hold so we do not fail forward. Users can
                        # manually address issues and type a resume keyword to continue
                        # validation from the same phase.
                        validation = self._hold_and_retry_validation(
                            self.context.plan,
                            self.context.user_request,
                            validation,
                        )
                        if validation.overall_status != ValidationStatus.FAILED:
                            self.context.add_insight("validation", "interactive_retries", self.context.agent_insights.get("validation", {}).get("interactive_retries", 0) + 1)
                            self.context.errors = [e for e in self.context.errors if "Validation failed" in e and "retry attempts" in e]

            # Determine if all tasks are completed or successfully handled in sub-agent mode
            all_tasks_handled = False
            if config.EXECUTION_MODE == 'sub-agent':
                handled_action_types = AgentRegistry.get_registered_action_types()
                handled_tasks = [t for t in self.context.plan.tasks if t.action_type in handled_action_types]
                all_tasks_handled = all(t.status == TaskStatus.COMPLETED for t in handled_tasks) and len(handled_tasks) > 0
            else:
                all_tasks_handled = all(t.status == TaskStatus.COMPLETED for t in self.context.plan.tasks) and len(self.context.plan.tasks) > 0


            validation_ok = (
                not self.config.enable_validation or
                (validation and validation.overall_status in [ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS, ValidationStatus.SKIPPED, None])
            )
            
            # The result object must be initialized with values that are always available
            # especially since it's returned on early exceptions.
            result.success = False
            result.phase_reached = self.context.current_phase
            result.plan = self.context.plan
            result.resource_budget = self.context.resource_budget
            result.agent_insights = self.context.agent_insights
            result.errors = self.context.errors
            result.run_mode = run_mode # run_mode is defined earlier
            result.validation_status = validation.overall_status if validation else None
            result.review_decision = review.decision if review else None

            if all_tasks_handled and validation_ok:
                self._update_phase(AgentPhase.COMPLETE)
                result.phase_reached = AgentPhase.COMPLETE
                result.success = True
            else:
                result.phase_reached = self.context.current_phase
                result.success = False

            # Learn from execution only when we reached a valid stopping point
            if self.config.enable_learning and self.learning_agent and self.context.plan:
                execution_time = time.time() - start_time
                validation_passed = (validation and validation.overall_status in [ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS]) if validation else True
                self.learning_agent.learn_from_execution(
                    self.context.plan,
                    self.context.user_request,
                    execution_time,
                    validation_passed
                )

        except KeyboardInterrupt:
            if self.context.plan is not None and self.context.state_manager is not None:
                try:
                    self.context.resource_budget.tokens_used = get_token_usage().get("total", self.context.resource_budget.tokens_used)
                    token_usage = {
                        "total": self.context.resource_budget.tokens_used,
                        "prompt": 0,
                        "completion": 0,
                    }
                    self.context.state_manager.on_interrupt(token_usage=token_usage)
                except Exception as exc: # pragma: no cover - best-effort resume handling
                    print(f"⚠️  Warning: could not save checkpoint on interrupt ({{exc}})")
            raise
        except Exception as e:
            failure_phase = self.context.current_phase if self.context.current_phase else AgentPhase.FAILED
            tb = traceback.format_exc()
            print(f"\n?? Exception during {failure_phase.value} phase: {e}")
            print(tb)
            self.context.add_error(f"{failure_phase.value} phase error: {e}")
            self.context.add_insight("exception", "phase", failure_phase.value)
            self.context.add_insight("exception", "error", str(e))
            self.context.add_insight("exception", "traceback", tb)
            
            # Ensure result is always an OrchestratorResult
            result.phase_reached = failure_phase
            result.success = False
            result.errors.append(f"{failure_phase.value} phase error: {e}") # Add to existing errors

        result.execution_time = time.time() - start_time

        # Refresh token usage from the LLM tracker before displaying summary
        self.context.resource_budget.tokens_used = get_token_usage().get("total", self.context.resource_budget.tokens_used)

        # Display final resource budget summary
        self.context.resource_budget.update_time()
        print(f"\n📊 Resource Usage Summary:")
        print(f"   {self.context.resource_budget.get_usage_summary()}")
        remaining = self.context.resource_budget.get_remaining()
        print(f"   Remaining: Steps {remaining['steps']:.0f}% | Tokens {remaining['tokens']:.0f}% | Time {remaining['time']:.0f}s%")
        if self.context.resource_budget.is_exceeded():
            print(f"   ⚠️  Budget exceeded!")

        self._emit_run_metrics(result.plan, result, self.context.resource_budget)
        self._display_summary(result)
        return result
        
    def _display_summary(self, result: OrchestratorResult):
        """Displays a summary of the orchestration result."""
        print("\n" + "=" * 60)
        print("ORCHESTRATOR - EXECUTION SUMMARY")
        print("=" * 60)
        status = "SUCCESS" if result.success else "FAILED"
        print(f"Overall Status: {status} (Phase: {result.phase_reached.value})")
        print(f"Execution Time: {result.execution_time:.2f} seconds")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"  - {error}")
        if result.plan and result.plan.tasks:
            completed_tasks = [t for t in result.plan.tasks if t.status == TaskStatus.COMPLETED]
            failed_tasks = [t for t in result.plan.tasks if t.status == TaskStatus.FAILED]
            stopped_tasks = [t for t in result.plan.tasks if t.status == TaskStatus.STOPPED]
            print(f"Tasks: {len(completed_tasks)} completed, {len(failed_tasks)} failed, {len(stopped_tasks)} skipped/stopped of {len(result.plan.tasks)} total")

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
) -> OrchestratorResult:
    """Run a task through the orchestrated multi-agent pipeline.

    This is the main entry point for orchestrated execution.

    Args:
        user_request: The user's task request
        project_root: Root path of the project
        enable_learning: Enable Learning Agent
        enable_research: Enable Research Agent
        enable_review: Enable Review Agent
        enable_validation: Enable Validation Agent
        review_strictness: Review strictness level
        enable_action_review: Enable action-level review
        parallel_workers: Number of parallel execution workers
        auto_approve: Auto-approve plans with warnings
        research_depth: Research depth (off/shallow/medium/deep)

    Returns:
        OrchestratorResult with execution outcome
    """
    config_obj = OrchestratorConfig( # Renamed to config_obj to avoid name collision with module config
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
    )

    orchestrator = Orchestrator(project_root, config_obj)
    return orchestrator.execute(user_request)
