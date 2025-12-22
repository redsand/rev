#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contract Registry.

Manages registered handoff contracts.
"""

from typing import Dict, List, Optional
from .definitions import HandoffContract


class ContractRegistry:
    """Registry for managing handoff contracts."""

    def __init__(self):
        """Initialize empty registry."""
        self._contracts: Dict[str, HandoffContract] = {}

    def register(self, contract: HandoffContract) -> None:
        """Register a contract.

        Args:
            contract: Contract to register
        """
        self._contracts[contract.name] = contract

    def get(self, name: str) -> Optional[HandoffContract]:
        """Get a contract by name.

        Args:
            name: Contract name

        Returns:
            Contract if found, None otherwise
        """
        return self._contracts.get(name)

    def list_all(self) -> List[HandoffContract]:
        """List all registered contracts.

        Returns:
            List of all contracts
        """
        return list(self._contracts.values())

    def get_contracts_for_agent(self, agent_name: str) -> List[HandoffContract]:
        """Get contracts relevant to a specific agent.

        Args:
            agent_name: Agent name

        Returns:
            List of contracts where agent is source or target
        """
        relevant = []

        for contract in self._contracts.values():
            metadata = contract.metadata
            source_agent = metadata.get("source_agent")
            target_agent = metadata.get("target_agent")

            if source_agent == agent_name or target_agent == agent_name:
                relevant.append(contract)

        return relevant
