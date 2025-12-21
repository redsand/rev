import pytest
from rev.execution.anchoring_scorer import AnchoringScorer, AnchoringDecision

class TestAnchoringScorer:
    
    @pytest.fixture
    def scorer(self):
        return AnchoringScorer(
            density_weight=1.0,
            risk_penalty=0.5, # Moderate penalty for tests
            stop_threshold=1.0,
            debate_risk_threshold=3
        )

    def test_unbaited_casting_triggers_research(self, scorer):
        """
        Scenario: The agent is making many claims but has found zero code citations.
        This is 'unbaited casting' in UCCT terms.
        Expected: Low score -> RE_SEARCH.
        """
        claims = ["User auth handles JWT", "DB uses Postgres", "API is REST"]
        citations = [] # No source code found
        test_outputs = [] # No tests run
        
        metrics = scorer.compute_anchoring_score(
            claims=claims,
            repo_citations=citations,
            test_outputs=test_outputs,
            unresolved_symbols=[],
            missing_files=[],
            tools_used_count=5 # We looked, but found nothing
        )

        assert metrics.evidence_density == 0.0
        assert metrics.raw_score == 0.0
        assert metrics.decision == AnchoringDecision.RE_SEARCH
        print(f"\nUnbaited Casting Score: {metrics.raw_score} -> {metrics.decision}")

    def test_strong_anchoring_triggers_stop(self, scorer):
        """
        Scenario: The agent has high evidence density (code + tests) and low risk.
        The anchors have 'shifted the posterior' sufficiently.
        Expected: High score -> STOP.
        """
        claims = ["Login function validates password"]
        citations = ["src/auth/login.py", "src/utils/hash.py"] # 2 citations
        test_outputs = ["tests/test_login.py passed"] # 1 test
        
        metrics = scorer.compute_anchoring_score(
            claims=claims,
            repo_citations=citations,
            test_outputs=test_outputs,
            unresolved_symbols=[],
            missing_files=[],
            tools_used_count=3
        )

        # Density = 3/1 = 3.0
        # Risk = 0
        assert metrics.evidence_density == 3.0
        assert metrics.raw_score > scorer.stop_threshold
        assert metrics.decision == AnchoringDecision.STOP
        print(f"\nStrong Anchoring Score: {metrics.raw_score:.2f} -> {metrics.decision}")

    def test_high_mismatch_risk_triggers_debate(self, scorer):
        """
        Scenario: Agent has evidence, but the code references symbols 
        or files that don't exist (High Mismatch Risk).
        Expected: Score penalized, Risk Threshold hit -> DEBATE.
        """
        claims = ["Data is imported from CSV"]
        citations = ["src/data/importer.py"]
        test_outputs = []
        
        # High risk items
        unresolved = ["pandas_config", "CSVLoader"]
        missing_files = ["src/config/settings.csv"]
        
        metrics = scorer.compute_anchoring_score(
            claims=claims,
            repo_citations=citations,
            test_outputs=test_outputs,
            unresolved_symbols=unresolved,
            missing_files=missing_files,
            tools_used_count=2
        )

        assert metrics.mismatch_risk == 3 # 2 symbols + 1 file
        # Even if score was high, risk threshold forces debate
        assert metrics.decision == AnchoringDecision.DEBATE
        print(f"\nHigh Risk Score: {metrics.raw_score:.2f} (Risk: {metrics.mismatch_risk}) -> {metrics.decision}")

    def test_anchor_budget_increases_confidence(self, scorer):
        """
        Scenario: Compare two states with identical evidence density.
        State B has used more tools (higher budget/k), implying deeper search.
        Expected: State B has a higher score (logarithmic boost).
        """
        common_args = {
            "claims": ["Claim A"],
            "repo_citations": ["file.py"],
            "test_outputs": [],
            "unresolved_symbols": [],
            "missing_files": []
        }

        # Shallow search
        metrics_shallow = scorer.compute_anchoring_score(
            **common_args, tools_used_count=1
        )

        # Deep search
        metrics_deep = scorer.compute_anchoring_score(
            **common_args, tools_used_count=10
        )

        assert metrics_deep.raw_score > metrics_shallow.raw_score
        assert metrics_deep.anchor_budget > metrics_shallow.anchor_budget
        print(f"\nBudget Impact: {metrics_shallow.raw_score:.2f} vs {metrics_deep.raw_score:.2f}")

    def test_partial_evidence_logic(self, scorer):
        """
        Scenario: Some evidence found, but not enough to cross threshold.
        """
        metrics = scorer.compute_anchoring_score(
            claims=["Claim A", "Claim B", "Claim C"],
            repo_citations=["file_a.py"], # Density 0.33
            test_outputs=[],
            unresolved_symbols=[],
            missing_files=[],
            tools_used_count=5
        )
        
        # Density is ~0.33. Score will be likely below 1.0 threshold
        assert metrics.decision == AnchoringDecision.RE_SEARCH
