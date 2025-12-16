from abc import ABC, abstractmethod
from rev.models.task import Task
from rev.core.context import RevContext
from typing import Dict, Any, Optional

class BaseAgent(ABC):
    """Abstract base class for all sub-agents with built-in recovery mechanisms."""

    # All agents should limit recovery attempts to prevent infinite loops
    MAX_RECOVERY_ATTEMPTS = 2

    @abstractmethod
    def execute(self, task: Task, context: RevContext) -> str:
        """
        Execute a given task.

        Args:
            task: The task to execute.
            context: The RevContext for the current execution.

        Returns:
            A string containing the result of the execution.
            Special prefixes for recovery:
            - "[RECOVERY_REQUESTED]" - Task failed, requesting replan (will retry)
            - "[FINAL_FAILURE]" - Task exhausted recovery attempts
        """
        pass

    def get_recovery_key(self, task: Task) -> str:
        """Get unique key for tracking recovery attempts per task."""
        agent_name = self.__class__.__name__.lower()
        return f"{agent_name}_recovery_{task.task_id}"

    def get_recovery_attempts(self, task: Task, context: RevContext) -> int:
        """Get current recovery attempt count for this task."""
        key = self.get_recovery_key(task)
        return context.get_agent_state(key, 0)

    def increment_recovery_attempts(self, task: Task, context: RevContext) -> int:
        """Increment recovery attempt count and return new count."""
        key = self.get_recovery_key(task)
        current = context.get_agent_state(key, 0)
        new_count = current + 1
        context.set_agent_state(key, new_count)
        return new_count

    def should_attempt_recovery(self, task: Task, context: RevContext) -> bool:
        """Check if task should attempt recovery (not exhausted attempts)."""
        attempts = self.get_recovery_attempts(task, context)
        return attempts < self.MAX_RECOVERY_ATTEMPTS

    def make_recovery_request(self, error_type: str, error_detail: str) -> str:
        """Generate a recovery request signal."""
        return f"[RECOVERY_REQUESTED] {error_type}: {error_detail}"

    def make_failure_signal(self, error_type: str, error_detail: str) -> str:
        """Generate a final failure signal."""
        return f"[FINAL_FAILURE] {error_type}: {error_detail}"

    def request_replan(self, context: RevContext, reason: str, detailed_reason: str = ""):
        """Request the orchestrator to replan."""
        context.add_agent_request("REPLAN_REQUEST", {"agent": self.__class__.__name__, "reason": reason, "detailed_reason": detailed_reason})

    def request_research(self, context: RevContext, query: str, reason: str = ""):
        """Request the orchestrator to perform more research."""
        context.add_agent_request("RESEARCH_REQUEST", {"agent": self.__class__.__name__, "query": query, "reason": reason})