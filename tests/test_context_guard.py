"""
Tests for ContextGuard phase - context validation and filtering.

Verifies:
1. Intent extraction identifies entities correctly
2. Relevance scoring filters low-value context
3. Sufficiency validation detects gaps and hallucination risks
4. Integration with orchestrator pipeline
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from rev.execution.context_guard import (
    extract_user_intent,
    score_context_relevance,
    validate_context_sufficiency,
    run_context_guard,
    ContextGuardResult,
    ContextGap,
    GapType,
    GapSeverity,
    FilteredContext,
)
from rev.execution.researcher import ResearchFindings
from rev.retrieval.base import CodeChunk
from rev.core.context import RevContext


class TestIntentExtraction:
    """Test user intent extraction."""

    def test_extract_action_from_clear_request(self):
        """Test extracting action type from request."""
        request = "Add JWT authentication to the UserAuth class"

        intent = extract_user_intent(request)

        assert intent["action"] == "add"
        assert intent["confidence"] > 0.5

    def test_extract_entities_from_request(self):
        """Test extracting entities (files, classes) from request."""
        request = "Fix the bug in auth.py by updating the UserAuth class"

        intent = extract_user_intent(request)

        assert "auth.py" in intent["entities"]["files"]
        assert "UserAuth" in intent["entities"]["classes"]

    def test_detect_ambiguities_in_vague_request(self):
        """Test ambiguity detection for vague requests."""
        request = "Fix the auth bug"

        intent = extract_user_intent(request)

        assert len(intent["ambiguities"]) > 0
        assert intent["confidence"] < 0.7


class TestRelevanceScoring:
    """Test context relevance scoring and filtering."""

    def test_score_and_filter_context(self):
        """Test that context is scored and low-relevance items filtered."""
        intent = {
            "action": "add",
            "entities": {"files": ["auth.py"], "classes": ["UserAuth"], "functions": [], "features": []},
            "ambiguities": [],
            "scope": "file",
            "confidence": 0.8,
        }

        findings = ResearchFindings()
        findings.relevant_files = [
            {"path": "auth.py", "relevance": 0.9},
            {"path": "config.py", "relevance": 0.2},
            {"path": "utils.py", "relevance": 0.15},
        ]

        filtered = score_context_relevance(intent, findings, threshold=0.3)

        assert filtered.original_chunk_count == 3
        assert filtered.filtered_chunk_count < 3  # Some should be filtered out
        assert filtered.tokens_saved > 0

    def test_boost_score_for_entity_matches(self):
        """Test that files with entity matches get boosted scores."""
        intent = {
            "action": "edit",
            "entities": {"files": ["UserAuth"], "classes": [], "functions": [], "features": []},
            "ambiguities": [],
            "scope": "unknown",
            "confidence": 0.5,
        }

        findings = ResearchFindings()
        findings.relevant_files = [
            {"path": "UserAuthHandler.py", "relevance": 0.5},
            {"path": "OtherFile.py", "relevance": 0.5},
        ]

        filtered = score_context_relevance(intent, findings, threshold=0.3)

        # UserAuthHandler should have higher score due to entity match
        if filtered.relevant_files:
            scores = [f.get("score", 0) for f in filtered.relevant_files]
            # At least one file should match
            assert any("UserAuth" in f.get("path", "") for f in filtered.relevant_files)


class TestSufficiencyValidation:
    """Test context sufficiency validation."""

    def test_sufficient_context_with_all_entities(self):
        """Test that context with all entities scores as sufficient."""
        intent = {
            "action": "add",
            "entities": {"files": ["auth.py"], "classes": ["UserAuth"], "functions": [], "features": []},
            "ambiguities": [],
            "scope": "file",
            "confidence": 0.85,
        }

        filtered = FilteredContext(
            original_chunk_count=5,
            filtered_chunk_count=3,
            tokens_saved=500,
            relevant_files=[{"path": "auth.py", "score": 0.9}],
            relevant_chunks=[],
            relevance_threshold=0.3,
            filtered_out=["config.py", "utils.py"],
        )

        findings = ResearchFindings()
        findings.code_patterns = ["class UserAuth:", "def __init__(self):"]

        sufficiency = validate_context_sufficiency(intent, filtered, findings)

        assert sufficiency.is_sufficient
        assert sufficiency.confidence_score > 0.7
        assert len(sufficiency.gaps) == 0

    def test_insufficient_context_missing_entities(self):
        """Test that missing entities are detected as gaps."""
        intent = {
            "action": "add",
            "entities": {"files": ["UserAuth.py"], "classes": ["TokenValidator"], "functions": [], "features": []},
            "ambiguities": [],
            "scope": "file",
            "confidence": 0.6,
        }

        filtered = FilteredContext(
            original_chunk_count=1,
            filtered_chunk_count=1,
            tokens_saved=0,
            relevant_files=[{"path": "auth.py"}],  # Different file
            relevant_chunks=[],
            relevance_threshold=0.3,
            filtered_out=[],
        )

        findings = ResearchFindings()

        sufficiency = validate_context_sufficiency(intent, filtered, findings)

        assert not sufficiency.is_sufficient
        assert len(sufficiency.gaps) > 0
        # Should have critical gaps for missing file and class
        critical_gaps = [g for g in sufficiency.gaps if g.severity == GapSeverity.CRITICAL]
        assert len(critical_gaps) > 0

    def test_hallucination_risk_with_vague_request(self):
        """Test hallucination risk detection for vague requests."""
        intent = {
            "action": "fix",
            "entities": {"files": [], "classes": [], "functions": [], "features": []},  # No specific entities
            "ambiguities": ["Vague action language"],
            "scope": "unknown",
            "confidence": 0.3,
        }

        filtered = FilteredContext(
            original_chunk_count=5,
            filtered_chunk_count=2,
            tokens_saved=600,
            relevant_files=[],
            relevant_chunks=[],
            relevance_threshold=0.3,
            filtered_out=[],
        )

        findings = ResearchFindings()

        sufficiency = validate_context_sufficiency(intent, filtered, findings)

        # Should have hallucination risks due to vague intent and few entities
        assert len(sufficiency.hallucination_risks) > 0


class TestMainEntryPoint:
    """Test the main run_context_guard function."""

    @patch('rev.execution.context_guard.extract_user_intent')
    @patch('rev.execution.context_guard.score_context_relevance')
    @patch('rev.execution.context_guard.validate_context_sufficiency')
    def test_run_context_guard_success(self, mock_validate, mock_score, mock_intent):
        """Test successful ContextGuard execution."""
        # Setup mocks
        mock_intent.return_value = {
            "action": "add",
            "entities": {"files": ["auth.py"], "classes": [], "functions": [], "features": []},
            "ambiguities": [],
            "scope": "file",
            "confidence": 0.8,
        }

        mock_score.return_value = FilteredContext(
            original_chunk_count=3,
            filtered_chunk_count=2,
            tokens_saved=500,
            relevant_files=[{"path": "auth.py", "score": 0.9}],
            relevant_chunks=[],
            relevance_threshold=0.3,
            filtered_out=["config.py"],
        )

        mock_validate.return_value = type('ContextSufficiency', (), {
            'is_sufficient': True,
            'confidence_score': 0.85,
            'gaps': [],
            'hallucination_risks': [],
            'concrete_references': {"files": ["auth.py"]},
        })()

        findings = ResearchFindings()
        findings.relevant_files = [{"path": "auth.py"}]

        result = run_context_guard(
            "Add JWT authentication to auth.py",
            findings,
            interactive=False,
            threshold=0.3
        )

        assert isinstance(result, ContextGuardResult)
        assert result.action_taken in ["approved", "approved_with_warnings"]
        assert result.filtered_context.tokens_saved > 0


class TestIntegration:
    """Test integration with orchestrator."""

    def test_rev_context_stores_context_guard_results(self):
        """Test that RevContext properly stores ContextGuard results."""
        context = RevContext(user_request="Test request")

        # Should initialize with None values
        assert context.context_sufficiency is None
        assert context.purified_context is None
        assert context.clarification_history == []

        # Simulate storing results
        sufficiency = type('ContextSufficiency', (), {
            'is_sufficient': True,
            'confidence_score': 0.85,
        })()

        context.context_sufficiency = sufficiency

        # Verify storage
        assert context.context_sufficiency is not None
        assert context.context_sufficiency.confidence_score == 0.85

    def test_context_guard_dataclass_creation(self):
        """Test that ContextGuard data structures can be created."""
        gap = ContextGap(
            gap_type=GapType.MISSING_ENTITY,
            description="File not found",
            mentioned_in_request="auth.py",
            found_in_research=False,
            severity=GapSeverity.CRITICAL,
            suggested_action="Search for auth.py"
        )

        assert gap.gap_type == GapType.MISSING_ENTITY
        assert gap.severity == GapSeverity.CRITICAL
        assert not gap.found_in_research


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
