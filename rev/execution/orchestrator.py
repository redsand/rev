"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.

Implements Resource-Aware Optimization pattern to track and enforce budgets.
"""

import os
import time
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections import defaultdict

from rev.models.task import ExecutionPlan, TaskStatus
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
from rev.tools.registry import get_available_tools
from rev.config import (
    MAX_PLAN_TASKS,
    MAX_STEPS_PER_RUN,
    MAX_LLM_TOKENS_PER_RUN,
    MAX_WALLCLOCK_SECONDS,
    RESEARCH_DEPTH_DEFAULT,
    VALIDATION_MODE_DEFAULT,
    MAX_ORCHESTRATOR_RETRIES,
    MAX_PLAN_REGEN_RETRIES,
    MAX_VALIDATION_RETRIES,
)
from rev.llm.client import get_token_usage


@dataclass
class ResourceBudget:
    """Resource budget tracker for resource-aware optimization."""
    max_steps: int = MAX_STEPS_PER_RUN
    max_tokens: int = MAX_LLM_TOKENS_PER_RUN
    max_seconds: float = MAX_WALLCLOCK_SECONDS

    # Current usage
    steps_used: int = 0
    tokens_used: int = 0
    seconds_used: float = 0.0

    # Start time for duration tracking
    start_time: float = field(default_factory=time.time)

    def update_step(self, count: int = 1) -> None:
        """Increment step counter."""
        self.steps_used += count

    def update_tokens(self, count: int) -> None:
        """Add to token counter."""
        self.tokens_used += count

    def update_time(self) -> None:
        """Update elapsed time."""
        self.seconds_used = time.time() - self.start_time

    def is_exceeded(self) -> bool:
        """Check if any budget limit is exceeded."""
        self.update_time()
        return (
            self.steps_used >= self.max_steps or
            self.tokens_used >= self.max_tokens or
            self.seconds_used >= self.max_seconds
        )

    def get_remaining(self) -> Dict[str, float]:
        """Get remaining budget percentages."""
        self.update_time()
        return {
            "steps": max(0, (self.max_steps - self.steps_used) / self.max_steps * 100) if self.max_steps > 0 else 100,
            "tokens": max(0, (self.max_tokens - self.tokens_used) / self.max_tokens * 100) if self.max_tokens > 0 else 100,
            "time": max(0, (self.max_seconds - self.seconds_used) / self.max_seconds * 100) if self.max_seconds > 0 else 100
        }

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        self.update_time()
        return (
            f"Steps: {self.steps_used}/{self.max_steps} | "
            f"Tokens: {self.tokens_used}/{self.max_tokens} | "
            f"Time: {self.seconds_used:.1f}s/{self.max_seconds:.0f}s"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        self.update_time()
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "seconds_used": self.seconds_used,
            "steps_remaining_pct": self.get_remaining()["steps"],
            "tokens_remaining_pct": self.get_remaining()["tokens"],
            "time_remaining_pct": self.get_remaining()["time"],
            "exceeded": self.is_exceeded()
        }


class AgentPhase(Enum):
    """Phases of the orchestrated workflow."""
    LEARNING = "learning"
    RESEARCH = "research"
    PLANNING = "planning"
    REVIEW = "review"
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMPLETE = "complete"
    FAILED = "failed"


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
    parallel_workers: int = 2
    auto_approve: bool = True
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT
    validation_mode: Literal["none", "smoke", "targeted", "full"] = VALIDATION_MODE_DEFAULT
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES
    validation_retries: int = MAX_VALIDATION_RETRIES
    # Back-compat shim (legacy)
    max_retries: Optional[int] = None
    max_plan_tasks: int = MAX_PLAN_TASKS

    def __post_init__(self):
        # If legacy max_retries is provided, apply to all retry knobs for backward compatibility
        if self.max_retries is not None:
            self.orchestrator_retries = self.max_retries
            self.plan_regen_retries = self.max_retries
            self.validation_retries = self.max_retries


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
        self.current_phase = AgentPhase.LEARNING
        self.learning_agent = LearningAgent(project_root) if self.config.enable_learning else None

    def execute(self, user_request: str) -> OrchestratorResult:
        """Execute a task through the full agent pipeline.

        Args:
            user_request: The user's task request

        Returns:
            OrchestratorResult with execution outcome
        """
        aggregate_errors: List[str] = []
        last_result: Optional[OrchestratorResult] = None

        for attempt in range(self.config.orchestrator_retries + 1):
            if attempt > 0:
                print(f"\n🔄 Orchestrator retry {attempt}/{self.config.orchestrator_retries}")
            result = self._run_single_attempt(user_request)
            aggregate_errors.extend([f"Attempt {attempt + 1}: {err}" for err in result.errors])

            if result.success:
                result.errors = aggregate_errors
                return result
            if result.no_retry:
                result.errors = aggregate_errors
                return result

            last_result = result

        if last_result:
            last_result.errors = aggregate_errors
            return last_result

        return OrchestratorResult(
            success=False,
            phase_reached=AgentPhase.FAILED,
            errors=["Unknown orchestrator failure"],
        )

    def _run_single_attempt(self, user_request: str) -> OrchestratorResult:
        """Run a single orchestration attempt."""
        print("\n" + "=" * 60)
        print("ORCHESTRATOR - MULTI-AGENT COORDINATION")
        print("=" * 60)
        print(f"Task: {user_request[:100]}...")

        # NEW: Route the request to determine optimal configuration
        from rev.execution.router import TaskRouter
        router = TaskRouter()
        repo_stats = self._collect_repo_stats()
        route = router.route(user_request, repo_stats=repo_stats)
        run_mode = route.mode

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
        print(f"   Validation mode: {self.config.validation_mode}")

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
        self.current_phase = AgentPhase.LEARNING
        budget = ResourceBudget()
        result = OrchestratorResult(
            success=False,
            phase_reached=AgentPhase.LEARNING,
            resource_budget=budget,
            run_mode=run_mode,
        )
        start_time = time.time()

        plan: Optional[ExecutionPlan] = None
        state_manager: Optional[StateManager] = None
        checkpoint_path: Optional[str] = None

        # Display resource budgets
        print(f"\n📊 Resource Budgets:")
        print(f"   Steps: {budget.max_steps} | Tokens: {budget.max_tokens} | Time: {budget.max_seconds}s")

        try:
            # Phase 1: Learning Agent - Get historical insights
            if self.config.enable_learning and self.learning_agent:
                self._update_phase(AgentPhase.LEARNING)
                budget.update_step()  # Track phase transition
                if budget.is_exceeded():
                    print(f"\n⚠️ Resource budget exceeded during learning phase!")
                    result.errors.append("Resource budget exceeded during learning phase")
                    result.phase_reached = AgentPhase.LEARNING
                    return result
                suggestions = self.learning_agent.get_suggestions(user_request)
                if suggestions["similar_patterns"]:
                    display_learning_suggestions(suggestions, user_request)
                result.agent_insights["learning"] = suggestions

            # Phase 2: Research Agent - Explore codebase
            if self.config.enable_research:
                self._update_phase(AgentPhase.RESEARCH)
                budget.update_step()
                if budget.is_exceeded():
                    print(f"\n⚠️ Resource budget exceeded during research phase!")
                    result.errors.append("Resource budget exceeded during research phase")
                    result.phase_reached = AgentPhase.RESEARCH
                    return result
                quick_mode = self.config.research_depth == "shallow"
                research_findings = research_codebase(
                    user_request,
                    quick_mode=quick_mode,
                    search_depth=self.config.research_depth,
                    repo_stats=repo_stats,
                    budget=budget,
                )
                result.research_findings = research_findings
                result.agent_insights["research"] = {
                    "files_found": len(research_findings.relevant_files),
                    "complexity": research_findings.estimated_complexity,
                    "warnings": len(research_findings.warnings)
                }

            # Phase 3: Planning Agent - Create execution plan
            self._update_phase(AgentPhase.PLANNING)
            budget.update_step()
            if budget.is_exceeded():
                print(f"\n⚠️ Resource budget exceeded during planning phase!")
                result.errors.append("Resource budget exceeded during planning phase")
                result.phase_reached = AgentPhase.PLANNING
                return result
            plan = planning_mode(
                user_request,
                coding_mode=coding_mode,
                max_plan_tasks=self.config.max_plan_tasks,
            )
            result.plan = plan
            state_manager = StateManager(plan)

            if not plan.tasks:
                result.errors.append("Planning agent produced no tasks")
                result.phase_reached = AgentPhase.FAILED
                return result

            # Phase 4: Review Agent - Validate plan with retry loop
            review = None
            if self.config.enable_review:
                self._update_phase(AgentPhase.REVIEW)
                budget.update_step()
                if budget.is_exceeded():
                    print(f"\n⚠️ Resource budget exceeded during review phase!")
                    result.errors.append("Resource budget exceeded during review phase")
                    result.phase_reached = AgentPhase.REVIEW
                    return result

                # Retry loop for plan regeneration
                planning_retry_count = 0
                max_plan_retries = max(1, self.config.plan_regen_retries)
                while planning_retry_count <= max_plan_retries:
                    review = review_execution_plan(
                        plan,
                        user_request,
                        strictness=self.config.review_strictness,
                        auto_approve_low_risk=True
                    )
                    result.review_decision = review.decision

                    # Store review insights
                    review_key = "review" if planning_retry_count == 0 else f"review_retry_{planning_retry_count}"
                    result.agent_insights[review_key] = {
                        "decision": review.decision.value,
                        "confidence": review.confidence_score,
                        "issues": len(review.issues),
                        "suggestions": len(review.suggestions)
                    }

                    # Handle review decision
                    if review.decision == ReviewDecision.REJECTED:
                        print("\n❌ Plan rejected by review agent")
                        result.errors.append("Plan rejected by review agent")
                        result.phase_reached = AgentPhase.REVIEW
                        return result

                    if review.decision == ReviewDecision.REQUIRES_CHANGES:
                        # Display review feedback
                        print(f"\n⚠️  Plan requires changes (attempt {planning_retry_count + 1}/{self.config.plan_regen_retries + 1})")
                        print(f"   Review confidence: {review.confidence_score:.0%}")
                        print(f"   Issues found: {len(review.issues)}")
                        print(f"   Security concerns: {len(review.security_concerns)}")
                        if review.suggestions:
                            print(f"   Suggestions: {len(review.suggestions)}")

                        # Check if we've exhausted retries
                        if planning_retry_count >= max_plan_retries:
                            print(f"\n❌ Plan still requires changes after {max_plan_retries} regeneration attempt(s)")
                            result.errors.append(f"Plan requires changes after {max_plan_retries} regeneration attempts")
                            result.phase_reached = AgentPhase.REVIEW
                            return result

                        # Regenerate plan with review feedback
                        planning_retry_count += 1
                        print(f"\n🔄 Plan Regeneration {planning_retry_count}/{max_plan_retries}")
                        print("  → Incorporating review feedback...")

                        # Format review feedback for planning agent
                        feedback = self._format_review_feedback_for_planning(review, user_request)

                        # Regenerate plan with feedback
                        plan = planning_mode(
                            f"""{user_request}

