#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Typed Agent Handoff Contracts.

Defines interfaces between agents with type-safe validation.
"""

from .definitions import HandoffContract
from .validation import validate_handoff
from .handoff import execute_handoff
from .registry import ContractRegistry
from .evolution import is_backward_compatible

__all__ = [
    "HandoffContract",
    "validate_handoff",
    "execute_handoff",
    "ContractRegistry",
    "is_backward_compatible",
]
