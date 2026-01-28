"""
DeepReasoningAgent - For complex multi-step reasoning without interruption.

This agent is designed for complex tasks that require:
- Long chains of thought (10+ steps)
- Exploration of multiple solution paths
- Building complex mental models
- Multi-step reasoning without tool call interruptions
- Comprehensive solution planning

Unlike specialized agents that execute specific operations, this agent:
1. Thinks deeply about the entire problem
2. Builds a comprehensive solution plan
3. Delegates execution to specialized agents
4. Maintains context throughout the reasoning chain
"""

import json
import re
import os
from typing import Any, Dict, List, Optional, Tuple
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.tools.registry import get_available_tools, execute_tool
from rev.agents.subagent_io import build_subagent_output
from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.execution.context_guard import extract_user_intent
from rev import config


DEEP_REASONING_SYSTEM = """You are a DeepReasoningAgent specializing in complex, multi-step problem solving.

Your purpose is to think deeply about complex tasks without interruption, exploring multiple solution paths and building comprehensive mental models.

CRITICAL DIFFERENCES FROM OTHER AGENTS:
1. YOU THINK BEFORE ACTING - Perform extended reasoning (3-10 steps) before any tool calls
2. YOU EXPLORE ALTERNATIVES - Consider multiple approaches before choosing
3. YOU BUILD MENTAL MODELS - Create comprehensive understanding of the problem space
4. YOU PRODUCE PLANS - Generate detailed solution plans, not just immediate actions
5. YOU MAINTAIN CONTEXT - Keep the entire reasoning chain in mind

DEEP REASONING WORKFLOW:
1. UNDERSTAND: Analyze the problem, constraints, and requirements
2. EXPLORE: Consider 2-3 alternative approaches with pros/cons
3. MODEL: Build mental model of solution architecture
4. PLAN: Create detailed execution plan with dependencies
5. EXECUTE: Use tools to gather necessary information
6. REFINE: Adjust plan based on new information
7. DELEGATE: Generate tasks for specialized agents to execute

TOOL USAGE GUIDELINES:
- Use tools primarily for INFORMATION GATHERING (read_file, search_code, list_dir)
- Limit write/modification tools - your job is to PLAN, not implement
- Gather enough context to make informed decisions
- After gathering context, produce a comprehensive solution plan

OUTPUT FORMAT:
1. For thinking phases: Use [THINKING: ...] blocks
2. For information gathering: Make tool calls
3. For final output: Return a [DEEP_PLAN] JSON structure

[DEEP_PLAN] JSON structure:
{
  "reasoning_steps": ["step1", "step2", ...],
  "alternative_approaches": [
    {"approach": "description", "pros": [...], "cons": [...]}
  ],
  "chosen_approach": "description",
  "solution_architecture": "description",
  "execution_plan": [
    {"task": "description", "agent": "agent_type", "priority": "high/medium/low"}
  ],
  "delegation_instructions": "Instructions for orchestrator"
}

REMEMBER: Your value is in DEEP THINKING, not rapid execution. Take the time needed."""


