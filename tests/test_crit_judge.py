#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CRIT Judge - Critical Reasoning and Inspection Tool."""

import pytest
from unittest.mock import Mock, patch

from rev.agents.crit_judge import (
    CRITJudge,
    CRITJudgement,
    CriticalQuestion,
    Verdict,
    JudgementType
)
from rev.models.task import Task, ExecutionPlan, TaskStatus, RiskLevel
from rev.models.dod import DefinitionOfDone, Deliverable, DeliverableType


@pytest.fixture
def crit_judge():
    """Create a CRIT judge (without LLM for faster tests)."""
    return CRITJudge(use_llm=False)


@pytest.fixture
def crit_judge_with_llm():
    """Create a CRIT judge with LLM enabled."""
    return CRITJudge(use_llm=True)


class TestPlanEvaluation:
    """Test plan evaluation functionality."""

    def test_empty_plan_rejected(self, crit_judge):
        """Empty plan should be rejected."""
        plan = ExecutionPlan()
        judgement = crit_judge.evaluate_plan(plan, "Do something")

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("no tasks" in c.lower() or "empty" in c.lower() for c in judgement.concerns)
        assert any(q.severity == "critical" for q in judgement.questions)

    def test_simple_valid_plan_approved(self, crit_judge):
        """Simple valid plan should be approved."""
        plan = ExecutionPlan()
        plan.add_task("Update README.md", action_type="edit")
        plan.add_task("Run tests", action_type="test")

        judgement = crit_judge.evaluate_plan(plan, "Update docs and test")

        assert judgement.verdict in [Verdict.APPROVED, Verdict.NEEDS_REVISION]
        assert judgement.judgement_type == JudgementType.PLAN_EVALUATION

    def test_circular_dependency_detected(self, crit_judge):
        """Circular dependencies should raise concerns."""
        plan = ExecutionPlan()
        task1 = plan.add_task("Task 1", dependencies=[])
        task2 = plan.add_task("Task 2", dependencies=[0])

        # Create circular dependency
        task1.dependencies = [1]

        judgement = crit_judge.evaluate_plan(plan, "Test circular deps")

        assert len(judgement.concerns) > 0
        assert any("circular" in c.lower() for c in judgement.concerns)

    def test_invalid_dependency_detected(self, crit_judge):
        """Invalid dependencies should raise concerns."""
        plan = ExecutionPlan()
        plan.add_task("Task 1", dependencies=[999])  # Non-existent task

        judgement = crit_judge.evaluate_plan(plan, "Test invalid deps")

        assert len(judgement.concerns) > 0
        assert any("non-existent" in c.lower() for c in judgement.concerns)

    def test_high_risk_without_validation(self, crit_judge):
        """High-risk tasks without validation should raise concerns."""
        plan = ExecutionPlan()
        task = plan.add_task("Delete production database", action_type="delete")
        task.risk_level = RiskLevel.HIGH
        task.validation_steps = []  # No validation!

        judgement = crit_judge.evaluate_plan(plan, "Clean up database")

        assert len(judgement.concerns) > 0
        assert any("validation" in c.lower() for c in judgement.concerns)
        assert any(q.severity in ["high", "critical"] for q in judgement.questions)

    def test_destructive_without_rollback(self, crit_judge):
        """Destructive operations without rollback should raise critical concerns."""
        plan = ExecutionPlan()
        task = plan.add_task("Delete old files", action_type="delete")
        task.rollback_plan = None  # No rollback!

        judgement = crit_judge.evaluate_plan(plan, "Clean up")

        assert judgement.verdict in [Verdict.REJECTED, Verdict.NEEDS_REVISION]
        assert len(judgement.concerns) > 0
        assert any("rollback" in c.lower() for c in judgement.concerns)
        assert any(q.severity == "critical" for q in judgement.questions)

    def test_plan_metadata_included(self, crit_judge):
        """Judgement should include plan metadata."""
        plan = ExecutionPlan()
        plan.add_task("Task 1", action_type="edit")
        plan.add_task("Task 2", action_type="delete")
        plan.tasks[1].risk_level = RiskLevel.HIGH
        plan.tasks[1].rollback_plan = "Restore from backup"

        judgement = crit_judge.evaluate_plan(plan, "Test metadata")

        assert judgement.metadata["total_tasks"] == 2
        assert "high_risk_tasks" in judgement.metadata
        assert "destructive_tasks" in judgement.metadata


