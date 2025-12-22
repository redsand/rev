#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debate mode for behavior-modulated agent collaboration (MACI).

This module implements a debate system where:
- Proposer suggests solutions with explicit assumptions
- Skeptic challenges with evidence requests
- Judge evaluates and makes final decisions
- Contentiousness is automatically modulated based on anchoring score
"""

from .proposer import ProposerAgent
from .skeptic import SkepticAgent
from .judge import JudgeAgent
from .controller import DebateController

__all__ = [
    "ProposerAgent",
    "SkepticAgent",
    "JudgeAgent",
    "DebateController",
]
