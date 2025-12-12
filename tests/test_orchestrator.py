#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the orchestrator functionality.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from rev.execution.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    AgentPhase,
    run_orchestrated
)
from rev.execution.reviewer import ReviewDecision, ReviewStrictness, PlanReview
from rev.models.task import ExecutionPlan, RiskLevel, TaskStatus
from rev.execution.validator import ValidationReport, ValidationResult, ValidationStatus


def _route_stub(enable_validation: bool = False, parallel_workers: int = 1, max_retries: int = 0):
    return type(
        "Route",
        (),
        {
            "mode": "quick_edit",
            "reasoning": "",
            "enable_learning": False,
            "enable_research": False,
            "enable_review": True,
            "enable_validation": enable_validation,
            "review_strictness": "moderate",
            "parallel_workers": parallel_workers,
            "auto_approve": True,
            "enable_action_review": False,
            "enable_auto_fix": False,
            "research_depth": "off",
            "max_retries": max_retries,
            "max_plan_tasks": None,
        },
    )()


class TestOrchestratorReviewHandling(unittest.TestCase):
    """Test orchestrator handling of review decisions."""

    @patch('rev.execution.orchestrator.concurrent_execution_mode')
    @patch('rev.execution.orchestrator.execution_mode')
    @patch('rev.execution.router.TaskRouter')
    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_requires_changes_with_retry_success(
        self, mock_research, mock_planning, mock_review, mock_router, mock_exec, mock_concurrent
    ):
        """Test that REQUIRES_CHANGES triggers retry loop and succeeds on second attempt.

        This test verifies that the orchestrator will regenerate the plan when
        review says REQUIRES_CHANGES, and that it eventually succeeds when the
        regenerated plan is approved.
        """
        # Setup initial plan
        initial_plan = ExecutionPlan()
        initial_plan.add_task("Incomplete security audit", "general")
        initial_plan.tasks[0].risk_level = RiskLevel.HIGH

        # Setup improved plan after feedback
        improved_plan = ExecutionPlan()
        improved_plan.add_task("Run AddressSanitizer for memory corruption", "test")
        improved_plan.add_task("Run Valgrind for use-after-free detection", "test")
        improved_plan.add_task("Analyze results and report findings", "review")
        for task in improved_plan.tasks:
            task.risk_level = RiskLevel.MEDIUM

        # Mock planning_mode to return initial plan first, then improved plan
        mock_planning.side_effect = [initial_plan, improved_plan]

        # Setup mock research
        mock_research.return_value = MagicMock(
            relevant_files=[],
            estimated_complexity="HIGH",
            warnings=[]
        )

        def complete_tasks(plan_obj, **_kwargs):
            for task in plan_obj.tasks:
                task.status = TaskStatus.COMPLETED

        mock_exec.side_effect = complete_tasks
        mock_concurrent.side_effect = complete_tasks

        mock_router.return_value = type("R", (), {"route": lambda *_a, **_k: _route_stub()})()

        # Setup mock review: first REQUIRES_CHANGES, then APPROVED
        review_needs_changes = PlanReview()
        review_needs_changes.decision = ReviewDecision.REQUIRES_CHANGES
        review_needs_changes.confidence_score = 0.95
        review_needs_changes.issues = [
            {
                "severity": "critical",
                "task_id": 0,
                "description": "Vague task description",
                "impact": "Could miss critical vulnerabilities"
            }
        ]
        review_needs_changes.security_concerns = [
            "No adequate coverage for security analysis"
        ]
        review_needs_changes.suggestions = [
            "Add static analysis with memory error detection"
        ]
        review_needs_changes.overall_assessment = "Plan is insufficient"

        review_approved = PlanReview()
        review_approved.decision = ReviewDecision.APPROVED
        review_approved.confidence_score = 0.90
        review_approved.overall_assessment = "Plan now addresses security concerns"

        mock_review.side_effect = [review_needs_changes, review_approved]

        # Create orchestrator with max_retries=2
        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=True,
            enable_review=True,
            enable_validation=False,
            auto_approve=True,
            max_retries=2
        )

        orchestrator = Orchestrator(Path("/test"), config)
        result = orchestrator.execute("find security bugs")

        # Verify plan was regenerated
        self.assertEqual(mock_planning.call_count, 2, "Planning should be called twice")
        self.assertEqual(mock_review.call_count, 2, "Review should be called twice")

        # Verify second planning call included feedback
        second_call_args = mock_planning.call_args_list[1][0][0]
        self.assertIn("IMPORTANT", second_call_args)
        self.assertIn("review feedback", second_call_args.lower())

        # Verify execution did NOT stop at review (it should proceed)
        self.assertNotEqual(result.phase_reached, AgentPhase.REVIEW)

    @patch('rev.execution.router.TaskRouter')
    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_requires_changes_exhausts_retries(
        self, mock_research, mock_planning, mock_review, mock_router
    ):
        """Test that orchestrator stops after exhausting max retries.

        This test verifies that if the plan keeps requiring changes after
        max_retries attempts, the orchestrator stops and reports failure.
        """
        # Setup mock plan
        plan = ExecutionPlan()
        plan.add_task("Incomplete security audit", "general")
        plan.tasks[0].risk_level = RiskLevel.HIGH
        mock_planning.return_value = plan

        # Setup mock research
        mock_research.return_value = MagicMock(
            relevant_files=[],
            estimated_complexity="HIGH",
            warnings=[]
        )

        mock_router.return_value = type("R", (), {"route": lambda *_a, **_k: _route_stub()})()

        # Setup mock review to always return REQUIRES_CHANGES
        review = PlanReview()
        review.decision = ReviewDecision.REQUIRES_CHANGES
        review.confidence_score = 0.95
        review.issues = [
            {
                "severity": "critical",
                "task_id": 0,
                "description": "Still incomplete",
                "impact": "Not good enough"
            }
        ]
        review.security_concerns = ["Still has issues"]
        review.suggestions = ["Keep trying"]
        review.overall_assessment = "Plan is still insufficient"
        mock_review.return_value = review

        # Create orchestrator with max_retries=2
        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=True,
            enable_review=True,
            enable_validation=False,
            auto_approve=True,
            max_retries=2  # Will try: initial + 2 retries = 3 total attempts
        )

        orchestrator = Orchestrator(Path("/test"), config)
        result = orchestrator.execute("find security bugs")

        expected_attempts = config.max_retries + 1
        expected_calls = expected_attempts * expected_attempts

        # Verify it tried 3 times per execution attempt (and retried executions)
        self.assertEqual(mock_planning.call_count, expected_calls, "Planning should run on each regeneration across retries")
        self.assertEqual(mock_review.call_count, expected_calls, "Review should run for each regenerated plan across retries")

        # Verify execution stopped at review phase with error
        self.assertEqual(result.phase_reached, AgentPhase.REVIEW)
        self.assertFalse(result.success)
        self.assertTrue(any("requires changes" in err.lower() for err in result.errors))
        self.assertTrue(any("2 regeneration" in err for err in result.errors))

    @patch('rev.execution.router.TaskRouter')
    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_rejected_always_stops_execution(
        self, mock_research, mock_planning, mock_review, mock_router
    ):
        """Test that REJECTED always stops execution."""
        # Setup mock plan
        plan = ExecutionPlan()
        plan.add_task("Dangerous operation", "general")
        plan.tasks[0].risk_level = RiskLevel.CRITICAL
        mock_planning.return_value = plan

        # Setup mock research
        mock_research.return_value = MagicMock(
            relevant_files=[],
            estimated_complexity="HIGH",
            warnings=[]
        )

        # Setup mock review with REJECTED decision
        review = PlanReview()
        review.decision = ReviewDecision.REJECTED
        review.confidence_score = 0.99
        review.issues = [
            {
                "severity": "critical",
                "task_id": 0,
                "description": "Will cause data loss",
                "impact": "Unrecoverable damage"
            }
        ]
        review.security_concerns = ["Critical security violation"]
        mock_review.return_value = review

        mock_router.return_value = type("R", (), {"route": lambda *_a, **_k: _route_stub()})()

        # Create orchestrator with auto_approve=True
        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=True,
            enable_review=True,
            enable_validation=False,
            auto_approve=True
        )

        orchestrator = Orchestrator(Path("/test"), config)
        result = orchestrator.execute("delete everything")

        # Verify execution stopped at review phase
        self.assertEqual(result.phase_reached, AgentPhase.REVIEW)
        self.assertFalse(result.success)
        self.assertIn("rejected", result.errors[0].lower())

    @patch('rev.execution.router.TaskRouter')
    @patch('rev.execution.orchestrator.concurrent_execution_mode')
    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_approved_proceeds_to_execution(
        self, mock_research, mock_planning, mock_review, mock_execution, mock_router
    ):
        """Test that APPROVED plans proceed to execution."""
        # Setup mock plan
        plan = ExecutionPlan()
        plan.add_task("Safe operation", "general")
        plan.tasks[0].risk_level = RiskLevel.LOW
        mock_planning.return_value = plan

        # Setup mock research
        mock_research.return_value = MagicMock(
            relevant_files=[],
            estimated_complexity="LOW",
            warnings=[]
        )

        # Setup mock review with APPROVED decision
        review = PlanReview()
        review.decision = ReviewDecision.APPROVED
        review.confidence_score = 0.95
        mock_review.return_value = review

        mock_router.return_value = type("R", (), {"route": lambda *_a, **_k: _route_stub(parallel_workers=2, max_retries=2)})()

        def mark_completed(plan_obj, **_kwargs):
            for task in plan_obj.tasks:
                task.status = TaskStatus.COMPLETED

        mock_execution.side_effect = mark_completed

        # Create orchestrator
        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=True,
            enable_review=True,
            enable_validation=False,
            auto_approve=True,
            parallel_workers=2
        )

        orchestrator = Orchestrator(Path("/test"), config)
        result = orchestrator.execute("read a file")

        # Verify execution proceeded past review phase
        self.assertNotEqual(result.phase_reached, AgentPhase.REVIEW)

        # Verify execution was called
        mock_execution.assert_called_once()


