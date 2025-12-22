#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anchoring Score Tracker.

Updates and tracks anchoring score in execution context over time.
"""

from typing import Any
from .score import calculate_anchoring_score


def update_anchoring_score(context: Any) -> None:
    """Update the anchoring score in context.

    Calculates the current anchoring score and stores it in context.anchoring_score.

    Args:
        context: Execution context to update
    """
    score = calculate_anchoring_score(context)
    context.anchoring_score = score
