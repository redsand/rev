#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Behavior-Modulated Debate Mode (MACI).

This module tests the debate system where:
- Proposer suggests solutions
- Skeptic challenges with evidence requests
- Judge evaluates and makes final decisions
- Contentiousness is modulated based on anchoring score
"""

import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any


class TestProposerAgent(unittest.TestCase):
    """Test the Proposer agent that suggests solutions."""

    def test_proposer_generates_solution_with_assumptions(self):
        """Proposer should generate a solution with explicit assumptions."""
        from rev.debate.proposer import ProposerAgent

        # Mock LLM client
        def mock_llm(**kwargs):
            return '''```json
{
  "solution": "Change module matching logic to use startswith()",
  "assumptions": ["Classes in package inherit parent module name"],
  "evidence": [
    {"source": "main.py:103", "description": "Current exact match fails for submodules"}
  ],
  "reasoning": [
    "Module split creates submodule names like lib.analysts.BreakoutAnalyst",
    "Exact match fails because parent is lib.analysts",
    "Using startswith() will match both parent and children"
  ],
  "confidence": 0.85
}
```'''

        proposer = ProposerAgent(llm_client=mock_llm)
        context = Mock()
        context.request = "Fix the auto-registration bug"

        proposal = proposer.propose(context)

        # Proposal must have required fields
        self.assertIsNotNone(proposal)
        self.assertIn("solution", proposal)
        self.assertIn("assumptions", proposal)
        self.assertIn("evidence", proposal)
        self.assertIn("confidence", proposal)

        # Confidence should be a float between 0 and 1
        self.assertIsInstance(proposal["confidence"], float)
        self.assertGreaterEqual(proposal["confidence"], 0.0)
        self.assertLessEqual(proposal["confidence"], 1.0)

    def test_proposer_includes_reasoning_steps(self):
        """Proposer should include step-by-step reasoning."""
        from rev.debate.proposer import ProposerAgent

        # Mock LLM client
        def mock_llm(**kwargs):
            return '''```json
{
  "solution": "Add database indexes",
  "assumptions": ["Queries are slow due to missing indexes"],
  "evidence": [],
  "reasoning": [
    "Step 1: Identify slow queries",
    "Step 2: Analyze query patterns",
    "Step 3: Add appropriate indexes"
  ],
  "confidence": 0.7
}
```'''

        proposer = ProposerAgent(llm_client=mock_llm)
        context = Mock()
        context.request = "Optimize database queries"

        proposal = proposer.propose(context)

        self.assertIn("reasoning", proposal)
        self.assertIsInstance(proposal["reasoning"], list)
        self.assertGreater(len(proposal["reasoning"]), 0)

    def test_proposer_cites_evidence(self):
        """Proposer should cite specific evidence (files, test results, etc.)."""
        from rev.debate.proposer import ProposerAgent

        # Mock LLM client
        def mock_llm(**kwargs):
            return '''```json
{
  "solution": "Update import statement in main.py",
  "assumptions": ["__init__.py exports all classes"],
  "evidence": [
    {"source": "main.py:51", "description": "Import statement location"},
    {"source": "lib/analysts/__init__.py:290", "description": "Classes exported via __all__"}
  ],
  "reasoning": ["Check files", "Update imports"],
  "confidence": 0.9
}
```'''

        proposer = ProposerAgent(llm_client=mock_llm)
        context = Mock()
        context.request = "Fix import error"
        context.files_read = ["main.py", "lib/analysts/__init__.py"]

        proposal = proposer.propose(context)

        # Evidence should reference actual files or tool outputs
        self.assertIsInstance(proposal["evidence"], list)
        for evidence_item in proposal["evidence"]:
            self.assertIn("source", evidence_item)  # e.g., "main.py:51"
            self.assertIn("description", evidence_item)


class TestSkepticAgent(unittest.TestCase):
    """Test the Skeptic agent that challenges proposals."""

    def test_skeptic_identifies_gaps_in_evidence(self):
        """Skeptic should identify missing evidence in proposal."""
        from rev.debate.skeptic import SkepticAgent

        # Mock LLM
        def mock_llm(**kwargs):
            return '''```json
{
  "gaps": ["No evidence that file exists", "No test of actual import behavior"],
  "evidence_requests": [
    {"type": "file_read", "description": "Read the file to verify it exists", "rationale": "Cannot change what doesn't exist"},
    {"type": "runtime_test", "description": "Test import statement", "rationale": "Verify it actually works"}
  ],
  "counter_examples": []
}
```'''

        skeptic = SkepticAgent(llm_client=mock_llm)

        # Proposal with weak evidence
        proposal = {
            "solution": "Change import statement",
            "assumptions": ["File exists"],
            "evidence": [],  # No evidence provided
            "confidence": 0.9
        }

        critique = skeptic.critique(proposal)

        self.assertIsNotNone(critique)
        self.assertIn("gaps", critique)
        self.assertGreater(len(critique["gaps"]), 0)
        self.assertIn("evidence_requests", critique)

    def test_skeptic_challenges_high_confidence_with_weak_evidence(self):
        """Skeptic should be more aggressive when confidence doesn't match evidence."""
        from rev.debate.skeptic import SkepticAgent

        # Mock LLM
        def mock_llm(**kwargs):
            return '''```json
{
  "gaps": ["No objective evidence", "Unfalsifiable assumption", "No error analysis"],
  "evidence_requests": [
    {"type": "test_run", "description": "Run tests with error injection", "rationale": "Prove errors don't happen"},
    {"type": "log_analysis", "description": "Analyze production error logs", "rationale": "Real-world error frequency"}
  ],
  "counter_examples": ["Network failures", "Invalid input", "Resource exhaustion"]
}
```'''

        skeptic = SkepticAgent(llm_client=mock_llm)

        proposal = {
            "solution": "Delete all error handling",
            "assumptions": ["Errors never happen"],
            "evidence": [{"source": "gut feeling", "description": "seems fine"}],
            "confidence": 0.95  # High confidence
        }

        critique = skeptic.critique(proposal)

        self.assertIn("skepticism_level", critique)
        self.assertGreaterEqual(critique["skepticism_level"], 0.7)  # Should be high
        self.assertGreater(len(critique["evidence_requests"]), 0)

    def test_skeptic_requests_specific_evidence(self):
        """Skeptic should request specific, actionable evidence."""
        from rev.debate.skeptic import SkepticAgent

        # Mock LLM
        def mock_llm(**kwargs):
            return '''```json
{
  "gaps": ["Pattern X not defined", "No validation of pattern"],
  "evidence_requests": [
    {"type": "runtime_test", "description": "Print actual module names to verify pattern", "rationale": "Validate assumption about naming"},
    {"type": "file_read", "description": "Read __init__.py to see actual exports", "rationale": "Understand module structure"},
    {"type": "test_run", "description": "Run import test with edge cases", "rationale": "Test pattern matching logic"}
  ],
  "counter_examples": []
}
```'''

        skeptic = SkepticAgent(llm_client=mock_llm)

        proposal = {
            "solution": "Modify module name matching logic",
            "assumptions": ["Module names follow pattern X"],
            "evidence": [],
            "confidence": 0.6
        }

        critique = skeptic.critique(proposal)

        # Evidence requests should be specific and actionable
        for request in critique["evidence_requests"]:
            self.assertIn("type", request)  # e.g., "runtime_test", "file_read", "test_run"
            self.assertIn("description", request)
            self.assertIn("rationale", request)

    def test_skeptic_proposes_counter_examples(self):
        """Skeptic should propose counter-examples or edge cases."""
        from rev.debate.skeptic import SkepticAgent

        # Mock LLM
        def mock_llm(**kwargs):
            return '''```json
{
  "gaps": ["Only tested one case"],
  "evidence_requests": [
    {"type": "test_run", "description": "Test with multiple module structures", "rationale": "Verify assumption holds generally"}
  ],
  "counter_examples": [
    "Third-party modules that don't follow naming convention",
    "Dynamically imported modules",
    "Modules with underscores or special characters",
    "What if parent is 'lib' but child is 'external_lib'?"
  ]
}
```'''

        skeptic = SkepticAgent(llm_client=mock_llm)

        proposal = {
            "solution": "Use startswith() for module matching",
            "assumptions": ["All submodules start with parent name"],
            "evidence": [{"source": "test", "description": "works for BreakoutAnalyst"}],
            "confidence": 0.8
        }

        critique = skeptic.critique(proposal)

        self.assertIn("counter_examples", critique)
        # Should identify edge cases like "what if module has different naming?"


