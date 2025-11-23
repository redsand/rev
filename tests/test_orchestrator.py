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
from rev.models.task import ExecutionPlan, RiskLevel


class TestOrchestratorReviewHandling(unittest.TestCase):
    """Test orchestrator handling of review decisions."""

    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_requires_changes_stops_execution_with_auto_approve(
        self, mock_research, mock_planning, mock_review
    ):
        """Test that REQUIRES_CHANGES stops execution even with auto_approve=True.

        This is a regression test for the bug where REQUIRES_CHANGES was ignored
        when auto_approve was True, allowing execution to proceed despite critical
        review findings.
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

        # Setup mock review with REQUIRES_CHANGES decision
        review = PlanReview()
        review.decision = ReviewDecision.REQUIRES_CHANGES
        review.confidence_score = 0.95
        review.issues = [
            {
                "severity": "critical",
                "task_id": 0,
                "description": "Vague task description",
                "impact": "Could miss critical vulnerabilities"
            },
            {
                "severity": "critical",
                "task_id": 0,
                "description": "No static analysis tools specified",
                "impact": "High likelihood of missing memory safety issues"
            }
        ]
        review.security_concerns = [
            "No adequate coverage for security analysis",
            "No specific tools or methodologies mentioned"
        ]
        review.suggestions = [
            "Add static analysis with memory error detection",
            "Include dynamic analysis with fuzzing"
        ]
        review.overall_assessment = "Plan is insufficient for security goals"
        mock_review.return_value = review

        # Create orchestrator with auto_approve=True (the problematic config)
        config = OrchestratorConfig(
            enable_learning=False,
            enable_research=True,
            enable_review=True,
            enable_validation=False,
            auto_approve=True  # This was causing the bug
        )

        orchestrator = Orchestrator(Path("/test"), config)
        result = orchestrator.execute("find security bugs")

        # Verify execution stopped at review phase
        self.assertEqual(result.phase_reached, AgentPhase.REVIEW)
        self.assertFalse(result.success)
        self.assertIn("requires changes", result.errors[0].lower())

        # Verify review was actually called
        mock_review.assert_called_once()

    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_rejected_always_stops_execution(
        self, mock_research, mock_planning, mock_review
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

    @patch('rev.execution.orchestrator.concurrent_execution_mode')
    @patch('rev.execution.orchestrator.review_execution_plan')
    @patch('rev.execution.orchestrator.planning_mode')
    @patch('rev.execution.orchestrator.research_codebase')
    def test_approved_proceeds_to_execution(
        self, mock_research, mock_planning, mock_review, mock_execution
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


class TestOrchestratorConfig(unittest.TestCase):
    """Test orchestrator configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OrchestratorConfig()
        self.assertTrue(config.enable_learning)
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
