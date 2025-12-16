from typing import Dict, Type, List
from rev.agents.base import BaseAgent
from rev.agents.code_writer import CodeWriterAgent
from rev.agents.test_executor import TestExecutorAgent
from rev.agents.refactoring import RefactoringAgent
from rev.agents.debugging import DebuggingAgent
from rev.agents.documentation import DocumentationAgent
from rev.agents.research import ResearchAgent
from rev.agents.analysis import AnalysisAgent
from rev.agents.tool_creation import ToolCreationAgent

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

# Register default agents
# Code modification agents
AgentRegistry.register_agent("add", CodeWriterAgent)
AgentRegistry.register_agent("edit", CodeWriterAgent)
AgentRegistry.register_agent("refactor", RefactoringAgent)

# Testing and debugging agents
AgentRegistry.register_agent("test", TestExecutorAgent)
AgentRegistry.register_agent("debug", DebuggingAgent)
AgentRegistry.register_agent("fix", DebuggingAgent)

# Documentation agents
AgentRegistry.register_agent("document", DocumentationAgent)
AgentRegistry.register_agent("docs", DocumentationAgent)

# Research and analysis agents
AgentRegistry.register_agent("research", ResearchAgent)
AgentRegistry.register_agent("investigate", ResearchAgent)
AgentRegistry.register_agent("analyze", AnalysisAgent)
AgentRegistry.register_agent("review", AnalysisAgent)

# Advanced agents
AgentRegistry.register_agent("create_tool", ToolCreationAgent)
AgentRegistry.register_agent("tool", ToolCreationAgent)