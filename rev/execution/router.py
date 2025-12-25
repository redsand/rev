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

from rev.debug_logger import get_logger


# Route modes - different execution strategies
RouteMode = Literal["quick_edit", "focused_feature", "full_feature", "exploration"]


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
    parallel_workers: int = 1
    enable_action_review: bool = False
    research_depth: str = "medium"  # shallow, medium, deep
    validation_mode: str = "targeted"  # none, smoke, targeted, full
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
            "validation_mode": self.validation_mode,
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

        if self._is_quick_edit(text):
            decision = self._quick_edit_decision(text)
        elif self._is_exploration(text):
            decision = self._exploration_decision(text)
        elif self._is_full_feature(text, repo_stats):
            decision = self._full_feature_decision(text, repo_stats)
        elif self._is_focused_feature(text, repo_stats):
            decision = self._focused_feature_decision(text)
        else:
            decision = self._focused_feature_decision(text)

        # Log routing decision and enabled agents
        logger = get_logger()
        agents = {
            "learning": decision.enable_learning,
            "research": decision.enable_research,
            "planning": True,
            "review": decision.enable_review,
            "execution": True,
            "validation": decision.enable_validation,
        }
        logger.log("router", "ROUTE_DECISION", {
            "mode": decision.mode,
            "research_depth": decision.research_depth,
            "validation_mode": getattr(decision, "validation_mode", None),
            "agents": {k: v for k, v in agents.items() if v},
            "reason": decision.reasoning,
        }, "INFO")

        return decision

    def _quick_edit_decision(self, text: str) -> RouteDecision:
        """Quick edit mode for small, localized changes."""
        return RouteDecision(
            mode="quick_edit",
            enable_learning=False,
            enable_research=False,
            enable_review=False,
            enable_validation=True,
            review_strictness="lenient",
            parallel_workers=1,
            research_depth="off",
            validation_mode="smoke",
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
            parallel_workers=4,
            research_depth="medium",
            validation_mode="targeted",
            max_plan_tasks=20,
            max_retries=2,
            priority=RoutePriority.NORMAL,
            reasoning=self._focused_feature_reason(text, enable_review),
        )

    def _full_feature_decision(self, text: str, repo_stats: Dict[str, Any]) -> RouteDecision:
        """Full feature mode for large or high-risk changes."""
        is_security = self._is_security_heavy(text)
        has_tests = repo_stats.get("has_tests", True)
        validation_mode = "full" if has_tests else "targeted"
        return RouteDecision(
            mode="full_feature",
            enable_learning=True,
            enable_research=True,
            enable_review=True,
            enable_validation=True,
            review_strictness="strict" if is_security else "moderate",
            parallel_workers=4,
            enable_action_review=is_security,
            research_depth="deep",
            validation_mode=validation_mode,
            max_plan_tasks=30,
            max_retries=3,
            priority=RoutePriority.CRITICAL if is_security else RoutePriority.HIGH,
            reasoning=self._full_feature_reason(text, is_security),
        )

    def _exploration_decision(self, text: str) -> RouteDecision:
        """Exploration mode for learning and mapping tasks."""
        return RouteDecision(
            mode="exploration",
            enable_learning=True,
            enable_research=True,
            enable_review=False,
            enable_validation=False,
            review_strictness="lenient",
            parallel_workers=4,
            research_depth="shallow",
            validation_mode="none",
            max_plan_tasks=10,
            max_retries=1,
            priority=RoutePriority.LOW,
            reasoning="Exploratory request detected",
        )

    def _is_full_feature(self, text: str, repo_stats: Dict[str, Any]) -> bool:
        """Check if request implies architectural or wide-ranging impact."""
        architecture_keywords = [
            "architecture", "system-wide", "system wide", "major refactor", "large refactor",
            "schema", "migration", "database", "core module", "rewrite", "re-architect",
            "security audit", "penetration", "vulnerability", "performance audit", "scalability",
            "across the codebase", "multiple modules", "many files", "entire codebase",
            "all services", "all modules", "microservice", "subsystem",
        ]
        broad_scope = any(keyword in text for keyword in architecture_keywords)

        mentions_many = any(phrase in text for phrase in [
            "many files",
            "multiple modules",
            "multiple services",
            "whole project",
            "entire project",
            "across modules",
            "across services",
            "system wide",
            "system-wide",
            "large refactor",
            "entire repo",
            "across the repo",
        ])

        file_count = repo_stats.get("file_count", 0)
        has_tests = repo_stats.get("has_tests", True)
        tiny_repo = file_count and file_count <= 20
        large_repo = file_count >= 150

        if tiny_repo or not has_tests:
            return False

        if broad_scope:
            return True

        if mentions_many and (large_repo or file_count == 0):
            return True

        return False

    def _is_quick_edit(self, text: str) -> bool:
        """Check if the request is a small, localized change."""
        quick_keywords = [
            "fix", "bug", "typo", "rename", "update this", "change this", "adjust", "small tweak",
            "minor", "one file", "single file", "line", "import", "config flag", "syntax error",
            "compile error", "linter", "formatting",
        ]
        heavy_keywords = [
            "architecture", "schema", "system-wide", "system wide", "security", "audit",
            "refactor", "redesign", "rewrite", "migration", "large",
        ]

        looks_small = any(keyword in text for keyword in quick_keywords)
        looks_heavy = any(keyword in text for keyword in heavy_keywords)
        return looks_small and not looks_heavy

    def _is_focused_feature(self, text: str, repo_stats: Dict[str, Any]) -> bool:
        """Detect contained work on a specific file/module/function."""
        broad_keywords = [
            "across the codebase", "entire codebase", "system-wide", "system wide",
            "rewrite the system", "whole project", "across modules", "across services",
            "re-architect", "microservice", "subsystem",
        ]
        if any(keyword in text for keyword in broad_keywords):
            return False

        single_scope_markers = [".py", ".ts", ".js", ".md", ".json", " module", " function", " handler", " endpoint", " class "]
        focused_actions = ["add", "update", "modify", "tweak", "adjust", "extend", "write"]
        small_descriptors = ["small", "minor", "helper", "utility", "single", "one file"]

        mentions_single_scope = any(marker in text for marker in single_scope_markers)
        mentions_small = any(word in text for word in small_descriptors)
        mentions_action = any(word in text for word in focused_actions)

        if mentions_single_scope and (mentions_action or mentions_small):
            return True

        file_count = repo_stats.get("file_count", 0)
        tiny_repo = file_count and file_count <= 50
        if tiny_repo and (mentions_action or mentions_small):
            return True

        return False

    def _is_exploration(self, text: str) -> bool:
        """Detect exploration/understanding tasks without explicit edits."""
        exploration_keywords = [
            "investigate", "explore", "understand", "figure out", "learn how", "what does", "how does",
        ]
        change_keywords = ["fix", "add", "implement", "build", "rewrite", "refactor", "update", "remove", "delete", "create"]
        return any(k in text for k in exploration_keywords) and not any(k in text for k in change_keywords)

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
