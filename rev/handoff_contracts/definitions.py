#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Handoff Contract Definitions.

Defines the structure of agent handoff contracts.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class HandoffContract:
    """Defines a contract for agent-to-agent handoffs.

    Attributes:
        name: Contract name
        input_schema: JSON schema for input data
        output_schema: Optional JSON schema for output data
        version: Contract version (for evolution tracking)
        metadata: Additional metadata (e.g., source/target agents)
    """

    name: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate contract structure after initialization."""
        if not isinstance(self.input_schema, dict):
            raise ValueError("input_schema must be a dictionary")

        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be a dictionary or None")
