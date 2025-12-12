#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for TaskRouter heuristics."""

import unittest

from rev.execution.router import TaskRouter


class TestTaskRouter(unittest.TestCase):
    """Heuristic coverage for TaskRouter.route."""

    def setUp(self):
        self.router = TaskRouter()

    def test_focus_mode_for_targeted_file_change(self):
        decision = self.router.route(
            "In parser/utils.py, add a small helper to normalize data",
            repo_stats={"file_count": 120, "has_tests": True},
        )
        self.assertEqual(decision.mode, "focused_feature")
        self.assertTrue(decision.enable_research)
        self.assertEqual(decision.research_depth, "medium")
        self.assertTrue(decision.enable_validation)

    def test_full_feature_for_repo_wide_rewrite(self):
        decision = self.router.route(
            "Rewrite config system in entire repo for multi-service rollout",
            repo_stats={"file_count": 300, "has_tests": True},
        )
        self.assertEqual(decision.mode, "full_feature")
        self.assertEqual(decision.validation_mode, "full")

    def test_quick_edit_for_typo(self):
        decision = self.router.route(
            "Fix typo in README",
            repo_stats={"file_count": 10, "has_tests": False},
        )
        self.assertEqual(decision.mode, "quick_edit")
        self.assertFalse(decision.enable_research)

    def test_exploration_for_investigation(self):
        decision = self.router.route(
            "Investigate how module Y works",
            repo_stats={"file_count": 80, "has_tests": True},
        )
        self.assertEqual(decision.mode, "exploration")
        self.assertTrue(decision.enable_research)
        self.assertFalse(decision.enable_validation)

    def test_avoid_full_feature_for_tiny_repo_without_tests(self):
        decision = self.router.route(
            "Rewrite config system in entire repo",
            repo_stats={"file_count": 12, "has_tests": False},
        )
        self.assertNotEqual(decision.mode, "full_feature")


if __name__ == "__main__":
    unittest.main()