IMPORTANT - Address the following review feedback:
{feedback}""",
                            coding_mode=coding_mode,
                            max_plan_tasks=self.config.max_plan_tasks,
                        )
                        result.plan = plan

                        if not plan.tasks:
                            print("  ✗ Plan regeneration produced no tasks")
                            result.errors.append("Plan regeneration failed")
                            result.phase_reached = AgentPhase.FAILED
                            return result

                        print(f"  ✓ Generated new plan with {len(plan.tasks)} tasks")
                        # Continue to next iteration for re-review

                    else:
                        # Plan approved or approved with suggestions - proceed
                        if planning_retry_count > 0:
                            print(f"\n✓ Plan approved after {planning_retry_count} regeneration attempt(s)!")
                        break

            # Phase 5: Execution Agent - Execute the plan
            self._update_phase(AgentPhase.EXECUTION)
            budget.update_step()
            if budget.is_exceeded():
                print(f"\n⚠️ Resource budget exceeded before execution phase!")
                result.errors.append("Resource budget exceeded before execution phase")
                result.phase_reached = AgentPhase.EXECUTION
                return result
            # Note: Task execution steps are tracked inside execution_mode/concurrent_execution_mode
            # per-task, not consumed upfront to allow accurate tracking of partial execution
            tools = get_available_tools()
            if self.config.parallel_workers > 1:
                concurrent_execution_mode(
                    plan,
                    max_workers=self.config.parallel_workers,
                    auto_approve=self.config.auto_approve,
                    tools=tools,
                    enable_action_review=self.config.enable_action_review,
                    coding_mode=coding_mode,
                    state_manager=state_manager,
                    budget=budget,
                )
            else:
                execution_mode(
                    plan,
                    auto_approve=self.config.auto_approve,
                    tools=tools,
                    enable_action_review=self.config.enable_action_review,
                    coding_mode=coding_mode,
                    state_manager=state_manager,
                    budget=budget,
                )

            # Phase 6: Validation Agent - Verify results
            validation = None
            if self.config.enable_validation:
                self._update_phase(AgentPhase.VALIDATION)
                budget.update_step()
                if budget.is_exceeded():
                    print(f"\n⚠️ Resource budget exceeded during validation phase! Skipping validation.")
                    result.errors.append("Resource budget exceeded during validation phase (validation skipped)")
                    result.phase_reached = AgentPhase.VALIDATION
                    result.validation_status = ValidationStatus.SKIPPED
                    result.agent_insights["validation"] = {
                        "status": ValidationStatus.SKIPPED.value,
                        "reason": "resource_budget_exceeded",
                    }
                    result.no_retry = True
                else:
                    validation = validate_execution(
                        plan,
                        user_request,
                        run_tests=True,
                        run_linter=True,
                        check_syntax=True,
                        enable_auto_fix=self.config.enable_auto_fix,
                        validation_mode=self.config.validation_mode,
                    )
                    result.validation_status = validation.overall_status
                    result.agent_insights["validation"] = {
                        "status": validation.overall_status.value,
                        "checks_passed": sum(1 for r in validation.results if r.status == ValidationStatus.PASSED),
                        "checks_failed": sum(1 for r in validation.results if r.status == ValidationStatus.FAILED),
                        "auto_fixed": validation.auto_fixed,
                        "commands": validation.details.get("commands_run", []),
                    }
                result.validation_status = validation.overall_status
                result.agent_insights["validation"] = {
                    "status": validation.overall_status.value,
                    "checks_passed": sum(1 for r in validation.results if r.status == ValidationStatus.PASSED),
                    "checks_failed": sum(1 for r in validation.results if r.status == ValidationStatus.FAILED),
                    "auto_fixed": validation.auto_fixed
                }

                # Auto-fix loop for validation failures
                if validation and validation.overall_status == ValidationStatus.FAILED:
                    result.errors.append("Initial validation failed")

                    retry_count = 0
                    while retry_count < self.config.validation_retries and validation.overall_status == ValidationStatus.FAILED:
                        retry_count += 1
                        print(f"\n🔄 Validation Retry {retry_count}/{self.config.validation_retries}")

                        # Format validation feedback for LLM
                        feedback = format_validation_feedback_for_llm(validation, user_request)
                        if not feedback:
                            print("  → No specific feedback to provide")
                            break

                        # Attempt to fix validation failures
                        print("  → Attempting auto-fix...")
                        tools = get_available_tools()
                        fix_success = fix_validation_failures(
                            validation_feedback=feedback,
                            user_request=user_request,
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
                            plan,
                            user_request,
                            run_tests=True,
                            run_linter=True,
                            check_syntax=True,
                            enable_auto_fix=False,  # Don't auto-fix during retry validation
                            validation_mode=self.config.validation_mode,
                        )

                        result.validation_status = validation.overall_status
                        result.agent_insights["validation"][f"retry_{retry_count}"] = {
                            "status": validation.overall_status.value,
                            "checks_passed": sum(1 for r in validation.results if r.status == ValidationStatus.PASSED),
                            "checks_failed": sum(1 for r in validation.results if r.status == ValidationStatus.FAILED)
                        }

                        if validation.overall_status == ValidationStatus.FAILED:
                            print(f"  ⚠️  Validation still failing after retry {retry_count}")
                        else:
                            print(f"  ✓ Validation passed after {retry_count} fix attempt(s)!")
                            result.errors = [e for e in result.errors if e != "Initial validation failed"]
                            break

                    if validation.overall_status == ValidationStatus.FAILED:
                        print(f"\n❌ Validation failed after {retry_count} retry attempt(s)")
                        result.errors.append(f"Validation failed after {retry_count} retry attempts")

                        # Persist checkpoint before blocking for manual intervention
                        if state_manager:
                            checkpoint_path = state_manager.save_checkpoint(reason="validation_failed", force=True)
                            if checkpoint_path:
                                print(f"  ✓ Checkpoint saved to: {checkpoint_path}")
                                print("  The run will pause until you confirm a retry.")

                        # Enter an interactive hold so we do not fail forward. Users can
                        # manually address issues and type a resume keyword to continue
                        # validation from the same phase.
                        validation = self._hold_and_retry_validation(
                            plan,
                            user_request,
                            validation,
                        )
                        result.validation_status = validation.overall_status
                        result.agent_insights["validation"]["interactive_retries"] = result.agent_insights["validation"].get("interactive_retries", 0)
                        if validation.overall_status != ValidationStatus.FAILED:
                            result.agent_insights["validation"]["interactive_retries"] += 1
                            result.errors = [e for e in result.errors if "Validation failed" in e and "retry attempts" in e]

            # Complete (only mark complete when final phase succeeded)
            all_completed = all(t.status == TaskStatus.COMPLETED for t in plan.tasks) and len(plan.tasks) > 0
            validation_ok = (
                not self.config.enable_validation or
                result.validation_status in [ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS, ValidationStatus.SKIPPED, None]
            )

            if all_completed and validation_ok:
                self._update_phase(AgentPhase.COMPLETE)
                result.phase_reached = AgentPhase.COMPLETE
            else:
                # Stay on the current phase to prevent failing forward
                result.phase_reached = self.current_phase
            # Learn from execution only when we reached a valid stopping point
            if self.config.enable_learning and self.learning_agent:
                execution_time = time.time() - start_time
                validation_passed = result.validation_status in [ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS] if result.validation_status else True
                self.learning_agent.learn_from_execution(
                    plan,
                    user_request,
                    execution_time,
                    validation_passed
                )

            # Determine success
            result.success = all_completed and validation_ok

        except KeyboardInterrupt:
            if plan is not None:
                try:
                    state_manager = state_manager or StateManager(plan)
                    budget.tokens_used = get_token_usage().get("total", budget.tokens_used)
                    token_usage = {
                        "total": budget.tokens_used,
                        "prompt": 0,
                        "completion": 0,
                    }
                    state_manager.on_interrupt(token_usage=token_usage)
                except Exception as exc:  # pragma: no cover - best-effort resume handling
                    print(f"⚠️  Warning: could not save checkpoint on interrupt ({exc})")
            raise
        except Exception as e:
            failure_phase = self.current_phase if self.current_phase else AgentPhase.FAILED
            result.errors.append(f"{failure_phase.value} phase error: {e}")
            result.phase_reached = failure_phase
            result.success = False

        result.execution_time = time.time() - start_time

        # Refresh token usage from the LLM tracker before displaying summary
        budget.tokens_used = get_token_usage().get("total", budget.tokens_used)

        # Display final resource budget summary
        budget.update_time()
        print(f"\n📊 Resource Usage Summary:")
        print(f"   {budget.get_usage_summary()}")
        remaining = budget.get_remaining()
        print(f"   Remaining: Steps {remaining['steps']:.0f}% | Tokens {remaining['tokens']:.0f}% | Time {remaining['time']:.0f}%")
        if budget.is_exceeded():
            print(f"   ⚠️  Budget exceeded!")

        self._emit_run_metrics(plan, result, budget)
        self._display_summary(result)
        return result

    def _update_phase(self, phase: AgentPhase):
        """Update current phase and display progress."""
        self.current_phase = phase
        phase_icons = {
            AgentPhase.LEARNING: "📚",
            AgentPhase.RESEARCH: "🔍",
            AgentPhase.PLANNING: "📋",
            AgentPhase.REVIEW: "🔒",
            AgentPhase.EXECUTION: "⚡",
            AgentPhase.VALIDATION: "✅",
            AgentPhase.COMPLETE: "🎉",
            AgentPhase.FAILED: "❌"
        }
        icon = phase_icons.get(phase, "▶️")
        print(f"\n{icon} Phase: {phase.value.upper()}")

    def _emit_run_metrics(self, plan: Optional[ExecutionPlan], result: OrchestratorResult, budget: ResourceBudget):
        """Emit lightweight run metrics for observability."""
        try:
            from pathlib import Path
            import json

            metrics_dir = Path.cwd() / ".rev-metrics"
            metrics_dir.mkdir(exist_ok=True)
            metrics_path = metrics_dir / "run-metrics.jsonl"

            planned = len(plan.tasks) if plan and plan.tasks else 0
            completed = sum(1 for t in (plan.tasks if plan else []) if t.status == TaskStatus.COMPLETED)
            failed = sum(1 for t in (plan.tasks if plan else []) if t.status == TaskStatus.FAILED)
            token_usage = get_token_usage()

            metrics = {
                "mode": result.run_mode,
                "validation_mode": getattr(self.config, "validation_mode", None),
                "planned_tasks": planned,
                "completed_tasks": completed,
                "failed_tasks": failed,
                "success": result.success,
                "validation_status": result.validation_status.value if result.validation_status else None,
                "tokens": token_usage,
                "budget": budget.to_dict(),
            }

            with open(metrics_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(metrics) + "\n")
        except Exception:
            # Metrics are best-effort; do not fail the run
            pass

    def _hold_and_retry_validation(
        self,
        plan: ExecutionPlan,
        user_request: str,
        last_validation: ValidationReport,
    ) -> ValidationReport:
        """Block on validation failure until the user signals to continue."""

        print("\n⏸️  Validation halted. The orchestrator will not proceed until you confirm.")
        print("   Type 'go', 'continue', 'resume', or 'do stuff' to retry validation.")
        print("   Type 'abort' to stop this run while keeping the current checkpoint.")

        while True:
            if not self._wait_for_user_resume():
                print("\n🚫 User opted to stop at validation phase.")
                self.current_phase = AgentPhase.VALIDATION
                return last_validation

            print("\n▶️  Retrying validation from current state...")
            validation = validate_execution(
                plan,
                user_request,
                run_tests=True,
                run_linter=True,
                check_syntax=True,
                enable_auto_fix=self.config.enable_auto_fix,
                validation_mode=self.config.validation_mode,
            )

            self.current_phase = AgentPhase.VALIDATION

            if validation.overall_status == ValidationStatus.FAILED:
                print("⚠️  Validation still failing. Waiting for further instructions.")
                last_validation = validation
                continue

            print("✅ Validation passed after manual resume signal.")
            return validation

    def _wait_for_user_resume(self) -> bool:
        """Wait for explicit user confirmation to continue after a failure."""

        accepted = {"go", "continue", "resume", "c", "do stuff", "do it", "yes", "y"}
        abort = {"abort", "stop", "quit", "exit", "n", "no"}

        while True:
            try:
                response = input("→ Awaiting input [go/continue/resume/do stuff/abort]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nInput interrupted; stopping execution.")
                return False

            if response in accepted:
                return True
            if response in abort:
                return False

            print("Please type 'go' to continue or 'abort' to stop.")

    def _format_review_feedback_for_planning(self, review, user_request: str) -> str:
        """Format review feedback for the planning agent to incorporate.

        Args:
            review: PlanReview object with feedback
            user_request: Original user request

        Returns:
            Formatted feedback string
        """
        feedback_parts = []

        if review.overall_assessment:
            feedback_parts.append(f"Assessment: {review.overall_assessment}\n")

        if review.issues:
            feedback_parts.append("Issues to address:")
            for issue in review.issues:
                severity = issue.get("severity", "unknown").upper()
                description = issue.get("description", "")
                impact = issue.get("impact", "")
                feedback_parts.append(f"  - [{severity}] {description}")
                if impact:
                    feedback_parts.append(f"    Impact: {impact}")
            feedback_parts.append("")

        if review.security_concerns:
            feedback_parts.append("Security concerns:")
            for concern in review.security_concerns:
                feedback_parts.append(f"  - {concern}")
            feedback_parts.append("")

        if review.missing_tasks:
            feedback_parts.append("Missing tasks to add:")
            for task in review.missing_tasks:
                feedback_parts.append(f"  - {task}")
            feedback_parts.append("")

        if review.suggestions:
            feedback_parts.append("Suggestions:")
            for suggestion in review.suggestions:
                feedback_parts.append(f"  - {suggestion}")
            feedback_parts.append("")

        return "\n".join(feedback_parts)

    def _display_summary(self, result: OrchestratorResult):
        """Display orchestration summary."""
        print("\n" + "=" * 60)
        print("ORCHESTRATION SUMMARY")
        print("=" * 60)

        status_icon = "✅" if result.success else "❌"
        print(f"{status_icon} Status: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"⏱️  Total time: {result.execution_time:.1f}s")
        print(f"📍 Phase reached: {result.phase_reached.value}")
        if result.validation_status:
            print(f"🧪 Validation: {result.validation_status.value}")
        if result.run_mode:
            print(f"🎛️  Mode: {result.run_mode}")

        if result.agent_insights:
            print("\n📊 Agent Insights:")
            for agent, insights in result.agent_insights.items():
                print(f"   {agent}:")
                if isinstance(insights, dict):
                    for k, v in list(insights.items())[:3]:
                        print(f"     - {k}: {v}")

        if result.errors:
            print("\n❌ Errors:")
            for error in result.errors:
                print(f"   - {error}")

        print("=" * 60)

        return result

    def _collect_repo_stats(self) -> Dict[str, Any]:
        """Collect lightweight repository statistics for routing decisions."""
        stats: Dict[str, Any] = {
            "file_count": 0,
            "test_file_count": 0,
            "has_tests": False,
            "dominant_language": None,
        }
        ext_lang = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".md": "markdown",
        }
        ext_counts = defaultdict(int)
        skip_dirs = {".git", "node_modules", "venv", "__pycache__", ".pytest_cache", ".rev-metrics", ".mypy_cache"}

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in files:
                stats["file_count"] += 1
                lower = fname.lower()
                if lower.startswith("test_") or lower.endswith("_test.py") or "tests" in Path(root).parts:
                    stats["test_file_count"] += 1
                ext = Path(fname).suffix.lower()
                if ext in ext_lang:
                    ext_counts[ext_lang[ext]] += 1

                # Guardrail to avoid expensive walks
                if stats["file_count"] >= 2000:
                    break
            if stats["file_count"] >= 2000:
                break

        stats["has_tests"] = stats["test_file_count"] > 0
        if ext_counts:
            stats["dominant_language"] = max(ext_counts, key=ext_counts.get)
        return stats


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
    parallel_workers: int = 2,
    auto_approve: bool = True,
    research_depth: Literal["off", "shallow", "medium", "deep"] = RESEARCH_DEPTH_DEFAULT,
    validation_mode: Literal["none", "smoke", "targeted", "full"] = "targeted",
    orchestrator_retries: int = MAX_ORCHESTRATOR_RETRIES,
    plan_regen_retries: int = MAX_PLAN_REGEN_RETRIES,
    validation_retries: int = MAX_VALIDATION_RETRIES,
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
        enable_auto_fix: Enable auto-fix in validation
        parallel_workers: Number of parallel execution workers
        auto_approve: Auto-approve plans with warnings
        research_depth: Research depth (off/shallow/medium/deep)

    Returns:
        OrchestratorResult with execution outcome
    """
    config = OrchestratorConfig(
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
    )

    orchestrator = Orchestrator(project_root, config)
    return orchestrator.execute(user_request)
