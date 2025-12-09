#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task Router for adaptive multi-agent coordination.

This module implements the Routing pattern from Agentic Design Patterns,
dynamically selecting the appropriate execution mode and agent configuration
based on request characteristics.
"""

from dataclasses import dataclass
from typing import Literal, Dict, Any, Optional
from enum import Enum


# Route modes - different execution strategies
RouteMode = Literal["quick_edit", "full_feature", "refactor", "test_focus", "exploration", "security_audit"]


class RoutePriority(Enum):
    """Priority levels for routed tasks."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class RouteDecision:
    """Decision from the router about how to execute a task.

    This encapsulates all the configuration choices the router makes
    based on analyzing the user request.
    """
    mode: RouteMode
    enable_learning: bool
    enable_research: bool
    enable_review: bool
    enable_validation: bool
    review_strictness: str = "moderate"  # strict, moderate, lenient
    parallel_workers: int = 2
    enable_action_review: bool = False
    research_depth: str = "medium"  # shallow, medium, deep
    max_retries: int = 2
    priority: RoutePriority = RoutePriority.NORMAL
    reasoning: str = ""  # Why this route was chosen

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode,
            "enable_learning": self.enable_learning,
            "enable_research": self.enable_research,
            "enable_review": self.enable_review,
            "enable_validation": self.enable_validation,
            "review_strictness": self.review_strictness,
            "parallel_workers": self.parallel_workers,
            "enable_action_review": self.enable_action_review,
            "research_depth": self.research_depth,
            "max_retries": self.max_retries,
            "priority": self.priority.value,
            "reasoning": self.reasoning
        }


