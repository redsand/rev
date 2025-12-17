"""
Adaptive Prompt Optimizer for Agent System Prompts

This module improves agent system prompts based on their execution failures.
When an agent fails, this optimizer:
1. Analyzes what went wrong (tool usage, execution patterns)
2. Detects failure patterns (e.g., "only reads, never writes")
3. Auto-improves the agent's system prompt to fix the issue
4. Returns an improved prompt for retry

This creates a feedback loop:
Plan → Execute → Verify → Analyze Failure → Improve Prompt → Retry
"""

import logging
from typing import Dict, Any, Optional, Tuple
from rev.models.task import Task
from rev.llm.client import ollama_chat

logger = logging.getLogger(__name__)


def analyze_tool_call_pattern(tool_calls: list) -> Dict[str, Any]:
    """
    Analyze the pattern of tool calls made by an agent.

    Returns analysis like:
    - "only read_file: 5 calls"
    - "missing write_file: expected but not called"
    - "tool sequence: read → analyze → stop (incomplete)"
    """
    if not tool_calls:
        return {"pattern": "no_tools", "issue": "Agent made no tool calls"}

    tool_names = [tc.get('function', {}).get('name', 'unknown') for tc in tool_calls]
    tool_counts = {}
    for tool in tool_names:
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    analysis = {
        "tool_calls_count": len(tool_calls),
        "tools_used": list(tool_counts.keys()),
        "tool_counts": tool_counts,
        "pattern": " → ".join(tool_names),
    }

    # Detect common failure patterns
    if "read_file" in tool_counts and "write_file" not in tool_counts:
        analysis["issue"] = "Agent reads files but never writes new files"
        analysis["failure_type"] = "INCOMPLETE_EXTRACTION"
    elif "replace_in_file" not in tool_counts and "write_file" not in tool_counts:
        analysis["issue"] = "Agent never modifies any files"
        analysis["failure_type"] = "NO_MODIFICATIONS"

    return analysis


def get_agent_prompt_improvement(
    agent_type: str,
    task_description: str,
    failure_reason: str,
    tool_analysis: Dict[str, Any],
    original_prompt: str,
    retry_attempt: int = 1
) -> Optional[str]:
    """
    Ask LLM to improve an agent's system prompt based on its failures.

    Args:
        agent_type: Type of agent (e.g., "refactoring", "codewriter")
        task_description: What the agent was trying to do
        failure_reason: Why the previous attempt failed
        tool_analysis: Analysis of tool calls made
        original_prompt: The original system prompt
        retry_attempt: Which retry attempt this is (1, 2, 3, etc)

    Returns:
        Improved system prompt, or None if improvement fails
    """

    retry_context = f"\nThis is retry attempt #{retry_attempt}. Previous attempts failed." if retry_attempt > 1 else ""

    improvement_prompt = f"""You are a prompt engineering expert. An agent failed to complete a task.
Your job is to improve its system prompt to fix the failure.

AGENT TYPE: {agent_type}
TASK: {task_description}
FAILURE REASON: {failure_reason}

TOOL USAGE ANALYSIS:
{format_tool_analysis(tool_analysis)}

ORIGINAL SYSTEM PROMPT:
{original_prompt}

IMPROVEMENT REQUIREMENTS:
1. If agent only read files without writing, add explicit requirements to use write_file
2. If agent stopped mid-task, add requirements to complete ALL steps
3. If agent ignored important instructions, make them MORE explicit and repeated
4. Add specific examples of what the agent MUST do
5. For retry attempts, increase explicitness/repetition (don't just repeat)

Provide ONLY the improved system prompt. No explanations, no markdown, just the prompt text.
Make it more direct, explicit, and forceful about required actions.
{retry_context}"""

    messages = [{"role": "user", "content": improvement_prompt}]

    try:
        response = ollama_chat(messages, temperature=0.2)  # Low temp for consistency
        if response and "message" in response and "content" in response["message"]:
            improved = response["message"]["content"].strip()
            logger.info(f"[PROMPT_OPTIMIZER] Improved {agent_type} prompt (attempt {retry_attempt})")
            return improved
    except Exception as e:
        logger.error(f"[PROMPT_OPTIMIZER] Failed to generate improved prompt: {e}")

    return None