class TestClaimVerification:
    """Test claim verification functionality."""

    def test_completed_claim_without_evidence(self, crit_judge):
        """Completion claim without evidence should be rejected."""
        claim = "Task completed successfully"
        evidence = {}

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.verdict in [Verdict.REJECTED, Verdict.NEEDS_REVISION]
        assert len(judgement.concerns) > 0
        assert any("deliverables" in c.lower() or "verified" in c.lower() for c in judgement.concerns)

    def test_completed_claim_with_evidence(self, crit_judge):
        """Completion claim with evidence should be approved."""
        claim = "Task completed successfully"
        evidence = {
            "deliverables_verified": True,
            "tests_passed": True
        }

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.verdict == Verdict.APPROVED
        assert judgement.judgement_type == JudgementType.CLAIM_VERIFICATION

    def test_tests_pass_claim_with_failure(self, crit_judge):
        """'Tests pass' claim with non-zero exit code should be rejected."""
        claim = "All tests pass"
        evidence = {
            "exit_code": 1  # Non-zero!
        }

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("exit code" in c.lower() for c in judgement.concerns)
        assert any(q.severity == "critical" for q in judgement.questions)

    def test_tests_pass_claim_without_exit_code(self, crit_judge):
        """'Tests pass' claim without exit code should raise concerns."""
        claim = "All tests pass"
        evidence = {}

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.verdict in [Verdict.REJECTED, Verdict.NEEDS_REVISION]
        assert len(judgement.concerns) > 0

    def test_no_errors_claim_with_stderr(self, crit_judge):
        """'No errors' claim with stderr should raise concerns."""
        claim = "No errors detected"
        evidence = {
            "stderr": "Warning: Deprecated function used"
        }

        judgement = crit_judge.verify_claim(claim, evidence)

        assert len(judgement.concerns) > 0
        assert any("stderr" in c.lower() for c in judgement.concerns)

    def test_no_errors_claim_with_syntax_errors(self, crit_judge):
        """'No errors' claim with syntax errors should be rejected."""
        claim = "No errors in code"
        evidence = {
            "syntax_errors": ["Missing closing parenthesis at line 42"]
        }

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("syntax" in c.lower() for c in judgement.concerns)

    def test_claim_metadata_included(self, crit_judge):
        """Judgement should include claim metadata."""
        claim = "Test claim"
        evidence = {"key1": "value1", "key2": "value2"}

        judgement = crit_judge.verify_claim(claim, evidence)

        assert judgement.metadata["claim"] == claim
        assert "evidence_keys" in judgement.metadata
        assert set(judgement.metadata["evidence_keys"]) == {"key1", "key2"}


