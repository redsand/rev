from typing import Dict, Type, List
from rev.agents.base import BaseAgent
from rev.agents.analysis import AnalysisAgent
from rev.agents.documentation import DocumentationAgent
from rev.agents.research import ResearchAgent
from rev.agents.tool_executor import ToolExecutorAgent

class AgentRegistry:
    """
    A registry for managing and providing access to different sub-agents.
    """

    _agents: Dict[str, Type[BaseAgent]] = {}

    @classmethod
    def register_agent(cls, action_type: str, agent_class: Type[BaseAgent]):
        """Register an agent class with a specific action type."""
        if not issubclass(agent_class, BaseAgent):
            raise ValueError(f"Class {agent_class.__name__} must inherit from BaseAgent.")
        cls._agents[action_type] = agent_class

    @classmethod
    def get_agent_instance(cls, action_type: str) -> BaseAgent:
        """Get an instance of the agent registered for the given action type."""
        agent_class = cls._agents.get(action_type)
        if not agent_class:
            raise ValueError(f"No agent registered for action type: {action_type}")
        return agent_class()

    @classmethod
    def get_registered_action_types(cls) -> List[str]:
        """Get a list of all registered action types."""
        return list(cls._agents.keys())

# Register SOC-focused agents
# Research/investigation
AgentRegistry.register_agent("research", ResearchAgent)
AgentRegistry.register_agent("investigate", ResearchAgent)
AgentRegistry.register_agent("triage", AnalysisAgent)
AgentRegistry.register_agent("analyze", AnalysisAgent)

# Documentation and reporting
AgentRegistry.register_agent("document", DocumentationAgent)
AgentRegistry.register_agent("docs", DocumentationAgent)
AgentRegistry.register_agent("report", DocumentationAgent)

# Escalation and containment actions
AgentRegistry.register_agent("escalate", ToolExecutorAgent)
AgentRegistry.register_agent("contain", ToolExecutorAgent)
AgentRegistry.register_agent("mitigate", ToolExecutorAgent)
AgentRegistry.register_agent("tool", ToolExecutorAgent)
