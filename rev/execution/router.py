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
RouteMode = Literal["quick_edit", "focused_feature", "full_feature"]


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
    max_plan_tasks: Optional[int] = None
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
            "max_plan_tasks": self.max_plan_tasks,
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

        if self._is_full_feature(text, repo_stats):
            return self._full_feature_decision(text)

        if self._is_quick_edit(text):
            return self._quick_edit_decision(text)

        return self._focused_feature_decision(text)

    def _quick_edit_decision(self, text: str) -> RouteDecision:
        """Quick edit mode for small, localized changes."""
        return RouteDecision(
            mode="quick_edit",
            enable_learning=False,
            enable_research=False,
            enable_review=False,
            enable_validation=True,
            review_strictness="lenient",
            parallel_workers=2,
            research_depth="shallow",
            max_plan_tasks=8,
            max_retries=2,
            priority=RoutePriority.NORMAL,
            reasoning=self._quick_edit_reason(text),
        )

    def _focused_feature_decision(self, text: str) -> RouteDecision:
        """Focused feature mode for multi-file but contained work."""
        enable_review = self._needs_review(text)
        return RouteDecision(
            mode="focused_feature",
            enable_learning=False,
            enable_research=True,
            enable_review=enable_review,
            enable_validation=True,
            review_strictness="moderate",
            parallel_workers=3,
            research_depth="medium",
            max_plan_tasks=20,
            max_retries=3,
            priority=RoutePriority.NORMAL,
            reasoning=self._focused_feature_reason(text, enable_review),
        )

    def _full_feature_decision(self, text: str) -> RouteDecision:
        """Full feature mode for large or high-risk changes."""
        is_security = self._is_security_heavy(text)
        return RouteDecision(
            mode="full_feature",
            enable_learning=True,
            enable_research=True,
            enable_review=True,
            enable_validation=True,
            review_strictness="strict" if is_security else "moderate",
            parallel_workers=2 if is_security else 3,
            enable_action_review=is_security,
            research_depth="deep",
            max_plan_tasks=30,
            max_retries=3,
            priority=RoutePriority.CRITICAL if is_security else RoutePriority.HIGH,
            reasoning=self._full_feature_reason(text, is_security),
        )

    def _is_full_feature(self, text: str, repo_stats: Dict[str, Any]) -> bool:
        """Check if request implies architectural or wide-ranging impact."""
        architecture_keywords = [
            "architecture", "system-wide", "system wide", "major refactor", "large refactor",
            "schema", "migration", "database", "core module", "rewrite", "re-architect",
            "security audit", "penetration", "vulnerability", "performance audit", "scalability",
            "across the codebase", "multiple modules", "many files",
        ]
        if any(keyword in text for keyword in architecture_keywords):
            return True

        # Heuristic: explicit mention of touching many files/modules
        mentions_multiple_files = " files" in text or "modules" in text or "subsystems" in text
        return mentions_multiple_files

    def _is_quick_edit(self, text: str) -> bool:
        """Check if the request is a small, localized change."""
        quick_keywords = [
            "fix", "typo", "rename", "update this", "change this", "adjust", "small tweak",
            "minor", "one file", "single file", "line", "import", "config flag",
        ]
        heavy_keywords = [
            "architecture", "schema", "system-wide", "system wide", "security", "audit",
            "refactor", "redesign", "rewrite", "migration", "large",
        ]

        mentions_file = ".py" in text or ".ts" in text or ".js" in text or ".md" in text
        looks_small = any(keyword in text for keyword in quick_keywords) or mentions_file
        looks_heavy = any(keyword in text for keyword in heavy_keywords)
        return looks_small and not looks_heavy

    def _needs_review(self, text: str) -> bool:
        """Enable review for focused features when complexity is hinted."""
        complexity_keywords = [
            "security", "auth", "authentication", "authorization", "performance", "concurrency",
            "thread", "locking", "compliance", "payment", "billing", "race condition", "data loss",
        ]
        return any(keyword in text for keyword in complexity_keywords)

    def _is_security_heavy(self, text: str) -> bool:
        """Check for security-focused tasks that require stricter handling."""
        security_keywords = [
            "security", "vulnerability", "cve", "exploit", "penetration", "threat", "audit",
            "harden", "encrypt", "xss", "csrf", "sql injection",
        ]
        return any(keyword in text for keyword in security_keywords)

    def _quick_edit_reason(self, text: str) -> str:
        if "typo" in text:
            return "Detected typo or minor wording request"
        if "import" in text:
            return "Single-file import tweak detected"
        if "." in text and (".py" in text or ".ts" in text or ".js" in text or ".md" in text):
            return "File-specific edit requested"
        return "Small, localized change"

    def _focused_feature_reason(self, text: str, enable_review: bool) -> str:
        reason = "Feature work across limited components"
        if enable_review:
            reason += " with review enabled due to complexity cues"
        return reason

    def _full_feature_reason(self, text: str, is_security: bool) -> str:
        if is_security:
            return "Security-sensitive request triggers full feature mode"
        if "architecture" in text or "system" in text:
            return "Architecture or system-wide language detected"
        if "schema" in text or "migration" in text:
            return "Schema-level change detected"
        return "Large-scale feature or refactor"


def get_default_router() -> TaskRouter:
    """Get a default task router instance."""
    return TaskRouter()
