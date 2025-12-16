#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for expanded agent registry with all sub-agents."""

import unittest
from rev.core.agent_registry import AgentRegistry
from rev.agents.base import BaseAgent
from rev.agents.code_writer import CodeWriterAgent
from rev.agents.test_executor import TestExecutorAgent
from rev.agents.refactoring import RefactoringAgent
from rev.agents.debugging import DebuggingAgent
from rev.agents.documentation import DocumentationAgent
from rev.agents.research import ResearchAgent
from rev.agents.analysis import AnalysisAgent
from rev.agents.tool_creation import ToolCreationAgent


class TestAgentRegistryExpanded(unittest.TestCase):
    """Test that all agents are registered correctly."""

    def test_all_agents_registered(self):
        """Verify all expected agents are registered."""
        expected_action_types = [
            "add", "edit", "refactor",  # Code modification
            "test", "debug", "fix",  # Testing and debugging
            "document", "docs",  # Documentation
            "research", "investigate",  # Research
            "analyze", "review",  # Analysis
            "create_tool", "tool"  # Tool creation
        ]

        registered_types = AgentRegistry.get_registered_action_types()

        for action_type in expected_action_types:
            self.assertIn(action_type, registered_types,
                         f"Action type '{action_type}' should be registered")

    def test_agent_instance_creation(self):
        """Verify we can create instances of all registered agents."""
        registered_types = AgentRegistry.get_registered_action_types()

        for action_type in registered_types:
            with self.subTest(action_type=action_type):
                agent = AgentRegistry.get_agent_instance(action_type)
                self.assertIsInstance(agent, BaseAgent,
                                     f"Agent for '{action_type}' should be a BaseAgent")

    def test_code_modification_agents(self):
        """Test code modification agent types."""
        # add and edit should use CodeWriterAgent
        add_agent = AgentRegistry.get_agent_instance("add")
        edit_agent = AgentRegistry.get_agent_instance("edit")
        self.assertIsInstance(add_agent, CodeWriterAgent)
        self.assertIsInstance(edit_agent, CodeWriterAgent)

        # refactor should use RefactoringAgent
        refactor_agent = AgentRegistry.get_agent_instance("refactor")
        self.assertIsInstance(refactor_agent, RefactoringAgent)

    def test_testing_and_debugging_agents(self):
        """Test testing and debugging agent types."""
        # test should use TestExecutorAgent
        test_agent = AgentRegistry.get_agent_instance("test")
        self.assertIsInstance(test_agent, TestExecutorAgent)

        # debug and fix should use DebuggingAgent
        debug_agent = AgentRegistry.get_agent_instance("debug")
        fix_agent = AgentRegistry.get_agent_instance("fix")
        self.assertIsInstance(debug_agent, DebuggingAgent)
        self.assertIsInstance(fix_agent, DebuggingAgent)

    def test_documentation_agents(self):
        """Test documentation agent types."""
        # document and docs should use DocumentationAgent
        document_agent = AgentRegistry.get_agent_instance("document")
        docs_agent = AgentRegistry.get_agent_instance("docs")
        self.assertIsInstance(document_agent, DocumentationAgent)
        self.assertIsInstance(docs_agent, DocumentationAgent)

    def test_research_agents(self):
        """Test research agent types."""
        # research and investigate should use ResearchAgent
        research_agent = AgentRegistry.get_agent_instance("research")
        investigate_agent = AgentRegistry.get_agent_instance("investigate")
        self.assertIsInstance(research_agent, ResearchAgent)
        self.assertIsInstance(investigate_agent, ResearchAgent)

    def test_analysis_agents(self):
        """Test analysis agent types."""
        # analyze and review should use AnalysisAgent
        analyze_agent = AgentRegistry.get_agent_instance("analyze")
        review_agent = AgentRegistry.get_agent_instance("review")
        self.assertIsInstance(analyze_agent, AnalysisAgent)
        self.assertIsInstance(review_agent, AnalysisAgent)

    def test_tool_creation_agents(self):
        """Test tool creation agent types."""
        # create_tool and tool should use ToolCreationAgent
        create_tool_agent = AgentRegistry.get_agent_instance("create_tool")
        tool_agent = AgentRegistry.get_agent_instance("tool")
        self.assertIsInstance(create_tool_agent, ToolCreationAgent)
        self.assertIsInstance(tool_agent, ToolCreationAgent)

    def test_invalid_action_type(self):
        """Test that invalid action types raise ValueError."""
        with self.assertRaises(ValueError):
            AgentRegistry.get_agent_instance("nonexistent_action_type")


if __name__ == "__main__":
    unittest.main()
