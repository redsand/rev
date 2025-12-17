from enum import Enum

class AgentPhase(Enum):
    """Phases of the orchestrated workflow."""
    LEARNING = "learning"
    RESEARCH = "research"
    CONTEXT_GUARD = "context_guard"
    PLANNING = "planning"
    REVIEW = "review"
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMPLETE = "complete"
    FAILED = "failed"
