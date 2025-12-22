#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proposer Agent - Suggests solutions with explicit assumptions and evidence.

The Proposer generates structured proposals including:
- Solution description
- Explicit assumptions
- Evidence (citations to files, tool outputs, test results)
- Step-by-step reasoning
- Confidence score
"""

from typing import Dict, List, Any, Optional, Callable
from rev.llm import ollama_chat
from rev import config
import json


class ProposerAgent:
    """Agent that proposes solutions with explicit assumptions and evidence."""

    def __init__(self, model: Optional[str] = None, llm_client: Optional[Callable] = None):
        """Initialize the Proposer agent.

        Args:
            model: Optional LLM model to use (defaults to config.DEFAULT_MODEL)
            llm_client: Optional LLM client function (for testing)
        """
        self.model = model or getattr(config, 'DEFAULT_MODEL', config._DEFAULT_MODEL)
        self.llm_client = llm_client or ollama_chat

    def propose(self, context) -> Dict[str, Any]:
        """Generate a proposal for the given request.

        Args:
            context: Execution context with request, files_read, tool_events, etc.

        Returns:
            Dictionary with:
                - solution: Proposed solution description
                - assumptions: List of explicit assumptions made
                - evidence: List of evidence items (source + description)
                - reasoning: Step-by-step reasoning
                - confidence: Float between 0 and 1
        """
        # Build context from execution history
        context_summary = self._build_context_summary(context)

        # Create proposer prompt
        prompt = self._build_proposer_prompt(context.request, context_summary)

        # Get LLM response
        response = self.llm_client(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._get_system_prompt()
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
        proposal = self._parse_proposal(content)

        return proposal

    def _get_system_prompt(self) -> str:
        """Get the system prompt for the Proposer agent."""
        return """You are a Proposer agent in a debate system. Your role is to suggest solutions with:

1. Clear solution description
2. Explicit assumptions (what you're assuming to be true)
3. Evidence (cite specific files, tool outputs, test results)
4. Step-by-step reasoning
5. Honest confidence score (0.0 to 1.0)

Be specific and cite actual evidence. Acknowledge gaps in your knowledge.
Output your proposal as JSON with this structure:
{
  "solution": "clear description of proposed solution",
  "assumptions": ["assumption 1", "assumption 2"],
  "evidence": [
    {"source": "file.py:line", "description": "what this shows"},
    {"source": "test result", "description": "what was verified"}
  ],
  "reasoning": ["step 1", "step 2", "step 3"],
  "confidence": 0.85
}"""

    def _build_context_summary(self, context) -> str:
        """Build a summary of available context."""
        summary_parts = []

        # Files that have been read
        if hasattr(context, 'files_read') and context.files_read:
            try:
                files = list(context.files_read[:10]) if hasattr(context.files_read, '__getitem__') else [str(context.files_read)]
                summary_parts.append(f"Files read: {', '.join(files)}")
            except (TypeError, AttributeError):
                pass

        # Tool events (recent actions taken)
        if hasattr(context, 'tool_events') and context.tool_events:
            try:
                events = context.tool_events[-5:] if hasattr(context.tool_events, '__getitem__') else []
                recent_tools = [event.get('tool') if hasattr(event, 'get') else str(event) for event in events]
                summary_parts.append(f"Recent tools used: {', '.join(filter(None, recent_tools))}")
            except (TypeError, AttributeError):
                pass

        # Work history
        if hasattr(context, 'work_history') and context.work_history:
            try:
                count = len(context.work_history) if hasattr(context.work_history, '__len__') else 0
                summary_parts.append(f"Previous actions: {count} tasks completed")
            except (TypeError, AttributeError):
                pass

        return "\n".join(summary_parts) if summary_parts else "No prior context available"

    def _build_proposer_prompt(self, request: str, context_summary: str) -> str:
        """Build the prompt for the Proposer."""
        return f"""User Request: {request}

Available Context:
{context_summary}

Please propose a solution following the specified JSON format. Be specific about:
- What exactly should be done
- What assumptions you're making
- What evidence supports this approach
- Your reasoning steps
- Your confidence level (be honest - if you're uncertain, reflect that in a lower score)
"""

    def _parse_proposal(self, llm_response: str) -> Dict[str, Any]:
        """Parse LLM response into structured proposal.

        Args:
            llm_response: Raw LLM response

        Returns:
            Structured proposal dictionary
        """
        try:
            # Try to extract JSON from response
            # Look for JSON block between ```json and ``` or just plain JSON
            response_text = llm_response.strip()

            # Try to find JSON block
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            elif "{" in response_text:
                # Try to parse from first { to last }
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                json_str = response_text[start:end]
            else:
                raise ValueError("No JSON found in response")

            proposal = json.loads(json_str)

            # Validate required fields
            required_fields = ["solution", "assumptions", "evidence", "confidence"]
            for field in required_fields:
                if field not in proposal:
                    proposal[field] = self._get_default_value(field)

            # Ensure reasoning exists (optional but good to have)
            if "reasoning" not in proposal:
                proposal["reasoning"] = ["Solution proposed based on available information"]

            # Validate confidence is in range
            if not isinstance(proposal["confidence"], (int, float)):
                proposal["confidence"] = 0.5
            proposal["confidence"] = max(0.0, min(1.0, float(proposal["confidence"])))

            return proposal

        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: create a structured proposal from unstructured response
            return {
                "solution": llm_response[:200],
                "assumptions": ["LLM did not provide structured output"],
                "evidence": [{"source": "llm_response", "description": "unstructured response"}],
                "reasoning": ["Proposal extracted from unstructured LLM output"],
                "confidence": 0.3  # Low confidence for unstructured
            }

    def _get_default_value(self, field: str) -> Any:
        """Get default value for missing field."""
        defaults = {
            "solution": "No solution provided",
            "assumptions": [],
            "evidence": [],
            "confidence": 0.0,
            "reasoning": []
        }
        return defaults.get(field, None)