class DeepReasoningAgent(BaseAgent):
    """Agent for complex multi-step reasoning without interruption."""

    MAX_RECOVERY_ATTEMPTS = 1  # Deep reasoning should rarely need recovery
    MAX_REASONING_STEPS = 15   # Maximum thinking steps before tool calls

    def execute(self, task: Task, context: RevContext) -> str:
        """Execute complex reasoning task."""

        # Extract user intent and complexity
        user_intent = self._extract_intent(task.description)
        complexity = self._assess_complexity(task.description, user_intent)

        print(f"  [DeepReasoning] Starting complex task (complexity: {complexity}/10)")
        print(f"  [DeepReasoning] Intent: {user_intent.get('primary_intent', 'unknown')}")

        # Build enhanced context for deep reasoning
        tools = get_available_tools()
        enhanced_context = self._build_enhanced_context(task, context, tools)

        # Perform deep reasoning
        reasoning_result = self._perform_deep_reasoning(
            task=task,
            context=context,
            enhanced_context=enhanced_context,
            tools=tools,
            complexity=complexity
        )

        # Handle different result types
        if isinstance(reasoning_result, dict) and "deep_plan" in reasoning_result:
            return self._format_deep_plan_result(reasoning_result, task, context)
        elif isinstance(reasoning_result, str) and reasoning_result.startswith("[TOOL_CALL]"):
            return self._execute_tool_from_reasoning(reasoning_result, task, context)
        else:
            return self._format_thinking_result(reasoning_result, task, context)

    def _extract_intent(self, description: str) -> Dict[str, Any]:
        """Extract user intent from task description."""
        intent = {
            "primary_intent": "unknown",
            "complexity_hints": [],
            "requires_research": False,
            "requires_architecture": False
        }

        desc_lower = description.lower()

        # Detect intent patterns
        if any(keyword in desc_lower for keyword in ["refactor", "restructure", "reorganize"]):
            intent["primary_intent"] = "refactoring"
            intent["requires_architecture"] = True
        elif any(keyword in desc_lower for keyword in ["implement", "add feature", "new feature"]):
            intent["primary_intent"] = "implementation"
            intent["requires_research"] = True
        elif any(keyword in desc_lower for keyword in ["debug", "fix", "solve issue"]):
            intent["primary_intent"] = "debugging"
            intent["requires_research"] = True
        elif any(keyword in desc_lower for keyword in ["analyze", "understand", "research"]):
            intent["primary_intent"] = "analysis"
            intent["requires_research"] = True
        elif any(keyword in desc_lower for keyword in ["design", "architecture", "plan"]):
            intent["primary_intent"] = "design"
            intent["requires_architecture"] = True

        # Detect complexity hints
        complexity_hints = [
            "complex", "difficult", "challenging", "multi-step",
            "multiple", "integrate", "system", "architecture"
        ]
        intent["complexity_hints"] = [hint for hint in complexity_hints if hint in desc_lower]

        return intent

    def _assess_complexity(self, description: str, intent: Dict[str, Any]) -> int:
        """Assess task complexity on scale 1-10."""
        complexity = 3  # Baseline

        # Intent-based complexity
        intent_complexity = {
            "refactoring": 7,
            "implementation": 6,
            "debugging": 5,
            "analysis": 4,
            "design": 8
        }
        complexity += intent_complexity.get(intent.get("primary_intent", "unknown"), 0)

        # Length-based complexity
        word_count = len(description.split())
        if word_count > 50:
            complexity += 2
        elif word_count > 100:
            complexity += 3

        # Keyword-based complexity
        complex_keywords = [
            "system", "architecture", "integration", "multiple",
            "complex", "difficult", "challenging", "redesign"
        ]
        desc_lower = description.lower()
        for keyword in complex_keywords:
            if keyword in desc_lower:
                complexity += 1

        return min(max(complexity, 1), 10)

    def _build_enhanced_context(self, task: Task, context: RevContext, tools: List[Dict]) -> Dict[str, Any]:
        """Build enhanced context for deep reasoning."""
        enhanced_context = {
            "task": {
                "description": task.description,
                "action_type": task.action_type
            },
            "user_intent": self._extract_intent(task.description),
            "available_tools": [t.get("function", {}).get("name") for t in tools if isinstance(t, dict)],
            "agent_state": context.agent_state if hasattr(context, 'agent_state') else {},
            "work_history": context.work_history if hasattr(context, 'work_history') else []
        }

        # Add project context if available
        if hasattr(context, 'project_root'):
            enhanced_context["project_root"] = str(context.project_root)

        return enhanced_context

    def _perform_deep_reasoning(self, task: Task, context: RevContext,
                               enhanced_context: Dict[str, Any], tools: List[Dict],
                               complexity: int) -> Any:
        """Perform multi-step deep reasoning."""

        # Prepare messages for LLM
        messages = [
            {"role": "system", "content": DEEP_REASONING_SYSTEM},
            {"role": "user", "content": self._build_reasoning_prompt(task, enhanced_context, complexity)}
        ]

        # Perform reasoning with extended parameters
        try:
            response = ollama_chat(
                messages,
                tools=tools,
                model=config.EXECUTION_MODEL,
                temperature=0.3,  # Lower temp for more consistent reasoning
                max_tokens=8000 if complexity > 7 else 4000  # More tokens for complex tasks
            )

            if not isinstance(response, dict):
                return {"error": "LLM response invalid", "response": str(response)}

            message = response.get("message", {})

            # Check for tool calls (information gathering)
            if "tool_calls" in message and message["tool_calls"]:
                return self._handle_reasoning_tool_calls(message["tool_calls"], task, context)

            # Check for structured deep plan
            content = message.get("content", "")
            deep_plan_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if deep_plan_match:
                try:
                    deep_plan = json.loads(deep_plan_match.group(1))
                    return {"deep_plan": deep_plan, "raw_content": content}
                except json.JSONDecodeError:
                    pass

            # Check for inline JSON
            json_match = re.search(r'\{.*"execution_plan".*\}', content, re.DOTALL)
            if json_match:
                try:
                    deep_plan = json.loads(json_match.group(0))
                    return {"deep_plan": deep_plan, "raw_content": content}
                except json.JSONDecodeError:
                    pass

            # Return thinking content
            return {"thinking": content, "needs_more_context": True}

        except Exception as e:
            return {"error": f"Reasoning failed: {str(e)}"}

    def _build_reasoning_prompt(self, task: Task, enhanced_context: Dict[str, Any], complexity: int) -> str:
        """Build prompt for deep reasoning."""

        prompt = f"""DEEP REASONING TASK - Complexity: {complexity}/10

TASK: {task.description}

CONTEXT ANALYSIS:
- Primary Intent: {enhanced_context.get('user_intent', {}).get('primary_intent', 'unknown')}
- Requires Research: {enhanced_context.get('user_intent', {}).get('requires_research', False)}
- Requires Architecture: {enhanced_context.get('user_intent', {}).get('requires_architecture', False)}

AVAILABLE TOOLS (for information gathering):
{', '.join(enhanced_context.get('available_tools', []))}

INSTRUCTIONS:
1. First, think deeply about the problem (3-5 reasoning steps)
2. Consider 2-3 alternative approaches
3. Identify what information you need
4. Use tools to gather necessary context
5. Create a comprehensive solution plan
6. Structure your output as a [DEEP_PLAN] JSON

THINKING TEMPLATE:
[THINKING: Step 1 - Problem decomposition]
[THINKING: Step 2 - Alternative approaches]
[THINKING: Step 3 - Information needs]
[TOOL_CALL: gather information]
[THINKING: Step 4 - Solution synthesis]
[THINKING: Step 5 - Plan creation]
[DEEP_PLAN: {{...}}]

Begin your deep reasoning now."""

        return prompt

    def _handle_reasoning_tool_calls(self, tool_calls: List[Dict], task: Task, context: RevContext) -> str:
        """Handle tool calls during reasoning phase."""

        # For deep reasoning, we execute tools but mark them as "research" not "execution"
        tool_results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("arguments", {})

            print(f"  [DeepReasoning] Gathering context: {tool_name}")

            # Execute tool
            try:
                result = execute_tool(tool_name, tool_args, agent_name="DeepReasoningAgent")
                tool_results.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result[:500] if isinstance(result, str) else str(result)[:500]
                })
            except Exception as e:
                tool_results.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "error": str(e)
                })

        # Return tool results wrapped in thinking context
        return f"""[THINKING: Information gathering complete]
[TOOL_RESULTS: {json.dumps(tool_results, indent=2)}]
[THINKING: Analyzing gathered information...]
Please continue your deep reasoning with this new context."""

    def _execute_tool_from_reasoning(self, reasoning_text: str, task: Task, context: RevContext) -> str:
        """Extract and execute tool call from reasoning text."""

        # Extract tool call pattern
        tool_pattern = r'\[TOOL_CALL:\s*(.+?)\]'
        match = re.search(tool_pattern, reasoning_text, re.DOTALL)

        if not match:
            return self._format_thinking_result(reasoning_text, task, context)

        tool_text = match.group(1).strip()

        # Try to recover tool call from text
        available_tools = [t.get("function", {}).get("name") for t in get_available_tools() if isinstance(t, dict)]
        recovered = recover_tool_call_from_text(tool_text, available_tools)

        if recovered:
            try:
                result = execute_tool(recovered.tool_name, recovered.tool_args, agent_name="DeepReasoningAgent")
                return build_subagent_output(
                    agent_name="DeepReasoningAgent",
                    tool_name=recovered.tool_name,
                    tool_args=recovered.tool_args,
                    tool_output=result,
                    context=context,
                    task_id=task.task_id
                )
            except Exception as e:
                return f"[TOOL_ERROR] {str(e)}"

        return self._format_thinking_result(reasoning_text, task, context)

    def _format_deep_plan_result(self, reasoning_result: Dict[str, Any], task: Task, context: RevContext) -> str:
        """Format deep plan result for orchestrator."""

        deep_plan = reasoning_result.get("deep_plan", {})

        # Add deep plan to context for orchestrator to use
        if hasattr(context, 'agent_state'):
            context.agent_state["deep_reasoning_plan"] = deep_plan

        # Create delegation instructions
        delegation = {
            "agent": "DeepReasoningAgent",
            "plan": deep_plan,
            "instructions": "Execute via specialized agents",
            "complexity": self._assess_complexity(task.description, self._extract_intent(task.description))
        }

        return json.dumps({
            "deep_reasoning_complete": True,
            "delegation_instructions": delegation,
            "execution_plan": deep_plan.get("execution_plan", []),
            "reasoning_steps": deep_plan.get("reasoning_steps", []),
            "message": "Deep reasoning complete. Ready for orchestrated execution."
        })

    def _format_thinking_result(self, reasoning_result: Any, task: Task, context: RevContext) -> str:
        """Format thinking result (intermediate or error)."""

        if isinstance(reasoning_result, dict):
            if "error" in reasoning_result:
                return f"[DEEP_REASONING_ERROR] {reasoning_result['error']}"
            elif "thinking" in reasoning_result:
                return f"[THINKING_IN_PROGRESS] {reasoning_result['thinking'][:500]}"

        return f"[DEEP_REASONING] {str(reasoning_result)[:1000]}"