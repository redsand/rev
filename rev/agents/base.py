from abc import ABC, abstractmethod
from rev.models.task import Task
from rev.core.context import RevContext
from typing import Dict, Any

class BaseAgent(ABC):
    """Abstract base class for all sub-agents."""

    @abstractmethod
    def execute(self, task: Task, context: RevContext) -> str:
        """
        Execute a given task.

        Args:
            task: The task to execute.
            context: The RevContext for the current execution.

        Returns:
            A string containing the result of the execution.
        """
        pass

    def request_replan(self, context: RevContext, reason: str, detailed_reason: str = ""):
        """Request the orchestrator to replan."""
        context.add_agent_request("REPLAN_REQUEST", {"agent": self.__class__.__name__, "reason": reason, "detailed_reason": detailed_reason})

    def request_research(self, context: RevContext, query: str, reason: str = ""):
        """Request the orchestrator to perform more research."""
        context.add_agent_request("RESEARCH_REQUEST", {"agent": self.__class__.__name__, "query": query, "reason": reason})