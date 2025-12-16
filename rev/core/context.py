from typing import Dict, Any, List, Optional
from rev.models.task import ExecutionPlan, Task
from rev.execution.state_manager import StateManager
from rev.tools.git_ops import get_repo_context
from rev.debug_logger import get_logger
from rev.core.shared_enums import AgentPhase # Import AgentPhase from shared_enums
from dataclasses import dataclass, field
import time
import uuid
from rev.config import (
    MAX_STEPS_PER_RUN,
    MAX_LLM_TOKENS_PER_RUN,
    MAX_WALLCLOCK_SECONDS,
)

@dataclass
class ResourceBudget:
    """Resource budget tracker for resource-aware optimization."""
    max_steps: int = MAX_STEPS_PER_RUN
    max_tokens: int = MAX_LLM_TOKENS_PER_RUN
    max_seconds: float = MAX_WALLCLOCK_SECONDS

    # Current usage
    steps_used: int = 0
    tokens_used: int = 0
    seconds_used: float = 0.0

    # Start time for duration tracking
    start_time: float = field(default_factory=time.time)

    def update_step(self, count: int = 1) -> None:
        """Increment step counter."""
        self.steps_used += count

    def update_tokens(self, count: int) -> None:
        """Add to token counter."""
        self.tokens_used += count

    def update_time(self) -> None:
        """Update elapsed time."""
        self.seconds_used = time.time() - self.start_time

    def is_exceeded(self) -> bool:
        """Check if any budget limit is exceeded."""
        self.update_time()
        return (
            self.steps_used >= self.max_steps or
            self.tokens_used >= self.max_tokens or
            self.seconds_used >= self.max_seconds
        )

    def get_remaining(self) -> Dict[str, float]:
        """Get remaining budget percentages."""
        self.update_time()
        return {
            "steps": max(0, (self.max_steps - self.steps_used) / self.max_steps * 100) if self.max_steps > 0 else 100,
            "tokens": max(0, (self.max_tokens - self.tokens_used) / self.max_tokens * 100) if self.max_tokens > 0 else 100,
            "time": max(0, (self.max_seconds - self.seconds_used) / self.max_seconds * 100) if self.max_seconds > 0 else 100
        }

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        self.update_time()
        return (
            f"Steps: {self.steps_used}/{self.max_steps} | "
            f"Tokens: {self.tokens_used}/{self.max_tokens} | "
            f"Time: {self.seconds_used:.1f}s/{self.max_seconds:.0f}s"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        self.update_time()
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "seconds_used": self.seconds_used,
            "steps_remaining_pct": self.get_remaining()["steps"],
            "tokens_remaining_pct": self.get_remaining()["tokens"],
            "time_remaining_pct": self.get_remaining()["time"],
            "exceeded": self.is_exceeded()
        }


class RevContext:
    """
    A centralized context object for the rev system.
    This object holds all relevant information that agents and components need to access
    and share during an execution run.
    """

    def __init__(self, user_request: str, initial_plan: Optional[ExecutionPlan] = None):
        self.run_id: str = str(uuid.uuid4())  # Unique ID for each orchestration run
        self.user_request: str = user_request
        self.plan: Optional[ExecutionPlan] = initial_plan
        self.state_manager: Optional[StateManager] = None
        self.resource_budget: ResourceBudget = ResourceBudget()
        self.repo_context: str = "" # Populated on demand or by orchestrator
        self.current_phase: AgentPhase = AgentPhase.LEARNING
        self.agent_insights: Dict[str, Any] = {} # Shared dictionary for agents to log insights
        self.errors: List[str] = [] # Shared list for agents to log errors
        self.agent_requests: List[Dict[str, Any]] = [] # New: list to store agent requests
        self.logger = get_logger()
        self.session_id: str = "" # Will be set by StateManager

    def update_plan(self, new_plan: ExecutionPlan):
        """Update the current execution plan."""
        self.plan = new_plan
        if self.state_manager:
            self.state_manager.plan = new_plan # Ensure state manager has the latest plan

    def set_state_manager(self, state_manager: StateManager):
        """Set the state manager instance and update session_id."""
        self.state_manager = state_manager
        self.session_id = state_manager.session_id

    def set_current_phase(self, phase: AgentPhase):
        """Set the current phase of the execution."""
        self.current_phase = phase

    def update_repo_context(self):
        """Update the repository context string."""
        self.repo_context = get_repo_context()

    def add_insight(self, agent_name: str, key: str, value: Any):
        """Add an insight from an agent."""
        if agent_name not in self.agent_insights:
            self.agent_insights[agent_name] = {}
        self.agent_insights[agent_name][key] = value

    def add_error(self, error_message: str):
        """Add an error message to the context."""
        self.errors.append(error_message)
        self.logger.log("context", "ERROR_ADDED", {"error": error_message}, "ERROR")

    def add_agent_request(self, request_type: str, details: Dict[str, Any]):
        """Add a request from an agent to the context."""
        request = {"type": request_type, "details": details}
        self.agent_requests.append(request)
        self.logger.log("context", "AGENT_REQUEST_ADDED", request, "INFO")

    def __str__(self):
        return (
            f"RevContext(user_request='{self.user_request[:50]}...', "
            f"current_phase={self.current_phase.value}, "
            f"plan_tasks={len(self.plan.tasks) if self.plan else 0}, "
            f"errors={len(self.errors)})"
        )