def format_tool_analysis(analysis: Dict[str, Any]) -> str:
    """Format tool analysis for readability."""
    lines = [
        f"Tool calls made: {analysis.get('tool_calls_count', 0)}",
        f"Tools used: {', '.join(analysis.get('tools_used', ['none']))}",
        f"Call pattern: {analysis.get('pattern', 'unknown')}",
    ]

    if 'issue' in analysis:
        lines.append(f"Issue detected: {analysis['issue']}")

    if 'failure_type' in analysis:
        lines.append(f"Failure type: {analysis['failure_type']}")

    return "\n".join(lines)


def should_attempt_prompt_improvement(
    task: Task,
    verification_failed: bool,
    retry_count: int,
    max_retries: int = 3
) -> bool:
    """
    Determine if we should attempt to improve the agent's prompt.

    Returns False if:
    - Task succeeded (verification passed)
    - We've already retried max times
    - Task is not extractive/refactoring related
    """
    if not verification_failed:
        return False

    if retry_count >= max_retries:
        logger.info(f"[PROMPT_OPTIMIZER] Max retry attempts ({max_retries}) reached")
        return False

    # Check if this looks like an extraction/refactoring task
    task_desc_lower = task.description.lower()
    keywords = ["extract", "refactor", "move", "break out", "separate", "split", "reorganize"]
    is_structural_task = any(kw in task_desc_lower for kw in keywords)

    if not is_structural_task:
        logger.debug(f"[PROMPT_OPTIMIZER] Not a structural task, skipping prompt improvement")
        return False

    return True


class AdaptivePromptOptimizer:
    """Manages adaptive prompt improvement for agents across retries."""

    def __init__(self):
        self.prompt_history = {}  # agent_type -> [prompt1, prompt2, ...]
        self.failure_patterns = {}  # agent_type -> [pattern1, pattern2, ...]

    def improve_prompt_for_retry(
        self,
        agent_type: str,
        task: Task,
        verification_failure: str,
        tool_calls: list,
        original_prompt: str,
        retry_attempt: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to improve the agent's system prompt for a retry.

        Returns:
            (improved: bool, new_prompt: Optional[str])
        """

        # Analyze tool calls
        tool_analysis = analyze_tool_call_pattern(tool_calls)

        # Check if we should attempt improvement
        if not should_attempt_prompt_improvement(task, True, retry_attempt):
            return False, None

        # Get improved prompt from LLM
        improved_prompt = get_agent_prompt_improvement(
            agent_type=agent_type,
            task_description=task.description,
            failure_reason=verification_failure,
            tool_analysis=tool_analysis,
            original_prompt=original_prompt,
            retry_attempt=retry_attempt
        )

        if improved_prompt:
            # Track the improvement
            if agent_type not in self.prompt_history:
                self.prompt_history[agent_type] = [original_prompt]
            self.prompt_history[agent_type].append(improved_prompt)

            # Track the failure pattern
            if agent_type not in self.failure_patterns:
                self.failure_patterns[agent_type] = []
            self.failure_patterns[agent_type].append(tool_analysis.get("failure_type", "unknown"))

            logger.info(
                f"[PROMPT_OPTIMIZER] Improved {agent_type} prompt "
                f"(failure: {tool_analysis.get('failure_type', 'unknown')}, "
                f"retry: {retry_attempt})"
            )

            return True, improved_prompt

        return False, None

    def get_prompt_history(self, agent_type: str) -> list:
        """Get the evolution of prompts for an agent type."""
        return self.prompt_history.get(agent_type, [])

    def get_failure_patterns(self, agent_type: str) -> list:
        """Get failure patterns encountered for an agent type."""
        return self.failure_patterns.get(agent_type, [])


# Global instance
_optimizer = AdaptivePromptOptimizer()


def improve_prompt_for_retry(
    agent_type: str,
    task: Task,
    verification_failure: str,
    tool_calls: list,
    original_prompt: str,
    retry_attempt: int
) -> Tuple[bool, Optional[str]]:
    """
    Public API: Attempt to improve an agent's prompt for a retry.

    Args:
        agent_type: Type of agent ("refactoring", "codewriter", etc.)
        task: The task that failed
        verification_failure: Why verification failed
        tool_calls: Tool calls the agent made
        original_prompt: The agent's original system prompt
        retry_attempt: Which retry attempt (1, 2, 3, ...)

    Returns:
        (improved: bool, new_prompt: Optional[str])
    """
    return _optimizer.improve_prompt_for_retry(
        agent_type=agent_type,
        task=task,
        verification_failure=verification_failure,
        tool_calls=tool_calls,
        original_prompt=original_prompt,
        retry_attempt=retry_attempt
    )
