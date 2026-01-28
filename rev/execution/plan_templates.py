"""
Golden-Path Plan Templates for TDD Workflow.

This module provides reusable task templates for common workflows,
particularly Test-Driven Development (TDD) patterns.

Templates define standard task sequences that have been proven to work
well for specific types of work, enabling faster and more reliable
execution by the AI agents.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from rev.models.task import Task, ExecutionPlan, RiskLevel


class TemplateCategory(Enum):
    """Categories of plan templates."""
    TDD = "tdd"  # Test-Driven Development
    DEBUG = "debug"  # Debugging workflow
    REFACTOR = "refactor"  # Code refactoring
    FEATURE = "feature"  # New feature development
    BUGFIX = "bugfix"  # Bug fix workflow
    OPTIMIZE = "optimize"  # Performance optimization


@dataclass
class PlanTemplate:
    """A reusable plan template for common workflows.

    Attributes:
        template_id: Unique identifier for the template
        name: Human-readable name
        description: Description of when to use this template
        category: Category of the template
        task_templates: List of task templates in execution order
        preconditions: Conditions that must be met before using this template
        postconditions: Expected outcomes after using this template
    """

    template_id: str
    name: str
    description: str
    category: TemplateCategory
    task_templates: List[Dict[str, Any]] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def apply(self, plan: ExecutionPlan, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """Apply this template to an execution plan.

        Args:
            plan: The execution plan to modify
            context: Optional context variables for template substitution

        Returns:
            The modified execution plan
        """
        ctx = context or {}

        for template in self.task_templates:
            # Substitute context variables in task description
            description = template["description"]
            for key, value in ctx.items():
                description = description.replace(f"{{{key}}}", str(value))

            # Create task from template
            task = plan.add_task(
                description=description,
                action_type=template.get("action_type", "general"),
                dependencies=template.get("dependencies", []),
            )

            # Set additional properties
            if "risk_level" in template:
                task.risk_level = RiskLevel(template["risk_level"])
            if "priority" in template:
                task.priority = template["priority"]

        return plan

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "task_templates": self.task_templates,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "metadata": self.metadata,
        }


class TemplateRegistry:
    """Registry for managing plan templates."""

    def __init__(self):
        """Initialize TemplateRegistry with default templates."""
        self._templates: Dict[str, PlanTemplate] = {}
        self._register_default_templates()

    def _register_default_templates(self) -> None:
        """Register the default golden-path templates."""
        # TDD Template
        self.register(PlanTemplate(
            template_id="tdd_basic",
            name="Basic TDD",
            description="Standard Test-Driven Development workflow",
            category=TemplateCategory.TDD,
            task_templates=[
                {
                    "description": "Write failing test for {feature}",
                    "action_type": "test",
                    "risk_level": "low",
                },
                {
                    "description": "Implement minimal code to make test pass",
                    "action_type": "edit",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Run tests to verify implementation",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [1],
                },
                {
                    "description": "Refactor code while keeping tests green",
                    "action_type": "refactor",
                    "risk_level": "medium",
                    "dependencies": [2],
                },
            ],
            preconditions=[
                "Feature requirements are clearly defined",
                "Test framework is available",
            ],
            postconditions=[
                "Feature is implemented with tests",
                "All tests pass",
                "Code is clean and maintainable",
            ],
        ))

        # Debug Template
        self.register(PlanTemplate(
            template_id="debug_basic",
            name="Basic Debugging",
            description="Standard debugging workflow for fixing issues",
            category=TemplateCategory.DEBUG,
            task_templates=[
                {
                    "description": "Reproduce the issue",
                    "action_type": "research",
                    "risk_level": "low",
                },
                {
                    "description": "Identify root cause of the issue",
                    "action_type": "debug",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Implement fix for the issue",
                    "action_type": "edit",
                    "risk_level": "medium",
                    "dependencies": [1],
                },
                {
                    "description": "Test the fix",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [2],
                },
                {
                    "description": "Verify no regressions were introduced",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [3],
                },
            ],
            preconditions=[
                "Issue can be reproduced",
                "Error message or symptoms are known",
            ],
            postconditions=[
                "Issue is fixed",
                "Fix is tested",
                "No regressions were introduced",
            ],
        ))

        # Refactor Template
        self.register(PlanTemplate(
            template_id="refactor_safe",
            name="Safe Refactoring",
            description="Safe refactoring workflow with test coverage",
            category=TemplateCategory.REFACTOR,
            task_templates=[
                {
                    "description": "Analyze existing code structure",
                    "action_type": "research",
                    "risk_level": "low",
                },
                {
                    "description": "Write tests for existing behavior",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Refactor code while maintaining behavior",
                    "action_type": "refactor",
                    "risk_level": "medium",
                    "dependencies": [1],
                },
                {
                    "description": "Run tests to verify refactoring didn't break anything",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [2],
                },
            ],
            preconditions=[
                "Code to refactor exists",
                "Test framework is available",
            ],
            postconditions=[
                "Code is refactored",
                "Behavior is preserved",
                "All tests pass",
            ],
        ))

        # Feature Template
        self.register(PlanTemplate(
            template_id="feature_tdd",
            name="Feature Development with TDD",
            description="New feature development using TDD",
            category=TemplateCategory.FEATURE,
            task_templates=[
                {
                    "description": "Research and understand requirements for {feature}",
                    "action_type": "research",
                    "risk_level": "low",
                },
                {
                    "description": "Write failing tests for {feature}",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Implement minimal feature code",
                    "action_type": "edit",
                    "risk_level": "medium",
                    "dependencies": [1],
                },
                {
                    "description": "Run tests and verify implementation",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [2],
                },
                {
                    "description": "Write documentation for {feature}",
                    "action_type": "edit",
                    "risk_level": "low",
                    "dependencies": [3],
                },
                {
                    "description": "Perform final validation and testing",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [4],
                },
            ],
            preconditions=[
                "Feature requirements are documented",
                "Test framework is available",
            ],
            postconditions=[
                "Feature is implemented",
                "Tests are written and passing",
                "Documentation is complete",
            ],
        ))

        # Bugfix Template
        self.register(PlanTemplate(
            template_id="bugfix_tdd",
            name="Bug Fix with TDD",
            description="Bug fix workflow using TDD principles",
            category=TemplateCategory.BUGFIX,
            task_templates=[
                {
                    "description": "Understand the bug and its impact",
                    "action_type": "research",
                    "risk_level": "low",
                },
                {
                    "description": "Write a test that reproduces the bug",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Implement fix for the bug",
                    "action_type": "edit",
                    "risk_level": "medium",
                    "dependencies": [1],
                },
                {
                    "description": "Run tests to verify fix",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [2],
                },
                {
                    "description": "Verify no regressions were introduced",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [3],
                },
            ],
            preconditions=[
                "Bug is reproducible",
                "Test framework is available",
            ],
            postconditions=[
                "Bug is fixed",
                "Test case exists for the bug",
                "No regressions were introduced",
            ],
        ))

        # Optimize Template
        self.register(PlanTemplate(
            template_id="optimize_safe",
            name="Safe Performance Optimization",
            description="Performance optimization with test safety",
            category=TemplateCategory.OPTIMIZE,
            task_templates=[
                {
                    "description": "Profile and identify performance bottlenecks",
                    "action_type": "research",
                    "risk_level": "low",
                },
                {
                    "description": "Write performance tests for baseline",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [0],
                },
                {
                    "description": "Implement performance optimization",
                    "action_type": "edit",
                    "risk_level": "medium",
                    "dependencies": [1],
                },
                {
                    "description": "Verify performance improvement",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [2],
                },
                {
                    "description": "Run full test suite to ensure no regressions",
                    "action_type": "test",
                    "risk_level": "low",
                    "dependencies": [3],
                },
            ],
            preconditions=[
                "Performance issue is identified",
                "Performance measurement tools are available",
            ],
            postconditions=[
                "Performance is improved",
                "Tests are updated",
                "No functionality was broken",
            ],
        ))

    def register(self, template: PlanTemplate) -> None:
        """Register a new template.

        Args:
            template: The template to register
        """
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> Optional[PlanTemplate]:
        """Get a template by ID.

        Args:
            template_id: The ID of the template to retrieve

        Returns:
            The template if found, None otherwise
        """
        return self._templates.get(template_id)

    def get_by_category(self, category: TemplateCategory) -> List[PlanTemplate]:
        """Get all templates in a category.

        Args:
            category: The category to filter by

        Returns:
            List of templates in the category
        """
        return [
            template for template in self._templates.values()
            if template.category == category
        ]

    def list_templates(self) -> List[PlanTemplate]:
        """Get all registered templates.

        Returns:
            List of all templates
        """
        return list(self._templates.values())

    def apply_template(
        self,
        template_id: str,
        plan: ExecutionPlan,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ExecutionPlan]:
        """Apply a template to an execution plan.

        Args:
            template_id: The ID of the template to apply
            plan: The execution plan to modify
            context: Optional context variables for template substitution

        Returns:
            The modified execution plan, or None if template not found
        """
        template = self.get(template_id)
        if template is None:
            return None
        return template.apply(plan, context)

    def suggest_template(
        self,
        description: str,
        category: Optional[TemplateCategory] = None
    ) -> Optional[PlanTemplate]:
        """Suggest a template based on description.

        Args:
            description: Description of the work to be done
            category: Optional category to filter by

        Returns:
            The suggested template, or None if no match found
        """
        candidates = self.list_templates()
        if category:
            candidates = self.get_by_category(category)

        description_lower = description.lower()

        # Simple keyword matching for template suggestion
        for template in candidates:
            for keyword in _get_template_keywords(template.template_id):
                if keyword in description_lower:
                    return template

        # Default: return first template if no keyword match
        return candidates[0] if candidates else None


def _get_template_keywords(template_id: str) -> List[str]:
    """Get keywords for template matching.

    Args:
        template_id: The template ID

    Returns:
        List of keywords associated with the template
    """
    keyword_map = {
        "tdd_basic": ["test", "tdd", "test-driven"],
        "debug_basic": ["debug", "bug", "error", "fix", "issue"],
        "refactor_safe": ["refactor", "cleanup", "restructure"],
        "feature_tdd": ["feature", "new", "implement"],
        "bugfix_tdd": ["bug", "fix", "issue", "defect"],
        "optimize_safe": ["optimize", "performance", "fast"],
    }
    return keyword_map.get(template_id, [])


# Global registry instance
_registry: Optional[TemplateRegistry] = None


def get_template_registry() -> TemplateRegistry:
    """Get the global template registry.

    Returns:
        The global TemplateRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
    return _registry


def apply_template(
    template_id: str,
    plan: ExecutionPlan,
    context: Optional[Dict[str, Any]] = None
) -> Optional[ExecutionPlan]:
    """Convenience function to apply a template to a plan.

    Args:
        template_id: The ID of the template to apply
        plan: The execution plan to modify
        context: Optional context variables for template substitution

    Returns:
        The modified execution plan, or None if template not found
    """
    return get_template_registry().apply_template(template_id, plan, context)


def suggest_template(
    description: str,
    category: Optional[TemplateCategory] = None
) -> Optional[PlanTemplate]:
    """Convenience function to suggest a template.

    Args:
        description: Description of the work to be done
        category: Optional category to filter by

    Returns:
        The suggested template, or None if no match found
    """
    return get_template_registry().suggest_template(description, category)