class TestMergeGate:
    """Test merge gate functionality."""

    def test_merge_without_dod(self, crit_judge):
        """Merge without DoD should raise concerns."""
        task = Task(description="Test task", action_type="edit")
        task.status = TaskStatus.COMPLETED

        judgement = crit_judge.evaluate_merge(
            task=task,
            dod=None,
            verification_passed=True,
            transaction_committed=True
        )

        assert len(judgement.concerns) > 0
        assert any("dod" in c.lower() or "definition" in c.lower() for c in judgement.concerns)

    def test_merge_with_unverified_dod(self, crit_judge):
        """Merge with DoD but not verified should be rejected."""
        task = Task(description="Test task", action_type="edit")
        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test",
            deliverables=[],
            acceptance_criteria=[]
        )

        judgement = crit_judge.evaluate_merge(
            task=task,
            dod=dod,
            verification_passed=True,
            transaction_committed=True,
            context={"dod_verified": False}
        )

        assert judgement.verdict in [Verdict.REJECTED, Verdict.NEEDS_REVISION]
        assert len(judgement.concerns) > 0
        assert any(q.severity == "critical" for q in judgement.questions)

    def test_merge_without_verification(self, crit_judge):
        """Merge without verification should be rejected."""
        task = Task(description="Test task", action_type="edit")

        judgement = crit_judge.evaluate_merge(
            task=task,
            verification_passed=False,  # Failed!
            transaction_committed=True
        )

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("verification" in c.lower() for c in judgement.concerns)

    def test_merge_without_transaction_commit(self, crit_judge):
        """Merge without transaction commit should be rejected."""
        task = Task(description="Test task", action_type="edit")

        judgement = crit_judge.evaluate_merge(
            task=task,
            verification_passed=True,
            transaction_committed=False  # Not committed!
        )

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("transaction" in c.lower() for c in judgement.concerns)

    def test_merge_with_task_error(self, crit_judge):
        """Merge with task error should be rejected."""
        task = Task(description="Test task", action_type="edit")
        task.error = "Syntax error at line 42"

        judgement = crit_judge.evaluate_merge(
            task=task,
            verification_passed=True,
            transaction_committed=True
        )

        assert judgement.verdict == Verdict.REJECTED
        assert len(judgement.concerns) > 0
        assert any("error" in c.lower() for c in judgement.concerns)

    def test_merge_with_unexpected_files(self, crit_judge):
        """Merge with unexpected file modifications should raise concerns."""
        task = Task(description="Update utils.py", action_type="edit")

        judgement = crit_judge.evaluate_merge(
            task=task,
            verification_passed=True,
            transaction_committed=True,
            context={
                "expected_files": ["utils.py"],
                "files_modified": ["utils.py", "config.yaml", "secrets.env"]
            }
        )

        assert len(judgement.concerns) > 0
        assert len(judgement.recommendations) > 0
        assert any("unexpected" in c.lower() for c in judgement.concerns)

    def test_merge_all_gates_pass(self, crit_judge):
        """Merge with all gates passing should be approved."""
        task = Task(description="Test task", action_type="edit")
        task.task_id = "T-001"
        task.status = TaskStatus.COMPLETED

        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test",
            deliverables=[],
            acceptance_criteria=[]
        )

        judgement = crit_judge.evaluate_merge(
            task=task,
            dod=dod,
            verification_passed=True,
            transaction_committed=True,
            context={
                "dod_verified": True,
                "expected_files": ["utils.py"],
                "files_modified": ["utils.py"]
            }
        )

        assert judgement.verdict == Verdict.APPROVED
        assert judgement.confidence > 0.8

    def test_merge_metadata_included(self, crit_judge):
        """Judgement should include merge metadata."""
        task = Task(description="Test task", action_type="edit")
        task.task_id = "T-001"

        judgement = crit_judge.evaluate_merge(
            task=task,
            verification_passed=True,
            transaction_committed=False
        )

        assert judgement.metadata["task_id"] == "T-001"
        assert "dod_defined" in judgement.metadata
        assert "verification_passed" in judgement.metadata
        assert "transaction_committed" in judgement.metadata


class TestJudgementSummary:
    """Test judgement summary generation."""

    def test_summary_includes_verdict(self, crit_judge):
        """Summary should include verdict."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")

        judgement = crit_judge.evaluate_plan(plan, "Test")
        summary = judgement.summary()

        assert "CRIT Judgement:" in summary
        assert judgement.verdict.value.upper() in summary

    def test_summary_includes_questions(self, crit_judge):
        """Summary should include questions."""
        plan = ExecutionPlan()
        task = plan.add_task("Delete files", action_type="delete")
        task.rollback_plan = None

        judgement = crit_judge.evaluate_plan(plan, "Clean up")
        summary = judgement.summary()

        assert "Critical Questions" in summary or "questions" in summary.lower()
        assert len(judgement.questions) > 0

    def test_summary_includes_concerns(self, crit_judge):
        """Summary should include concerns."""
        claim = "All tests pass"
        evidence = {"exit_code": 1}

        judgement = crit_judge.verify_claim(claim, evidence)
        summary = judgement.summary()

        assert "Concerns" in summary
        assert len(judgement.concerns) > 0

    def test_summary_includes_recommendations(self, crit_judge):
        """Summary should include recommendations."""
        plan = ExecutionPlan()
        task = plan.add_task("Delete files", action_type="delete")
        task.rollback_plan = None

        judgement = crit_judge.evaluate_plan(plan, "Clean up")
        summary = judgement.summary()

        if judgement.recommendations:
            assert "Recommendations" in summary


class TestDependencyChecks:
    """Test dependency checking logic."""

    def test_no_dependencies_ok(self, crit_judge):
        """Plan with no dependencies should have no dependency issues."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")
        plan.add_task("Task 2")

        issues = crit_judge._check_dependencies(plan)

        assert len(issues) == 0

    def test_valid_dependencies_ok(self, crit_judge):
        """Plan with valid dependencies should have no issues."""
        plan = ExecutionPlan()
        plan.add_task("Task 1", dependencies=[])
        plan.add_task("Task 2", dependencies=[0])
        plan.add_task("Task 3", dependencies=[0, 1])

        issues = crit_judge._check_dependencies(plan)

        assert len(issues) == 0

    def test_self_dependency_detected(self, crit_judge):
        """Self-dependency should be detected."""
        plan = ExecutionPlan()
        task = plan.add_task("Task 1")
        task.dependencies = [0]  # Depends on itself!

        issues = crit_judge._check_dependencies(plan)

        assert len(issues) > 0
        assert any("itself" in issue.lower() for issue in issues)


