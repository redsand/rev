"""
Orchestrator Agent for coordinating multi-agent workflow.

This module provides orchestration capabilities that coordinate all agents,
manage workflow, resolve conflicts, and make meta-decisions.
"""

import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rev.models.task import ExecutionPlan, TaskStatus
from rev.execution.planner import planning_mode
from rev.execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from rev.execution.validator import validate_execution, ValidationStatus, format_validation_feedback_for_llm
from rev.execution.researcher import research_codebase, ResearchFindings
from rev.execution.learner import LearningAgent, display_learning_suggestions
from rev.execution.executor import execution_mode, concurrent_execution_mode, fix_validation_failures
from rev.tools.registry import get_available_tools


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
    enable_learning: bool = True
    enable_research: bool = True
    enable_review: bool = True
    enable_validation: bool = True
    review_strictness: ReviewStrictness = ReviewStrictness.MODERATE
    enable_action_review: bool = False
    enable_auto_fix: bool = False
    parallel_workers: int = 2
    auto_approve: bool = True
    research_depth: str = "medium"  # shallow, medium, deep
    max_retries: int = 2


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
    agent_insights: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "phase_reached": self.phase_reached.value,
            "review_decision": self.review_decision.value if self.review_decision else None,
            "validation_status": self.validation_status.value if self.validation_status else None,
            "execution_time": self.execution_time,
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
        print("\n" + "=" * 60)
        print("ORCHESTRATOR - MULTI-AGENT COORDINATION")
        print("=" * 60)
        print(f"Task: {user_request[:100]}...")
        print(f"Agents enabled: ", end="")
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
        print("=" * 60)

        result = OrchestratorResult(success=False, phase_reached=AgentPhase.LEARNING)
        start_time = time.time()

        try:
            # Phase 1: Learning Agent - Get historical insights
            if self.config.enable_learning and self.learning_agent:
                self._update_phase(AgentPhase.LEARNING)
                suggestions = self.learning_agent.get_suggestions(user_request)
                if suggestions["similar_patterns"]:
                    display_learning_suggestions(suggestions, user_request)
                result.agent_insights["learning"] = suggestions

            # Phase 2: Research Agent - Explore codebase
            if self.config.enable_research:
                self._update_phase(AgentPhase.RESEARCH)
                quick_mode = self.config.research_depth == "shallow"
                research_findings = research_codebase(
                    user_request,
                    quick_mode=quick_mode,
                    search_depth=self.config.research_depth
                )
                result.research_findings = research_findings
                result.agent_insights["research"] = {
                    "files_found": len(research_findings.relevant_files),
                    "complexity": research_findings.estimated_complexity,
                    "warnings": len(research_findings.warnings)
                }

            # Phase 3: Planning Agent - Create execution plan
            self._update_phase(AgentPhase.PLANNING)
            plan = planning_mode(user_request)
            result.plan = plan

            if not plan.tasks:
                result.errors.append("Planning agent produced no tasks")
                result.phase_reached = AgentPhase.FAILED
                return result

            # Phase 4: Review Agent - Validate plan
            if self.config.enable_review:
                self._update_phase(AgentPhase.REVIEW)
                review = review_execution_plan(
                    plan,
                    user_request,
                    strictness=self.config.review_strictness,
                    auto_approve_low_risk=True
                )
                result.review_decision = review.decision
                result.agent_insights["review"] = {
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
                    # REQUIRES_CHANGES should stop execution regardless of auto_approve
                    # The review agent identified significant issues that need addressing
                    print("\n⚠️  Plan requires changes - stopping for manual review")
                    print(f"   Review confidence: {review.confidence_score:.0%}")
                    print(f"   Issues found: {len(review.issues)}")
                    print(f"   Security concerns: {len(review.security_concerns)}")
                    if review.suggestions:
                        print(f"   Suggestions: {len(review.suggestions)}")
                    result.errors.append("Plan requires changes before execution")
                    result.phase_reached = AgentPhase.REVIEW
                    return result

            # Phase 5: Execution Agent - Execute the plan
            self._update_phase(AgentPhase.EXECUTION)
            tools = get_available_tools()
            if self.config.parallel_workers > 1:
                concurrent_execution_mode(
                    plan,
                    max_workers=self.config.parallel_workers,
                    auto_approve=self.config.auto_approve,
                    tools=tools,
                    enable_action_review=self.config.enable_action_review
                )
            else:
                execution_mode(
                    plan,
                    auto_approve=self.config.auto_approve,
                    tools=tools,
                    enable_action_review=self.config.enable_action_review
                )

            # Phase 6: Validation Agent - Verify results
            if self.config.enable_validation:
                self._update_phase(AgentPhase.VALIDATION)
                validation = validate_execution(
                    plan,
                    user_request,
                    run_tests=True,
                    run_linter=True,
                    check_syntax=True,
                    enable_auto_fix=self.config.enable_auto_fix
                )
                result.validation_status = validation.overall_status
                result.agent_insights["validation"] = {
                    "status": validation.overall_status.value,
                    "checks_passed": sum(1 for r in validation.results if r.status == ValidationStatus.PASSED),
                    "checks_failed": sum(1 for r in validation.results if r.status == ValidationStatus.FAILED),
                    "auto_fixed": validation.auto_fixed
                }

                # Auto-fix loop for validation failures
                if validation.overall_status == ValidationStatus.FAILED:
                    result.errors.append("Initial validation failed")

                    retry_count = 0
                    while retry_count < self.config.max_retries and validation.overall_status == ValidationStatus.FAILED:
                        retry_count += 1
                        print(f"\n🔄 Validation Retry {retry_count}/{self.config.max_retries}")

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
                            max_fix_attempts=3
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
                            enable_auto_fix=False  # Don't auto-fix during retry validation
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

            # Complete
            self._update_phase(AgentPhase.COMPLETE)
            result.phase_reached = AgentPhase.COMPLETE

            # Learn from execution
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
            completed = sum(1 for t in plan.tasks if t.status == TaskStatus.COMPLETED)
            result.success = completed > 0 and (
                not self.config.enable_validation or
                result.validation_status in [ValidationStatus.PASSED, ValidationStatus.PASSED_WITH_WARNINGS, None]
            )

        except Exception as e:
            result.errors.append(str(e))
            result.phase_reached = AgentPhase.FAILED

        result.execution_time = time.time() - start_time
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

    def _display_summary(self, result: OrchestratorResult):
        """Display orchestration summary."""
        print("\n" + "=" * 60)
        print("ORCHESTRATION SUMMARY")
        print("=" * 60)

        status_icon = "✅" if result.success else "❌"
        print(f"{status_icon} Status: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"⏱️  Total time: {result.execution_time:.1f}s")
        print(f"📍 Phase reached: {result.phase_reached.value}")

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


def run_orchestrated(
    user_request: str,
    project_root: Path,
    enable_learning: bool = True,
    enable_research: bool = True,
    enable_review: bool = True,
    enable_validation: bool = True,
    review_strictness: str = "moderate",
    enable_action_review: bool = False,
    enable_auto_fix: bool = False,
    parallel_workers: int = 2,
    auto_approve: bool = True,
    research_depth: str = "medium"
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
        research_depth: Research depth (shallow/medium/deep)

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
        research_depth=research_depth
    )

    orchestrator = Orchestrator(project_root, config)
    return orchestrator.execute(user_request)
