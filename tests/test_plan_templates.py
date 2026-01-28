#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Golden-Path Plan Templates functionality.

Tests the plan templates module that provides reusable templates
for common workflows like TDD, debugging, and refactoring.
"""

import unittest
from rev.execution.plan_templates import (
    TemplateCategory,
    PlanTemplate,
    TemplateRegistry,
    _get_template_keywords,
    get_template_registry,
    apply_template,
    suggest_template,
)
from rev.models.task import ExecutionPlan, TaskStatus


class TestTemplateCategory(unittest.TestCase):
    """Test TemplateCategory enum."""

    def test_category_values(self):
        """TemplateCategory enum should have correct values."""
        self.assertEqual(TemplateCategory.TDD.value, "tdd")
        self.assertEqual(TemplateCategory.DEBUG.value, "debug")
        self.assertEqual(TemplateCategory.REFACTOR.value, "refactor")
        self.assertEqual(TemplateCategory.FEATURE.value, "feature")
        self.assertEqual(TemplateCategory.BUGFIX.value, "bugfix")
        self.assertEqual(TemplateCategory.OPTIMIZE.value, "optimize")


class TestPlanTemplate(unittest.TestCase):
    """Test PlanTemplate dataclass."""

    def test_plan_template_creation(self):
        """PlanTemplate should be created with correct attributes."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
        )

        self.assertEqual(template.template_id, "test_template")
        self.assertEqual(template.name, "Test Template")
        self.assertEqual(template.description, "A test template")
        self.assertEqual(template.category, TemplateCategory.TDD)

    def test_plan_template_with_task_templates(self):
        """PlanTemplate should store task templates."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Task 1", "action_type": "test"},
                {"description": "Task 2", "action_type": "edit"},
            ],
        )

        self.assertEqual(len(template.task_templates), 2)
        self.assertEqual(template.task_templates[0]["description"], "Task 1")

    def test_plan_template_to_dict(self):
        """PlanTemplate.to_dict should return correct dictionary."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Task 1", "action_type": "test"},
            ],
        )

        template_dict = template.to_dict()

        self.assertEqual(template_dict["template_id"], "test_template")
        self.assertEqual(template_dict["name"], "Test Template")
        self.assertEqual(template_dict["category"], "tdd")
        self.assertEqual(len(template_dict["task_templates"]), 1)

    def test_plan_template_apply(self):
        """PlanTemplate.apply should add tasks to a plan."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Task 1", "action_type": "test"},
                {"description": "Task 2", "action_type": "edit"},
            ],
        )

        plan = ExecutionPlan()
        template.apply(plan)

        self.assertEqual(len(plan.tasks), 2)
        self.assertEqual(plan.tasks[0].description, "Task 1")
        self.assertEqual(plan.tasks[1].description, "Task 2")

    def test_plan_template_apply_with_context(self):
        """PlanTemplate.apply should substitute context variables."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Implement {feature}", "action_type": "edit"},
                {"description": "Test {feature}", "action_type": "test"},
            ],
        )

        plan = ExecutionPlan()
        template.apply(plan, context={"feature": "authentication"})

        self.assertEqual(len(plan.tasks), 2)
        self.assertEqual(plan.tasks[0].description, "Implement authentication")
        self.assertEqual(plan.tasks[1].description, "Test authentication")

    def test_plan_template_apply_with_dependencies(self):
        """PlanTemplate.apply should set task dependencies."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Task 1", "action_type": "test"},
                {"description": "Task 2", "action_type": "edit", "dependencies": [0]},
                {"description": "Task 3", "action_type": "test", "dependencies": [1]},
            ],
        )

        plan = ExecutionPlan()
        template.apply(plan)

        self.assertEqual(len(plan.tasks), 3)
        self.assertEqual(plan.tasks[0].dependencies, [])
        self.assertEqual(plan.tasks[1].dependencies, [0])
        self.assertEqual(plan.tasks[2].dependencies, [1])

    def test_plan_template_apply_to_existing_plan(self):
        """PlanTemplate.apply should work with existing plans."""
        template = PlanTemplate(
            template_id="test_template",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.TDD,
            task_templates=[
                {"description": "Template Task", "action_type": "test"},
            ],
        )

        plan = ExecutionPlan()
        plan.add_task("Existing Task")

        template.apply(plan)

        self.assertEqual(len(plan.tasks), 2)
        self.assertEqual(plan.tasks[0].description, "Existing Task")
        self.assertEqual(plan.tasks[1].description, "Template Task")


class TestTemplateRegistry(unittest.TestCase):
    """Test TemplateRegistry class."""

    def test_registry_initialization(self):
        """TemplateRegistry should initialize with default templates."""
        registry = TemplateRegistry()

        self.assertGreater(len(registry._templates), 0)

    def test_registry_register(self):
        """TemplateRegistry.register should add a template."""
        registry = TemplateRegistry()

        template = PlanTemplate(
            template_id="custom_template",
            name="Custom Template",
            description="A custom template",
            category=TemplateCategory.TDD,
        )

        registry.register(template)

        self.assertIsNotNone(registry.get("custom_template"))
        self.assertEqual(registry.get("custom_template").name, "Custom Template")

    def test_registry_get_existing(self):
        """TemplateRegistry.get should return template if it exists."""
        registry = TemplateRegistry()

        template = registry.get("tdd_basic")

        self.assertIsNotNone(template)
        self.assertEqual(template.template_id, "tdd_basic")

    def test_registry_get_nonexistent(self):
        """TemplateRegistry.get should return None for nonexistent template."""
        registry = TemplateRegistry()

        template = registry.get("nonexistent_template")

        self.assertIsNone(template)

    def test_registry_get_by_category(self):
        """TemplateRegistry.get_by_category should filter by category."""
        registry = TemplateRegistry()

        tdd_templates = registry.get_by_category(TemplateCategory.TDD)

        self.assertGreater(len(tdd_templates), 0)
        for template in tdd_templates:
            self.assertEqual(template.category, TemplateCategory.TDD)

    def test_registry_list_templates(self):
        """TemplateRegistry.list_templates should return all templates."""
        registry = TemplateRegistry()

        templates = registry.list_templates()

        self.assertGreater(len(templates), 0)
        self.assertIsInstance(templates, list)

    def test_registry_apply_template_existing(self):
        """TemplateRegistry.apply_template should apply existing template."""
        registry = TemplateRegistry()

        plan = ExecutionPlan()
        result = registry.apply_template("tdd_basic", plan)

        self.assertIsNotNone(result)
        self.assertGreater(len(result.tasks), 0)

    def test_registry_apply_template_with_context(self):
        """TemplateRegistry.apply_template should use context variables."""
        registry = TemplateRegistry()

        plan = ExecutionPlan()
        result = registry.apply_template("feature_tdd", plan, context={"feature": "login"})

        self.assertIsNotNone(result)
        # Check that feature name was substituted
        self.assertIn("login", result.tasks[1].description)

    def test_registry_apply_template_nonexistent(self):
        """TemplateRegistry.apply_template should return None for nonexistent template."""
        registry = TemplateRegistry()

        plan = ExecutionPlan()
        result = registry.apply_template("nonexistent_template", plan)

        self.assertIsNone(result)

    def test_registry_suggest_template_by_keyword(self):
        """TemplateRegistry.suggest_template should match keywords."""
        registry = TemplateRegistry()

        template = registry.suggest_template("Write tests for the login feature")

        self.assertIsNotNone(template)

    def test_registry_suggest_template_by_category(self):
        """TemplateRegistry.suggest_template should filter by category."""
        registry = TemplateRegistry()

        template = registry.suggest_template("something", category=TemplateCategory.TDD)

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.TDD)

    def test_registry_suggest_template_no_match(self):
        """TemplateRegistry.suggest_template should return first template if no match."""
        registry = TemplateRegistry()

        template = registry.suggest_template("xyzzy plugh")

        # Should return some template (first in list)
        self.assertIsNotNone(template)


class TestDefaultTemplates(unittest.TestCase):
    """Test default template implementations."""

    def setUp(self):
        """Set up test registry."""
        self.registry = TemplateRegistry()

    def test_tdd_basic_template_exists(self):
        """TDD basic template should exist with correct structure."""
        template = self.registry.get("tdd_basic")

        self.assertIsNotNone(template)
        self.assertEqual(template.template_id, "tdd_basic")
        self.assertEqual(template.category, TemplateCategory.TDD)
        self.assertGreater(len(template.task_templates), 0)

    def test_tdd_basic_template_has_test_task(self):
        """TDD basic template should start with a test task."""
        template = self.registry.get("tdd_basic")

        self.assertEqual(template.task_templates[0]["action_type"], "test")

    def test_tdd_basic_template_apply(self):
        """TDD basic template should apply correctly."""
        template = self.registry.get("tdd_basic")
        plan = ExecutionPlan()

        template.apply(plan, context={"feature": "new feature"})

        self.assertGreater(len(plan.tasks), 0)
        # First task should be a test
        self.assertEqual(plan.tasks[0].action_type, "test")

    def test_debug_basic_template_exists(self):
        """Debug basic template should exist."""
        template = self.registry.get("debug_basic")

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.DEBUG)

    def test_refactor_safe_template_exists(self):
        """Refactor safe template should exist."""
        template = self.registry.get("refactor_safe")

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.REFACTOR)

    def test_feature_tdd_template_exists(self):
        """Feature TDD template should exist."""
        template = self.registry.get("feature_tdd")

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.FEATURE)

    def test_bugfix_tdd_template_exists(self):
        """Bugfix TDD template should exist."""
        template = self.registry.get("bugfix_tdd")

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.BUGFIX)

    def test_optimize_safe_template_exists(self):
        """Optimize safe template should exist."""
        template = self.registry.get("optimize_safe")

        self.assertIsNotNone(template)
        self.assertEqual(template.category, TemplateCategory.OPTIMIZE)


class TestGetTemplateKeywords(unittest.TestCase):
    """Test _get_template_keywords helper function."""

    def test_get_template_keywords_tdd(self):
        """TDD template should have correct keywords."""
        keywords = _get_template_keywords("tdd_basic")

        self.assertIn("test", keywords)
        self.assertIn("tdd", keywords)
        self.assertIn("test-driven", keywords)

    def test_get_template_keywords_debug(self):
        """Debug template should have correct keywords."""
        keywords = _get_template_keywords("debug_basic")

        self.assertIn("debug", keywords)
        self.assertIn("bug", keywords)
        self.assertIn("fix", keywords)

    def test_get_template_keywords_refactor(self):
        """Refactor template should have correct keywords."""
        keywords = _get_template_keywords("refactor_safe")

        self.assertIn("refactor", keywords)
        self.assertIn("cleanup", keywords)

    def test_get_template_keywords_unknown(self):
        """Unknown template should return empty list."""
        keywords = _get_template_keywords("unknown_template")

        self.assertEqual(keywords, [])


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions."""

    def test_get_template_registry_singleton(self):
        """get_template_registry should return singleton."""
        registry1 = get_template_registry()
        registry2 = get_template_registry()

        self.assertIs(registry1, registry2)

    def test_apply_template_convenience(self):
        """apply_template function should work correctly."""
        plan = ExecutionPlan()
        result = apply_template("tdd_basic", plan, context={"feature": "test"})

        self.assertIsNotNone(result)
        self.assertGreater(len(result.tasks), 0)

    def test_suggest_template_convenience(self):
        """suggest_template function should work correctly."""
        template = suggest_template("Write tests for authentication")

        self.assertIsNotNone(template)


if __name__ == "__main__":
    unittest.main()