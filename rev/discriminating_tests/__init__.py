#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discriminating-Tests Generator.

Generates tests that discriminate between correct and incorrect implementations.
This helps verify that tests actually test the right behavior and catch edge cases.
"""

from .generator import generate_test_cases
from .edge_cases import detect_edge_cases
from .mutants import generate_mutants
from .validator import validate_discriminating_test
from .coverage import identify_untested_paths, calculate_branch_coverage

__all__ = [
    "generate_test_cases",
    "detect_edge_cases",
    "generate_mutants",
    "validate_discriminating_test",
    "identify_untested_paths",
    "calculate_branch_coverage",
]
