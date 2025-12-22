#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Judge Agent - Evaluates debates and makes final decisions.

The Judge evaluates proposals and critiques to make final decisions:
- ACCEPT: Proposal is well-supported with strong evidence
- REQUEST_EVIDENCE: Proposal has merit but needs more evidence
- REJECT: Proposal is unfalsifiable or fundamentally flawed
"""

from typing import Dict, Any


class JudgeAgent:
    """Agent that evaluates debates and makes final decisions."""

    def decide(self, proposal: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """Make a decision based on proposal and critique.

        Args:
            proposal: The proposal from Proposer
            critique: The critique from Skeptic

        Returns:
            Dictionary with:
                - decision: "ACCEPT", "REQUEST_EVIDENCE", or "REJECT"
                - rationale: Explanation of decision
                - confidence: Float between 0 and 1
                - required_evidence: (if REQUEST_EVIDENCE) List of required evidence
        """
        gaps = critique.get("gaps", [])
        evidence_requests = critique.get("evidence_requests", [])
        skepticism_level = critique.get("skepticism_level", 0.5)
        counter_examples = critique.get("counter_examples", [])

        proposal_confidence = proposal.get("confidence", 0.5)
        evidence_count = len(proposal.get("evidence", []))

        # Check for unfalsifiable claims
        if self._is_unfalsifiable(proposal, critique):
            return {
                "decision": "REJECT",
                "rationale": "Proposal is unfalsifiable and cannot be tested or verified",
                "confidence": 0.9
            }

        # ACCEPT: Strong evidence, no gaps, low skepticism
        if not gaps and not evidence_requests and skepticism_level < 0.3:
            return {
                "decision": "ACCEPT",
                "rationale": "Proposal is well-supported with strong evidence and no identified gaps",
                "confidence": max(0.7, proposal_confidence)
            }

        # REQUEST_EVIDENCE: Gaps exist but proposal is fixable
        if gaps or evidence_requests:
            return {
                "decision": "REQUEST_EVIDENCE",
                "rationale": f"Proposal has {len(gaps)} evidence gaps that need addressing",
                "confidence": 0.6,
                "required_evidence": evidence_requests
            }

        # Default: Accept with moderate confidence
        return {
            "decision": "ACCEPT",
            "rationale": "Proposal is acceptable",
            "confidence": proposal_confidence
        }

    def _is_unfalsifiable(self, proposal: Dict[str, Any], critique: Dict[str, Any]) -> bool:
        """Check if proposal is unfalsifiable (can't be tested or verified).

        Args:
            proposal: The proposal
            critique: The critique

        Returns:
            True if proposal is unfalsifiable
        """
        # Check for vague solutions
        solution = proposal.get("solution", "").lower()
        if any(phrase in solution for phrase in ["magic", "make it work better", "just fix it"]):
            return True

        # Check for evidence based on intuition/feeling
        evidence = proposal.get("evidence", [])
        for item in evidence:
            source = str(item.get("source", "")).lower()
            if any(word in source for word in ["intuition", "gut feeling", "feels right", "magic"]):
                return True

        # Check if gaps mention unfalsifiability
        gaps = critique.get("gaps", [])
        for gap in gaps:
            if "unfalsifiable" in gap.lower() or "vague" in gap.lower():
                return True

        # High skepticism with many gaps suggests unfalsifiable
        skepticism = critique.get("skepticism_level", 0.5)
        if skepticism > 0.85 and len(gaps) > 2:
            return True

        return False
