#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Handoff Execution.

Executes handoffs between agents with contract validation.
"""

from typing import Dict, Any
from .definitions import HandoffContract
from .validation import validate_handoff


def execute_handoff(
    contract: HandoffContract,
    source_data: Dict[str, Any],
    target_agent: Any
) -> Dict[str, Any]:
    """Execute a handoff from source to target agent with validation.

    Args:
        contract: Handoff contract defining interface
        source_data: Data from source agent
        target_agent: Target agent to receive data

    Returns:
        Dictionary with:
            - success: True if handoff succeeded
            - output: Target agent output (if successful)
            - validation_errors: Input validation errors (if any)
            - output_validation_errors: Output validation errors (if any)
    """
    result = {
        "success": False,
        "validation_errors": [],
        "output_validation_errors": []
    }

    # Validate source data against input schema
    input_validation = validate_handoff(source_data, contract.input_schema)

    if not input_validation["valid"]:
        result["validation_errors"] = input_validation["errors"]
        return result

    # Execute target agent with validated data
    try:
        output = target_agent.process(source_data)
        result["output"] = output

        # Validate output if output schema exists
        if contract.output_schema:
            output_validation = validate_handoff(output, contract.output_schema)

            if not output_validation["valid"]:
                result["output_validation_errors"] = output_validation["errors"]
            else:
                result["success"] = True
        else:
            # No output schema, consider success
            result["success"] = True

    except Exception as e:
        result["execution_error"] = str(e)

    return result