class TestCriticalQuestions:
    """Test critical question generation."""

    def test_question_has_category(self):
        """CriticalQuestion should have category."""
        q = CriticalQuestion(
            question="Is this safe?",
            category="safety",
            severity="high"
        )

        assert q.category == "safety"
        assert q.severity == "high"

    def test_question_default_severity(self):
        """CriticalQuestion should have default severity."""
        q = CriticalQuestion(
            question="Test?",
            category="test"
        )

        assert q.severity == "medium"


class TestLLMIntegration:
    """Test LLM integration (mocked)."""

    def test_llm_disabled_no_calls(self, crit_judge):
        """With LLM disabled, no LLM calls should be made."""
        plan = ExecutionPlan()
        plan.add_task("Task 1")

        with patch('rev.agents.crit_judge.ollama_chat') as mock_chat:
            judgement = crit_judge.evaluate_plan(plan, "Test")

            # Should not call LLM
            mock_chat.assert_not_called()

    @patch('rev.agents.crit_judge.ollama_chat')
    def test_llm_enabled_calls_llm(self, mock_chat, crit_judge_with_llm):
        """With LLM enabled, should call LLM."""
        mock_chat.return_value = {
            "message": {
                "content": "QUESTIONS:\n- [logic] Is this the right approach? (severity: medium)\n\nCONCERNS:\n- None"
            }
        }

        plan = ExecutionPlan()
        plan.add_task("Task 1")

        judgement = crit_judge_with_llm.evaluate_plan(plan, "Test")

        # Should call LLM
        assert mock_chat.called

    @patch('rev.agents.crit_judge.ollama_chat')
    def test_llm_response_parsed(self, mock_chat, crit_judge_with_llm):
        """LLM response should be parsed correctly."""
        mock_chat.return_value = {
            "message": {
                "content": """QUESTIONS:
- [logic] Is the order correct? (severity: high)
- [risks] What if it fails? (severity: critical)

CONCERNS:
- Missing error handling

RECOMMENDATIONS:
- Add try/catch blocks"""
            }
        }

        plan = ExecutionPlan()
        plan.add_task("Task 1")

        judgement = crit_judge_with_llm.evaluate_plan(plan, "Test")

        # Check parsed questions
        assert len(judgement.questions) >= 2
        logic_questions = [q for q in judgement.questions if q.category == "logic"]
        assert len(logic_questions) > 0

        # Check parsed concerns
        assert len(judgement.concerns) >= 1

        # Check parsed recommendations
        assert len(judgement.recommendations) >= 1

    @patch('rev.agents.crit_judge.ollama_chat')
    def test_llm_failure_graceful(self, mock_chat, crit_judge_with_llm):
        """LLM failure should not crash, fall back gracefully."""
        mock_chat.side_effect = Exception("LLM error")

        plan = ExecutionPlan()
        plan.add_task("Task 1")

        # Should not raise exception
        judgement = crit_judge_with_llm.evaluate_plan(plan, "Test")

        assert judgement is not None
        assert isinstance(judgement, CRITJudgement)


class TestConfidenceLevels:
    """Test confidence level calculation."""

    def test_approved_has_high_confidence(self, crit_judge):
        """Approved verdict should have high confidence."""
        plan = ExecutionPlan()
        plan.add_task("Simple task", action_type="edit")

        judgement = crit_judge.evaluate_plan(plan, "Test")

        if judgement.verdict == Verdict.APPROVED:
            assert judgement.confidence >= 0.7

    def test_rejected_has_high_confidence(self, crit_judge):
        """Rejected verdict should have high confidence."""
        plan = ExecutionPlan()  # Empty plan

        judgement = crit_judge.evaluate_plan(plan, "Test")

        if judgement.verdict == Verdict.REJECTED:
            assert judgement.confidence >= 0.8

    def test_needs_revision_has_medium_confidence(self, crit_judge):
        """Needs revision verdict should have medium confidence."""
        plan = ExecutionPlan()
        task = plan.add_task("Delete files", action_type="delete")
        task.rollback_plan = None

        judgement = crit_judge.evaluate_plan(plan, "Test")

        if judgement.verdict == Verdict.NEEDS_REVISION:
            assert 0.5 <= judgement.confidence <= 0.9