class TestValidationHoldBehavior(unittest.TestCase):
    """Tests for the validation hold-and-resume loop."""

    @staticmethod
    def _validation_report(status: ValidationStatus) -> ValidationReport:
        report = ValidationReport()
        report.overall_status = status
        report.results = [
            ValidationResult(
                name="tests", status=status, message="placeholder"
            )
        ]
        return report

    @patch("rev.execution.orchestrator.validate_execution")
    @patch("rev.execution.orchestrator.execution_mode")
    @patch("rev.execution.orchestrator.review_execution_plan")
    @patch("rev.execution.orchestrator.planning_mode")
    @patch("rev.execution.orchestrator.research_codebase")
    @patch("rev.execution.router.TaskRouter")
    def test_manual_resume_retries_validation(
        self,
        mock_router,
        mock_research,
        mock_planning,
        mock_review,
        mock_execution,
        mock_validate,
    ):
        """When user signals resume, validation should rerun until passing."""

        mock_router.return_value = type(
            "R", (), {"route": lambda *_args, **_kwargs: _route_stub(enable_validation=True)}
        )()
        mock_research.return_value = MagicMock(
            relevant_files=[], estimated_complexity="low", warnings=[]
        )
        approved_review = PlanReview()
        approved_review.decision = ReviewDecision.APPROVED
        approved_review.confidence_score = 0.9
        mock_review.return_value = approved_review

        plan = ExecutionPlan()
        plan.add_task("do work")
        mock_planning.return_value = plan

        def complete_tasks(plan_obj, **_kwargs):
            for task in plan_obj.tasks:
                task.status = TaskStatus.COMPLETED

        mock_execution.side_effect = complete_tasks

        mock_validate.side_effect = [
            self._validation_report(ValidationStatus.FAILED),
            self._validation_report(ValidationStatus.PASSED),
        ]

        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=False,
            enable_review=True,
            enable_validation=True,
            max_retries=0,
            parallel_workers=1,
        )

        with patch.object(Orchestrator, "_wait_for_user_resume", return_value=True):
            orchestrator = Orchestrator(Path("/test"), config)
            result = orchestrator.execute("do stuff")

        self.assertEqual(mock_validate.call_count, 2)
        self.assertEqual(result.validation_status, ValidationStatus.PASSED)
        self.assertEqual(result.phase_reached, AgentPhase.COMPLETE)
        self.assertTrue(result.success)

    @patch("rev.execution.orchestrator.validate_execution")
    @patch("rev.execution.orchestrator.execution_mode")
    @patch("rev.execution.orchestrator.review_execution_plan")
    @patch("rev.execution.orchestrator.planning_mode")
    @patch("rev.execution.orchestrator.research_codebase")
    @patch("rev.execution.router.TaskRouter")
    def test_abort_keeps_run_at_validation_phase(
        self,
        mock_router,
        mock_research,
        mock_planning,
        mock_review,
        mock_execution,
        mock_validate,
    ):
        """Abort command should stop at validation without marking success."""

        mock_router.return_value = type(
            "R", (), {"route": lambda *_args, **_kwargs: _route_stub(enable_validation=True)}
        )()
        mock_research.return_value = MagicMock(
            relevant_files=[], estimated_complexity="low", warnings=[]
        )
        approved_review = PlanReview()
        approved_review.decision = ReviewDecision.APPROVED
        approved_review.confidence_score = 0.9
        mock_review.return_value = approved_review

        plan = ExecutionPlan()
        plan.add_task("do work")
        mock_planning.return_value = plan

        def complete_tasks(plan_obj, **_kwargs):
            for task in plan_obj.tasks:
                task.status = TaskStatus.COMPLETED

        mock_execution.side_effect = complete_tasks

        mock_validate.side_effect = [self._validation_report(ValidationStatus.FAILED)]

        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=False,
            enable_review=True,
            enable_validation=True,
            max_retries=0,
            parallel_workers=1,
        )

        with patch.object(Orchestrator, "_wait_for_user_resume", return_value=False):
            orchestrator = Orchestrator(Path("/test"), config)
            result = orchestrator.execute("do stuff")

        self.assertEqual(mock_validate.call_count, 1)
        self.assertEqual(result.validation_status, ValidationStatus.FAILED)
        self.assertEqual(result.phase_reached, AgentPhase.VALIDATION)
        self.assertFalse(result.success)


class TestOrchestratorConfig(unittest.TestCase):
    """Test orchestrator configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OrchestratorConfig()
        self.assertFalse(config.enable_learning)
        self.assertTrue(config.enable_research)
        self.assertTrue(config.enable_review)
        self.assertTrue(config.enable_validation)
        self.assertEqual(config.review_strictness, ReviewStrictness.MODERATE)
        self.assertEqual(config.parallel_workers, 2)
        self.assertTrue(config.auto_approve)

    def test_custom_config(self):
        """Test custom configuration."""
        config = OrchestratorConfig(
            enable_learning=False,
            review_strictness=ReviewStrictness.STRICT,
            parallel_workers=4,
            auto_approve=False
        )
        self.assertFalse(config.enable_learning)
        self.assertEqual(config.review_strictness, ReviewStrictness.STRICT)
        self.assertEqual(config.parallel_workers, 4)
        self.assertFalse(config.auto_approve)


if __name__ == "__main__":
    unittest.main()