class TestJudgeAgent(unittest.TestCase):
    """Test the Judge agent that evaluates debates."""

    def test_judge_accepts_well_supported_proposal(self):
        """Judge should accept proposals with strong evidence and no gaps."""
        from rev.debate.judge import JudgeAgent

        judge = JudgeAgent()

        proposal = {
            "solution": "Fix import by using startswith()",
            "assumptions": ["Classes in package have parent prefix"],
            "evidence": [
                {"source": "lib/analysts/__init__.py", "description": "exports all classes"},
                {"source": "runtime test", "description": "BreakoutAnalyst.__module__ = 'lib.analysts.BreakoutAnalyst'"}
            ],
            "confidence": 0.85
        }

        critique = {
            "gaps": [],
            "evidence_requests": [],
            "skepticism_level": 0.2
        }

        verdict = judge.decide(proposal, critique)

        self.assertEqual(verdict["decision"], "ACCEPT")
        self.assertIn("rationale", verdict)
        self.assertGreaterEqual(verdict["confidence"], 0.7)

    def test_judge_requires_more_evidence_when_gaps_exist(self):
        """Judge should request more evidence when gaps are identified."""
        from rev.debate.judge import JudgeAgent

        judge = JudgeAgent()

        proposal = {
            "solution": "Change all imports",
            "assumptions": ["This will work"],
            "evidence": [],
            "confidence": 0.5
        }

        critique = {
            "gaps": ["No runtime testing", "No verification of edge cases"],
            "evidence_requests": [
                {"type": "runtime_test", "description": "Test actual import behavior"}
            ],
            "skepticism_level": 0.8
        }

        verdict = judge.decide(proposal, critique)

        self.assertEqual(verdict["decision"], "REQUEST_EVIDENCE")
        self.assertIn("required_evidence", verdict)
        self.assertGreater(len(verdict["required_evidence"]), 0)

    def test_judge_rejects_unfalsifiable_proposals(self):
        """Judge should reject proposals that can't be tested or verified."""
        from rev.debate.judge import JudgeAgent

        judge = JudgeAgent()

        proposal = {
            "solution": "Make it work better",
            "assumptions": ["Magic happens"],
            "evidence": [{"source": "intuition", "description": "feels right"}],
            "confidence": 0.9
        }

        critique = {
            "gaps": ["Vague solution", "No measurable outcomes"],
            "evidence_requests": [{"type": "any", "description": "Any actual evidence"}],
            "skepticism_level": 0.9
        }

        verdict = judge.decide(proposal, critique)

        self.assertEqual(verdict["decision"], "REJECT")
        self.assertIn("rationale", verdict)
        self.assertIn("unfalsifiable", verdict["rationale"].lower())