class TaskRouter:
    """Routes tasks to appropriate execution modes based on characteristics.

    The router uses heuristics to classify incoming requests and choose
    the optimal agent configuration and execution strategy.
    """

    def route(self, user_request: str, repo_stats: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """Route a user request to the appropriate execution mode.

        Args:
            user_request: The user's task description
            repo_stats: Optional repository statistics (file count, test presence, etc.)

        Returns:
            RouteDecision with execution configuration
        """
        text = user_request.lower()
        repo_stats = repo_stats or {}

        # Security audit mode
        if self._is_security_audit(text):
            return RouteDecision(
                mode="security_audit",
                enable_learning=True,
                enable_research=True,
                enable_review=True,
                enable_validation=True,
                review_strictness="strict",
                parallel_workers=1,  # Sequential for security
                enable_action_review=True,
                research_depth="deep",
                max_retries=3,
                priority=RoutePriority.CRITICAL,
                reasoning="Security audit requires thorough analysis and strict review"
            )

        # Structural change mode - requires deep investigation
        # Covers: schemas, types, classes, documentation, configuration
        if self._is_structural_change(text):
            return RouteDecision(
                mode="full_feature",
                enable_learning=True,
                enable_research=True,  # Critical: must research existing structures
                enable_review=True,
                enable_validation=True,
                review_strictness="strict",
                parallel_workers=1,  # Sequential to avoid conflicts
                enable_action_review=True,
                research_depth="deep",  # Deep search for existing structures
                max_retries=3,
                priority=RoutePriority.HIGH,
                reasoning="Structural changes require deep investigation of existing definitions to avoid duplication"
            )

        # Test-focused mode
        if self._is_test_focus(text):
            return RouteDecision(
                mode="test_focus",
                enable_learning=False,
                enable_research=False,
                enable_review=True,
                enable_validation=True,
                review_strictness="moderate",
                parallel_workers=2,
                research_depth="shallow",
                max_retries=2,
                priority=RoutePriority.HIGH,
                reasoning="Test-focused task requires validation but minimal research"
            )

        # Refactor mode
        if self._is_refactor(text):
            return RouteDecision(
                mode="refactor",
                enable_learning=True,
                enable_research=True,
                enable_review=True,
                enable_validation=True,
                review_strictness="strict",
                parallel_workers=1,  # Sequential for refactoring
                research_depth="deep",
                max_retries=3,
                priority=RoutePriority.HIGH,
                reasoning="Refactoring requires deep analysis and careful review"
            )

        # Full feature mode
        if self._is_full_feature(text):
            return RouteDecision(
                mode="full_feature",
                enable_learning=True,
                enable_research=True,
                enable_review=True,
                enable_validation=True,
                review_strictness="moderate",
                parallel_workers=3,  # More parallelism for features
                research_depth="medium",
                max_retries=3,
                priority=RoutePriority.NORMAL,
                reasoning="Full feature implementation with all agents enabled"
            )

        # Exploration mode
        if self._is_exploration(text):
            return RouteDecision(
                mode="exploration",
                enable_learning=True,
                enable_research=True,
                enable_review=False,  # Exploratory, no need for strict review
                enable_validation=False,
                parallel_workers=1,
                research_depth="deep",
                max_retries=1,
                priority=RoutePriority.LOW,
                reasoning="Exploratory task focused on research and learning"
            )

        # Default: quick edit mode
        return RouteDecision(
            mode="quick_edit",
            enable_learning=False,
            enable_research=False,
            enable_review=True,
            enable_validation=True,
            review_strictness="lenient",
            parallel_workers=2,
            research_depth="shallow",
            max_retries=2,
            priority=RoutePriority.NORMAL,
            reasoning="Simple quick edit with minimal overhead"
        )

    def _is_security_audit(self, text: str) -> bool:
        """Check if request is a security audit."""
        security_keywords = [
            "security audit", "vulnerability", "cve", "exploit",
            "penetration test", "security scan", "threat"
        ]
        return any(keyword in text for keyword in security_keywords)

    def _is_structural_change(self, text: str) -> bool:
        """Check if request involves structural changes to code, schemas, docs, or config."""
        structure_keywords = [
            # Database/Schema structures
            "prisma", "schema", "database", "enum", "model",
            "migration", "sequelize", "typeorm", "mongoose",
            "table", "entity", "sql",
            # Code structures
            "class", "interface", "type", "typedef", "struct",
            "enum", "dataclass",
            # Documentation structures
            "readme", "documentation", "docs", "api documentation",
            "guide", "tutorial",
            # Configuration structures
            "config", "configuration", "settings", "environment",
            ".env", "config file"
        ]

        # Action verbs that indicate creation/modification
        action_verbs = [
            "add", "create", "update", "modify", "change",
            "define", "implement", "build", "generate"
        ]

        # Must have structure keyword AND an action verb
        has_structure = any(keyword in text for keyword in structure_keywords)
        has_action = any(action in text for action in action_verbs)

        return has_structure and has_action

    def _is_test_focus(self, text: str) -> bool:
        """Check if request is test-focused."""
        # Must have "test" and NOT be adding features
        has_test = any(word in text for word in ["test", "testing", "coverage", "pytest"])
        not_feature = not any(word in text for word in ["add", "build", "implement", "create", "feature"])
        return has_test and not_feature

    def _is_refactor(self, text: str) -> bool:
        """Check if request is a refactoring task."""
        refactor_keywords = [
            "refactor", "cleanup", "restructure", "reorganize",
            "simplify", "optimize code", "improve structure"
        ]
        return any(keyword in text for keyword in refactor_keywords)

    def _is_full_feature(self, text: str) -> bool:
        """Check if request is a full feature implementation."""
        feature_keywords = [
            "add", "build", "implement", "create", "feature",
            "functionality", "new capability", "integrate"
        ]
        return any(keyword in text for keyword in feature_keywords)

    def _is_exploration(self, text: str) -> bool:
        """Check if request is exploratory/research."""
        exploration_keywords = [
            "explore", "investigate", "analyze", "research",
            "understand", "how does", "what is", "explain"
        ]
        return any(keyword in text for keyword in exploration_keywords)


def get_default_router() -> TaskRouter:
    """Get a default task router instance."""
    return TaskRouter()
