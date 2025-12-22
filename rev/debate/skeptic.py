#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skeptic Agent - Challenges proposals and requests evidence.

The Skeptic evaluates proposals and:
- Identifies gaps in evidence
- Challenges high confidence when evidence is weak
- Requests specific, actionable evidence
- Proposes counter-examples and edge cases
- Adjusts skepticism level based on proposal quality
"""

from typing import Dict, List, Any, Optional, Callable
from rev.llm import ollama_chat
from rev import config
import json


class SkepticAgent:
    """Agent that critiques proposals and requests evidence."""

    def __init__(self, model: Optional[str] = None, llm_client: Optional[Callable] = None):
        """Initialize the Skeptic agent.

        Args:
            model: Optional LLM model to use
            llm_client: Optional LLM client function (for testing)
        """
        self.model = model or getattr(config, 'DEFAULT_MODEL', config._DEFAULT_MODEL)
        self.llm_client = llm_client or ollama_chat

    def critique(self, proposal: Dict[str, Any], skepticism_level: float = 0.5) -> Dict[str, Any]:
        """Critique a proposal and request evidence.

        Args:
            proposal: The proposal to critique (from Proposer)
            skepticism_level: Base skepticism level (0.0-1.0), can be modulated

        Returns:
            Dictionary with:
                - gaps: List of identified evidence gaps
                - evidence_requests: List of specific evidence requests
                - counter_examples: List of potential counter-examples
                - skepticism_level: Calculated skepticism level for this proposal
        """
        # Calculate skepticism based on proposal quality
        calculated_skepticism = self._calculate_skepticism(proposal, skepticism_level)

        # Build critique prompt
        prompt = self._build_critique_prompt(proposal, calculated_skepticism)

        # Get LLM response
        response = self.llm_client(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._get_system_prompt(calculated_skepticism)
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        # Extract content from response
        if isinstance(response, dict) and "message" in response:
            content = response["message"].get("content", "")
        else:
            # For mock functions in tests that return strings directly
            content = response

        # Parse structured output
        critique = self._parse_critique(content)
        critique["skepticism_level"] = calculated_skepticism

        return critique

    def _calculate_skepticism(self, proposal: Dict[str, Any], base_level: float) -> float:
        """Calculate appropriate skepticism level for this proposal.

        Higher skepticism when:
        - High confidence but weak evidence
        - Many assumptions with little support
        - Vague or unfalsifiable claims

        Args:
            proposal: The proposal to evaluate
            base_level: Base skepticism level

        Returns:
            Calculated skepticism level (0.0-1.0)
        """
        confidence = proposal.get("confidence", 0.5)
        evidence = proposal.get("evidence", [])
        assumptions = proposal.get("assumptions", [])

        # Start with base level
        skepticism = base_level

        # High confidence with weak evidence → increase skepticism
        if confidence > 0.8 and len(evidence) < 2:
            skepticism += 0.3

        # Many assumptions → increase skepticism
        if len(assumptions) > 3:
            skepticism += 0.2

        # Empty or vague evidence → increase skepticism
        if not evidence or any("feeling" in str(e).lower() or "seems" in str(e).lower() for e in evidence):
            skepticism += 0.2

        # Strong evidence → decrease skepticism
        if len(evidence) >= 3:
            skepticism -= 0.1

        # Clamp to valid range
        return max(0.0, min(1.0, skepticism))

    def _get_system_prompt(self, skepticism_level: float) -> str:
        """Get system prompt tailored to skepticism level."""
        if skepticism_level > 0.7:
            tone = "highly skeptical and demanding"
        elif skepticism_level > 0.4:
            tone = "moderately skeptical"
        else:
            tone = "constructively critical"

        return f"""You are a Skeptic agent in a debate system. Your role is to be {tone}.

Evaluate proposals and identify:
1. Gaps in evidence - what's missing?
2. Specific evidence requests - what would prove/disprove this?
3. Counter-examples and edge cases - what could go wrong?
4. Unfalsifiable claims - can this actually be tested?

Output your critique as JSON with this structure:
{{
  "gaps": ["gap 1", "gap 2"],
  "evidence_requests": [
    {{"type": "runtime_test", "description": "what to test", "rationale": "why this matters"}},
    {{"type": "file_read", "description": "what to read", "rationale": "what to look for"}}
  ],
  "counter_examples": ["edge case 1", "edge case 2"]
}}

Be specific and actionable. Don't just say "needs more evidence" - say exactly what evidence is needed and why."""

    def _build_critique_prompt(self, proposal: Dict[str, Any], skepticism_level: float) -> str:
        """Build the critique prompt."""
        return f"""Proposal to Evaluate:
Solution: {proposal.get('solution', 'N/A')}
Assumptions: {', '.join(proposal.get('assumptions', []))}
Evidence: {len(proposal.get('evidence', []))} items
Confidence: {proposal.get('confidence', 0.0)}

Skepticism Level: {skepticism_level:.2f}

Please critique this proposal. What evidence is missing? What could go wrong? What should be tested?
"""

    def _parse_critique(self, llm_response: str) -> Dict[str, Any]:
        """Parse LLM response into structured critique.

        Args:
            llm_response: Raw LLM response

        Returns:
            Structured critique dictionary
        """
        try:
            # Extract JSON
            response_text = llm_response.strip()

            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            elif "{" in response_text:
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                json_str = response_text[start:end]
            else:
                raise ValueError("No JSON found")

            critique = json.loads(json_str)

            # Ensure required fields
            if "gaps" not in critique:
                critique["gaps"] = []
            if "evidence_requests" not in critique:
                critique["evidence_requests"] = []
            if "counter_examples" not in critique:
                critique["counter_examples"] = []

            return critique

        except (json.JSONDecodeError, ValueError):
            # Fallback
            return {
                "gaps": ["Unable to parse structured critique"],
                "evidence_requests": [],
                "counter_examples": []
            }
