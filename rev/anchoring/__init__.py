#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anchoring Score Instrumentation (UCCT-inspired).

Provides a scalar metric (0-1) representing confidence in current state.
Based on:
- Evidence density: How much evidence has been gathered
- Mismatch risk: Uncertainty or conflicting information
- Budget usage: Computational budget consumed

This score influences debate contentiousness.
"""

from .evidence_density import calculate_evidence_density
from .mismatch_risk import calculate_mismatch_risk
from .budget_usage import calculate_budget_usage
from .score import calculate_anchoring_score
from .tracker import update_anchoring_score

__all__ = [
    "calculate_evidence_density",
    "calculate_mismatch_risk",
    "calculate_budget_usage",
    "calculate_anchoring_score",
    "update_anchoring_score",
]