class TestDebateController(unittest.TestCase):
    """Test the debate orchestration controller."""

    def test_debate_controller_runs_multiple_rounds(self):
        """Debate controller should run multiple rounds until convergence."""
        from rev.debate.controller import DebateController

        controller = DebateController()
        context = Mock()
        context.request = "Fix auto-registration"

        result = controller.run_debate(context, max_rounds=3)

        self.assertIsNotNone(result)
        self.assertIn("rounds", result)
        self.assertIn("final_decision", result)
        self.assertLessEqual(len(result["rounds"]), 3)

    def test_debate_controller_converges_on_agreement(self):
        """Debate should stop early if proposal is accepted."""
        from rev.debate.controller import DebateController

        # Create mock agents directly
        mock_proposer = Mock()
        mock_proposer.propose.return_value = {
            "solution": "Fix it",
            "assumptions": ["Valid"],
            "evidence": [{"source": "test", "description": "passes"}],
            "confidence": 0.9
        }

        mock_skeptic = Mock()
        mock_skeptic.critique.return_value = {
            "gaps": [],
            "evidence_requests": [],
            "skepticism_level": 0.1
        }

        mock_judge = Mock()
        mock_judge.decide.return_value = {
            "decision": "ACCEPT",
            "confidence": 0.9,
            "rationale": "Good proposal"
        }

        # Use dependency injection to pass mocks
        controller = DebateController(
            proposer=mock_proposer,
            skeptic=mock_skeptic,
            judge=mock_judge
        )

        context = Mock()
        result = controller.run_debate(context, max_rounds=5)

        # Should converge in 1 round
        self.assertEqual(len(result["rounds"]), 1)
        self.assertEqual(result["final_decision"], "ACCEPT")

    def test_debate_controller_tracks_disagreement_points(self):
        """Debate controller should track all disagreement points across rounds."""
        from rev.debate.controller import DebateController

        controller = DebateController()
        context = Mock()

        result = controller.run_debate(context, max_rounds=2)

        self.assertIn("disagreement_points", result)
        self.assertIsInstance(result["disagreement_points"], list)


