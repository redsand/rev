#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contract Evolution.

Handles contract versioning and backward compatibility.
"""

from typing import Set
from .definitions import HandoffContract


def is_backward_compatible(old_contract: HandoffContract, new_contract: HandoffContract) -> bool:
    """Check if new contract is backward compatible with old contract.

    A contract is backward compatible if:
    - All previously required fields are still required
    - No new required fields are added to input schema
    - Field types remain the same

    Args:
        old_contract: Old contract version
        new_contract: New contract version

    Returns:
        True if backward compatible
    """
    # Get required fields from both versions
    old_required = set(old_contract.input_schema.get("required", []))
    new_required = set(new_contract.input_schema.get("required", []))

    # Check that no previously required fields are removed
    if not old_required.issubset(new_required):
        return False

    # Check that no NEW required fields are added
    # (adding optional fields is OK, adding required fields breaks compatibility)
    if new_required - old_required:
        return False

    # Check that types of existing fields haven't changed
    old_props = old_contract.input_schema.get("properties", {})
    new_props = new_contract.input_schema.get("properties", {})

    for field_name, old_field_schema in old_props.items():
        if field_name in new_props:
            new_field_schema = new_props[field_name]

            # Type must remain the same
            if old_field_schema.get("type") != new_field_schema.get("type"):
                return False

    return True
