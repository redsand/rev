#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Anchoring Score Instrumentation (UCCT-inspired).

The anchoring score is a scalar metric (0-1) representing confidence in current state.
It's based on:
- Evidence density: How much evidence has been gathered
- Mismatch risk: Uncertainty or conflicting information
- Budget usage: Computational budget consumed

This score influences debate contentiousness in Feature 1.
"""

import unittest
from unittest.mock import Mock
from typing import Dict, List, Any


class TestEvidenceDensity(unittest.TestCase):
    """Test evidence density calculation."""

    def test_zero_evidence_gives_zero_density(self):
        """No evidence should give 0.0 density."""
        from rev.anchoring.evidence_density import calculate_evidence_density

        context = Mock()
        context.files_read = []
        context.tool_events = []
        context.validation_results = {}

        density = calculate_evidence_density(context)

        self.assertEqual(density, 0.0)

    def test_evidence_density_increases_with_file_reads(self):
        """Reading files should increase evidence density."""
        from rev.anchoring.evidence_density import calculate_evidence_density

        context = Mock()
        context.files_read = ["file1.py", "file2.py", "file3.py"]
        context.tool_events = []
        context.validation_results = {}

        density = calculate_evidence_density(context)

        self.assertGreater(density, 0.0)
        self.assertLessEqual(density, 1.0)

    def test_evidence_density_increases_with_tool_usage(self):
        """Using tools should increase evidence density."""
        from rev.anchoring.evidence_density import calculate_evidence_density

        context = Mock()
        context.files_read = []
        context.tool_events = [
            {"tool": "grep", "result": "found matches"},
            {"tool": "glob", "result": "found files"},
            {"tool": "execute_python", "result": "ran test"}
        ]
        context.validation_results = {}

        density = calculate_evidence_density(context)

        self.assertGreater(density, 0.0)

    def test_validation_results_increase_density(self):
        """Validation results (tests, linting) increase evidence density."""
        from rev.anchoring.evidence_density import calculate_evidence_density

        context = Mock()
        context.files_read = ["test.py"]
        context.tool_events = []
        context.validation_results = {
            "pytest": {"rc": 0, "passed": 5},
            "mypy": {"rc": 0, "errors": 0}
        }

        density = calculate_evidence_density(context)

        self.assertGreater(density, 0.5)  # Validation is high-quality evidence

    def test_density_caps_at_one(self):
        """Evidence density should never exceed 1.0."""
        from rev.anchoring.evidence_density import calculate_evidence_density

        context = Mock()
        # Overwhelming amount of evidence
        context.files_read = [f"file{i}.py" for i in range(100)]
        context.tool_events = [{"tool": f"tool{i}", "result": "data"} for i in range(100)]
        context.validation_results = {"pytest": {"rc": 0, "passed": 100}}

        density = calculate_evidence_density(context)

        self.assertLessEqual(density, 1.0)


class TestMismatchRisk(unittest.TestCase):
    """Test mismatch risk calculation."""

    def test_no_conflicts_gives_zero_risk(self):
        """No conflicts or uncertainties should give 0.0 risk."""
        from rev.anchoring.mismatch_risk import calculate_mismatch_risk

        context = Mock()
        context.validation_results = {"pytest": {"rc": 0, "passed": 5}}
        context.tool_events = []
        context.failed_actions = []

        risk = calculate_mismatch_risk(context)

        self.assertEqual(risk, 0.0)

    def test_failed_validation_increases_risk(self):
        """Failed validation should increase mismatch risk."""
        from rev.anchoring.mismatch_risk import calculate_mismatch_risk

        context = Mock()
        context.validation_results = {
            "pytest": {"rc": 1, "passed": 3, "failed": 2}
        }
        context.tool_events = []
        context.failed_actions = []

        risk = calculate_mismatch_risk(context)

        self.assertGreater(risk, 0.0)
        self.assertLessEqual(risk, 1.0)

    def test_failed_actions_increase_risk(self):
        """Failed actions (edit failures, tool errors) increase risk."""
        from rev.anchoring.mismatch_risk import calculate_mismatch_risk

        context = Mock()
        context.validation_results = {}
        context.tool_events = []
        context.failed_actions = [
            {"action": "replace_in_file", "error": "string not found"},
            {"action": "apply_patch", "error": "patch failed"}
        ]

        risk = calculate_mismatch_risk(context)

        self.assertGreater(risk, 0.3)

    def test_conflicting_tool_results_increase_risk(self):
        """Conflicting information from tools increases risk."""
        from rev.anchoring.mismatch_risk import calculate_mismatch_risk

        context = Mock()
        context.validation_results = {}
        context.tool_events = [
            {"tool": "grep", "result": "pattern found in 5 files"},
            {"tool": "glob", "result": "0 files matching pattern"}  # Conflict!
        ]
        context.failed_actions = []

        risk = calculate_mismatch_risk(context)

        self.assertGreater(risk, 0.0)

    def test_risk_caps_at_one(self):
        """Mismatch risk should never exceed 1.0."""
        from rev.anchoring.mismatch_risk import calculate_mismatch_risk

        context = Mock()
        # Many failures
        context.validation_results = {
            "pytest": {"rc": 1, "failed": 50},
            "mypy": {"rc": 1, "errors": 100}
        }
        context.tool_events = []
        context.failed_actions = [{"action": f"fail{i}", "error": "err"} for i in range(50)]

        risk = calculate_mismatch_risk(context)

        self.assertLessEqual(risk, 1.0)


class TestBudgetUsage(unittest.TestCase):
    """Test budget usage calculation."""

    def test_zero_usage_at_start(self):
        """At start of task, budget usage should be 0.0."""
        from rev.anchoring.budget_usage import calculate_budget_usage

        context = Mock()
        context.llm_calls = 0
        context.tool_calls = 0
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        usage = calculate_budget_usage(context)

        self.assertEqual(usage, 0.0)

    def test_budget_usage_increases_with_llm_calls(self):
        """LLM calls should increase budget usage."""
        from rev.anchoring.budget_usage import calculate_budget_usage

        context = Mock()
        context.llm_calls = 50
        context.tool_calls = 0
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        usage = calculate_budget_usage(context)

        self.assertGreater(usage, 0.0)
        self.assertLess(usage, 1.0)

    def test_budget_usage_increases_with_tool_calls(self):
        """Tool calls should increase budget usage."""
        from rev.anchoring.budget_usage import calculate_budget_usage

        context = Mock()
        context.llm_calls = 0
        context.tool_calls = 250
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        usage = calculate_budget_usage(context)

        self.assertGreater(usage, 0.0)
        self.assertLess(usage, 1.0)

    def test_budget_usage_reaches_one_at_limit(self):
        """Budget usage should reach 1.0 when limits are hit."""
        from rev.anchoring.budget_usage import calculate_budget_usage

        context = Mock()
        context.llm_calls = 100
        context.tool_calls = 500
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        usage = calculate_budget_usage(context)

        self.assertEqual(usage, 1.0)

    def test_budget_usage_never_exceeds_one(self):
        """Budget usage should cap at 1.0 even if over limit."""
        from rev.anchoring.budget_usage import calculate_budget_usage

        context = Mock()
        context.llm_calls = 200  # Over limit
        context.tool_calls = 1000  # Over limit
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        usage = calculate_budget_usage(context)

        self.assertLessEqual(usage, 1.0)


class TestAnchoringScore(unittest.TestCase):
    """Test combined anchoring score calculation."""

    def test_anchoring_score_combines_all_factors(self):
        """Anchoring score should combine evidence, risk, and budget."""
        from rev.anchoring.score import calculate_anchoring_score

        context = Mock()
        # High evidence
        context.files_read = ["f1.py", "f2.py", "f3.py"]
        context.tool_events = [{"tool": "grep"}, {"tool": "glob"}]
        context.validation_results = {"pytest": {"rc": 0, "passed": 5}}
        # Low risk
        context.failed_actions = []
        # Moderate budget
        context.llm_calls = 25
        context.tool_calls = 100
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        score = calculate_anchoring_score(context)

        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_high_evidence_low_risk_gives_high_score(self):
        """High evidence + low risk → high anchoring score (confident)."""
        from rev.anchoring.score import calculate_anchoring_score

        context = Mock()
        context.files_read = [f"file{i}.py" for i in range(10)]
        context.tool_events = [{"tool": f"tool{i}"} for i in range(10)]
        context.validation_results = {"pytest": {"rc": 0, "passed": 20}}
        context.failed_actions = []
        context.llm_calls = 20
        context.tool_calls = 50
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        score = calculate_anchoring_score(context)

        self.assertGreaterEqual(score, 0.7)

    def test_low_evidence_high_risk_gives_low_score(self):
        """Low evidence + high risk → low anchoring score (uncertain)."""
        from rev.anchoring.score import calculate_anchoring_score

        context = Mock()
        context.files_read = []
        context.tool_events = []
        context.validation_results = {"pytest": {"rc": 1, "failed": 10}}
        context.failed_actions = [{"action": "edit", "error": "failed"}]
        context.llm_calls = 5
        context.tool_calls = 10
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        score = calculate_anchoring_score(context)

        self.assertLessEqual(score, 0.3)

    def test_high_budget_usage_reduces_score(self):
        """High budget usage should reduce anchoring score (less time to gather evidence)."""
        from rev.anchoring.score import calculate_anchoring_score

        context = Mock()
        context.files_read = ["f1.py"]
        context.tool_events = []
        context.validation_results = {}
        context.failed_actions = []
        context.llm_calls = 95  # Near limit
        context.tool_calls = 480  # Near limit
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        score = calculate_anchoring_score(context)

        # High budget usage means we're running out of time, lowering confidence
        self.assertLess(score, 0.5)

    def test_anchoring_score_always_in_valid_range(self):
        """Anchoring score must always be in [0, 1]."""
        from rev.anchoring.score import calculate_anchoring_score

        # Test with extreme values
        context = Mock()
        context.files_read = []
        context.tool_events = []
        context.validation_results = {}
        context.failed_actions = []
        context.llm_calls = 0
        context.tool_calls = 0
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        score = calculate_anchoring_score(context)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestAnchoringIntegrationWithDebate(unittest.TestCase):
    """Test integration of anchoring score with debate mode."""

    def test_low_anchoring_triggers_contentious_debate(self):
        """Low anchoring score should trigger contentious debate."""
        from rev.anchoring.score import calculate_anchoring_score
        from rev.debate.controller import DebateController

        # Context with low anchoring
        context = Mock()
        context.files_read = []
        context.tool_events = []
        context.validation_results = {"pytest": {"rc": 1, "failed": 5}}
        context.failed_actions = [{"action": "edit", "error": "failed"}]
        context.llm_calls = 10
        context.tool_calls = 20
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        anchoring = calculate_anchoring_score(context)
        self.assertLess(anchoring, 0.5)

        # Debate should be contentious
        controller = DebateController()
        skepticism = controller.calculate_skepticism_level(anchoring)

        # Low anchoring → high skepticism
        self.assertGreater(skepticism, 0.5)

    def test_high_anchoring_triggers_cooperative_debate(self):
        """High anchoring score should trigger cooperative debate."""
        from rev.anchoring.score import calculate_anchoring_score
        from rev.debate.controller import DebateController

        # Context with high anchoring
        context = Mock()
        context.files_read = [f"file{i}.py" for i in range(5)]
        context.tool_events = [{"tool": "test"}]
        context.validation_results = {"pytest": {"rc": 0, "passed": 10}}
        context.failed_actions = []
        context.llm_calls = 15
        context.tool_calls = 30
        context.max_llm_calls = 100
        context.max_tool_calls = 500

        anchoring = calculate_anchoring_score(context)
        self.assertGreater(anchoring, 0.5)

        # Debate should be cooperative
        controller = DebateController()
        skepticism = controller.calculate_skepticism_level(anchoring)

        # High anchoring → low skepticism
        self.assertLess(skepticism, 0.5)


class TestAnchoringScoreTracking(unittest.TestCase):
    """Test anchoring score tracking in execution context."""

    def test_anchoring_score_stored_in_context(self):
        """Anchoring score should be calculated and stored in context."""
        from rev.anchoring.tracker import update_anchoring_score

        context = Mock()
        context.files_read = ["test.py"]
        context.tool_events = []
        context.validation_results = {}
        context.failed_actions = []
        context.llm_calls = 5
        context.tool_calls = 10
        context.max_llm_calls = 100
        context.max_tool_calls = 500
        context.anchoring_score = None

        update_anchoring_score(context)

        self.assertIsNotNone(context.anchoring_score)
        self.assertGreaterEqual(context.anchoring_score, 0.0)
        self.assertLessEqual(context.anchoring_score, 1.0)

    def test_anchoring_score_updates_over_time(self):
        """Anchoring score should update as task progresses."""
        from rev.anchoring.tracker import update_anchoring_score

        context = Mock()
        context.files_read = []
        context.tool_events = []
        context.validation_results = {}
        context.failed_actions = []
        context.llm_calls = 5
        context.tool_calls = 10
        context.max_llm_calls = 100
        context.max_tool_calls = 500
        context.anchoring_score = None

        # First update - low evidence
        update_anchoring_score(context)
        first_score = context.anchoring_score

        # Gather more evidence
        context.files_read = ["f1.py", "f2.py"]
        context.validation_results = {"pytest": {"rc": 0, "passed": 5}}

        # Second update - more evidence
        update_anchoring_score(context)
        second_score = context.anchoring_score

        # Score should increase with more evidence
        self.assertGreater(second_score, first_score)


if __name__ == "__main__":
    unittest.main()