class TestContentiousnessModulation(unittest.TestCase):
    """Test automatic modulation of debate contentiousness."""

    def test_low_anchoring_increases_skepticism(self):
        """Low anchoring score should increase skeptic's aggressiveness."""
        from rev.debate.controller import DebateController

        controller = DebateController()

        # Low anchoring = less confidence in current state
        anchoring_score = 0.2

        skepticism_level = controller.calculate_skepticism_level(anchoring_score)

        # Low anchor → high skepticism
        self.assertGreaterEqual(skepticism_level, 0.6)

    def test_high_anchoring_promotes_convergence(self):
        """High anchoring score should reduce skepticism and promote convergence."""
        from rev.debate.controller import DebateController

        controller = DebateController()

        # High anchoring = high confidence in current state
        anchoring_score = 0.9

        skepticism_level = controller.calculate_skepticism_level(anchoring_score)

        # High anchor → low skepticism
        self.assertLessEqual(skepticism_level, 0.4)

    def test_contentiousness_affects_evidence_threshold(self):
        """Higher contentiousness should require more evidence."""
        from rev.debate.controller import DebateController

        controller = DebateController()

        # High contentiousness (low anchoring)
        evidence_threshold_high = controller.calculate_evidence_threshold(anchoring_score=0.2)

        # Low contentiousness (high anchoring)
        evidence_threshold_low = controller.calculate_evidence_threshold(anchoring_score=0.8)

        self.assertGreater(evidence_threshold_high, evidence_threshold_low)


class TestDebateRoundsArtifact(unittest.TestCase):
    """Test generation of debate_rounds.json artifact."""

    def test_debate_rounds_json_structure(self):
        """debate_rounds.json should have correct structure."""
        from rev.debate.controller import DebateController

        controller = DebateController()
        context = Mock()
        context.request = "Test request"

        result = controller.run_debate(context, max_rounds=2)

        # Export to JSON
        json_output = controller.export_debate_rounds(result)
        data = json.loads(json_output)

        # Verify structure
        self.assertIn("request", data)
        self.assertIn("rounds", data)
        self.assertIn("final_decision", data)
        self.assertIn("disagreement_points", data)
        self.assertIn("evidence_requests", data)
        self.assertIn("timestamp", data)

    def test_debate_rounds_includes_all_evidence_requests(self):
        """Artifact should include all evidence requests across rounds."""
        from rev.debate.controller import DebateController

        controller = DebateController()
        context = Mock()

        result = controller.run_debate(context, max_rounds=3)
        json_output = controller.export_debate_rounds(result)
        data = json.loads(json_output)

        # Should aggregate evidence requests from all rounds
        self.assertIn("evidence_requests", data)
        self.assertIsInstance(data["evidence_requests"], list)

    def test_debate_rounds_saved_to_file(self):
        """debate_rounds.json should be saved to filesystem."""
        from rev.debate.controller import DebateController

        controller = DebateController()
        context = Mock()
        context.workspace_root = Path("/tmp/test")

        result = controller.run_debate(context, max_rounds=1)

        # Save artifact
        output_path = controller.save_debate_rounds(result, context.workspace_root)

        self.assertIsInstance(output_path, Path)
        self.assertTrue(str(output_path).endswith("debate_rounds.json"))


if __name__ == "__main__":
    unittest.main()
