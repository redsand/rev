import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional

class AnchoringDecision(Enum):
    STOP = "STOP"           # Strongly anchored, posterior shifted sufficiently
    RE_SEARCH = "RE_SEARCH" # Unbaited casting, low evidence density
    DEBATE = "DEBATE"       # High mismatch risk, conflicting anchors

@dataclass
class AnchoringMetrics:
    """Metrics representing the pragmatic proxies for UCCT anchoring strength."""
    evidence_density: float
    mismatch_risk: int
    anchor_budget: int
    raw_score: float
    decision: AnchoringDecision
    details: Dict[str, Any] = field(default_factory=dict)

class AnchoringScorer:
    """
    Instrumentation to calculate UCCT-style anchoring scores to drive
    coordination decisions (Stop vs Search vs Debate).
    """

    def __init__(
        self,
        density_weight: float = 1.0,
        risk_penalty: float = 2.0,
        budget_log_base: float = 10.0,
        stop_threshold: float = 0.8,
        debate_risk_threshold: int = 3
    ):
        """
        Args:
            density_weight: Weighting for evidence density (rho).
            risk_penalty: Penalty multiplier for unresolved symbols (d_r).
            budget_log_base: Log base for dampening tool usage impact.
            stop_threshold: Score above which we consider the posterior shifted (Stop).
            debate_risk_threshold: Mismatch count that triggers mandatory debate.
        """
        self.density_weight = density_weight
        self.risk_penalty = risk_penalty
        self.budget_log_base = budget_log_base
        self.stop_threshold = stop_threshold
        self.debate_risk_threshold = debate_risk_threshold

    def compute_anchoring_score(
        self,
        claims: List[str],
        repo_citations: List[str],
        test_outputs: List[str],
        unresolved_symbols: List[str],
        missing_files: List[str],
        tools_used_count: int
    ) -> AnchoringMetrics:
        """
        Calculate the Anchoring Score based on pragmatic proxies.

        Proxies:
        1. Evidence Density (rho): (Repo Citations + Test Outputs) / Claims
        2. Mismatch Risk (d_r): Count of unresolved symbols + missing files
        3. Anchor Budget (k): Number of retrieved artifacts/tools used

        Equation Proxy:
        Score = (Density * log(1 + Budget)) / (1 + (Risk * Penalty))
        """
        
        # 1. Calculate Evidence Density
        num_claims = max(1, len(claims)) # Avoid division by zero
        num_evidence = len(repo_citations) + len(test_outputs)
        evidence_density = num_evidence / num_claims

        # 2. Calculate Mismatch Risk
        mismatch_risk = len(unresolved_symbols) + len(missing_files)

        # 3. Calculate Anchor Budget factor (Logarithmic dampening)
        # Using tool usage/artifacts as the budget 'k'
        budget_factor = math.log(1 + tools_used_count, self.budget_log_base)

        # 4. Compute Final Score (UCCT-style proxy)
        # Higher density & budget increases score. High risk decreases it.
        numerator = self.density_weight * evidence_density * (1 + budget_factor)
        denominator = 1 + (mismatch_risk * self.risk_penalty)
        
        raw_score = numerator / denominator

        # 5. Determine Decision
        decision = self._derive_decision(raw_score, mismatch_risk, evidence_density)

        return AnchoringMetrics(
            evidence_density=evidence_density,
            mismatch_risk=mismatch_risk,
            anchor_budget=tools_used_count,
            raw_score=raw_score,
            decision=decision,
            details={
                "numerator": numerator,
                "denominator": denominator,
                "claims_count": num_claims,
                "evidence_count": num_evidence
            }
        )

    def _derive_decision(
        self, score: float, risk: int, density: float
    ) -> AnchoringDecision:
        """
        Decide next step based on score topology.
        
        UCCT Logic:
        - High Risk -> Posterior is unstable -> Debate/Refine.
        - Low Score (Low Density) -> Unbaited casting -> Re-search.
        - High Score -> Anchors shift posterior -> Stop.
        """
        if risk >= self.debate_risk_threshold:
            return AnchoringDecision.DEBATE
        
        if score >= self.stop_threshold:
            return AnchoringDecision.STOP
            
        # If density is extremely low, specifically re-search
        if density < 0.2:
            return AnchoringDecision.RE_SEARCH
            
        # Default fallback for intermediate scores
        return AnchoringDecision.RE_SEARCH
