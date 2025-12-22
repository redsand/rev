#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Handoff Contract Validation.

Validates data against JSON schemas.
"""

from typing import Dict, Any, List


def validate_handoff(data: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Validate data against a JSON schema.

    Args:
        data: Data to validate
        schema: JSON schema

    Returns:
        Dictionary with:
            - valid: True if data is valid
            - errors: List of validation errors
    """
    errors = []

    # Validate type
    expected_type = schema.get("type")
    if expected_type:
        if not _validate_type(data, expected_type):
            errors.append(f"Expected type '{expected_type}', got '{type(data).__name__}'")
            return {"valid": False, "errors": errors}

    # Validate object properties
    if expected_type == "object":
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        # Check required fields
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: '{field}'")

        # Validate each property
        for prop_name, prop_schema in properties.items():
            if prop_name in data:
                prop_result = validate_handoff(data[prop_name], prop_schema)
                if not prop_result["valid"]:
                    for err in prop_result["errors"]:
                        errors.append(f"Field '{prop_name}': {err}")

    # Validate array items
    elif expected_type == "array":
        if isinstance(data, list):
            item_schema = schema.get("items")
            if item_schema:
                for i, item in enumerate(data):
                    item_result = validate_handoff(item, item_schema)
                    if not item_result["valid"]:
                        for err in item_result["errors"]:
                            errors.append(f"Array item [{i}]: {err}")

    # Validate number constraints
    elif expected_type == "number" or expected_type == "integer":
        if isinstance(data, (int, float)):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")

            if minimum is not None and data < minimum:
                errors.append(f"Value {data} is less than minimum {minimum}")

            if maximum is not None and data > maximum:
                errors.append(f"Value {data} is greater than maximum {maximum}")

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def _validate_type(data: Any, expected_type: str) -> bool:
    """Check if data matches expected JSON schema type.

    Args:
        data: Data to check
        expected_type: Expected type string

    Returns:
        True if type matches
    """
    if expected_type == "object":
        return isinstance(data, dict)
    elif expected_type == "array":
        return isinstance(data, list)
    elif expected_type == "string":
        return isinstance(data, str)
    elif expected_type == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    elif expected_type == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    elif expected_type == "boolean":
        return isinstance(data, bool)
    elif expected_type == "null":
        return data is None

    return False
