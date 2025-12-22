#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bundle Validation.

Validates bundle integrity and structure.
"""

from typing import Dict, Any, List


def validate_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Validate bundle structure and integrity.

    Args:
        bundle: Bundle to validate

    Returns:
        Dictionary with:
            - valid: True if bundle is valid
            - errors: List of errors (missing required fields)
            - warnings: List of warnings (incomplete data)
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": []
    }

    # Check required top-level fields
    required_fields = ["request", "tool_calls", "llm_calls", "file_modifications", "validations"]

    for field in required_fields:
        if field not in bundle:
            result["valid"] = False
            result["errors"].append(f"Missing required field: {field}")

    # If basic structure is invalid, return early
    if not result["valid"]:
        return result

    # Check tool calls have required fields
    for i, tool_call in enumerate(bundle.get("tool_calls", [])):
        if "tool" not in tool_call:
            result["warnings"].append(f"tool_call[{i}] missing 'tool' field")

        if "params" not in tool_call:
            result["warnings"].append(f"tool_call[{i}] missing 'params' field")

        if "result" not in tool_call and "error" not in tool_call:
            result["warnings"].append(f"tool_call[{i}] missing both 'result' and 'error' fields")

    # Check LLM calls have required fields
    for i, llm_call in enumerate(bundle.get("llm_calls", [])):
        if "messages" not in llm_call:
            result["warnings"].append(f"llm_call[{i}] missing 'messages' field")

        if "response" not in llm_call:
            result["warnings"].append(f"llm_call[{i}] missing 'response' field")

    # Check file modifications have required fields
    for i, mod in enumerate(bundle.get("file_modifications", [])):
        if "file_path" not in mod:
            result["warnings"].append(f"file_modification[{i}] missing 'file_path' field")

        if "operation" not in mod:
            result["warnings"].append(f"file_modification[{i}] missing 'operation' field")

    return result
