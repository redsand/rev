#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mutant Generator.

Generates plausible incorrect implementations (mutants) to test against.
"""

from typing import List, Dict, Any
import re


def generate_mutants(original_code: str) -> List[Dict[str, Any]]:
    """Generate mutant versions of code (plausible incorrect implementations).

    Args:
        original_code: Original function code

    Returns:
        List of mutant dictionaries with:
            - code: Mutated code
            - description: Description of mutation
            - mutation_type: Type of mutation applied
    """
    mutants = []

    # Mutation 1: Off-by-one errors
    if "-" in original_code or "+" in original_code:
        # Replace "- 1" with nothing
        mutant_code = re.sub(r'-\s*1\b', '', original_code)
        if mutant_code != original_code:
            mutants.append({
                "code": mutant_code,
                "description": "Off-by-one error: removed -1",
                "mutation_type": "off_by_one"
            })

        # Replace "+ 1" with nothing
        mutant_code = re.sub(r'\+\s*1\b', '', original_code)
        if mutant_code != original_code:
            mutants.append({
                "code": mutant_code,
                "description": "Off-by-one error: removed +1",
                "mutation_type": "off_by_one"
            })

    # Mutation 2: Boundary condition changes
    # Change <= to <
    if "<=" in original_code:
        mutant_code = original_code.replace("<=", "<")
        mutants.append({
            "code": mutant_code,
            "description": "Boundary condition error: <= changed to <",
            "mutation_type": "boundary"
        })

    # Change >= to >
    if ">=" in original_code:
        mutant_code = original_code.replace(">=", ">")
        mutants.append({
            "code": mutant_code,
            "description": "Boundary condition error: >= changed to >",
            "mutation_type": "boundary"
        })

    # Change < to <=
    if "<" in original_code and "<=" not in original_code:
        mutant_code = original_code.replace("<", "<=")
        mutants.append({
            "code": mutant_code,
            "description": "Boundary condition error: < changed to <=",
            "mutation_type": "boundary"
        })

    # Mutation 3: Return value changes
    # Change "return True" to "return False"
    if "return True" in original_code:
        mutant_code = original_code.replace("return True", "return False")
        mutants.append({
            "code": mutant_code,
            "description": "Return value inversion: True to False",
            "mutation_type": "return_value"
        })

    # Change "return False" to "return True"
    if "return False" in original_code:
        mutant_code = original_code.replace("return False", "return True")
        mutants.append({
            "code": mutant_code,
            "description": "Return value inversion: False to True",
            "mutation_type": "return_value"
        })

    # Mutation 4: Loop condition changes
    # Change "range(2, n)" to "range(1, n)"
    if "range(2," in original_code:
        mutant_code = original_code.replace("range(2,", "range(1,")
        mutants.append({
            "code": mutant_code,
            "description": "Loop start error: range(2,...) to range(1,...)",
            "mutation_type": "loop_condition"
        })

    # Mutation 5: Missing edge case handling
    # Remove "if n <= 1:" check
    if "if n <= 1:" in original_code or "if n < 1:" in original_code:
        lines = original_code.split("\n")
        mutant_lines = []
        skip_next = False
        for line in lines:
            if "if n <= 1:" in line or "if n < 1:" in line:
                skip_next = True
                continue
            if skip_next and line.strip().startswith("return"):
                skip_next = False
                continue
            mutant_lines.append(line)

        mutant_code = "\n".join(mutant_lines)
        if mutant_code != original_code:
            mutants.append({
                "code": mutant_code,
                "description": "Missing edge case: removed n<=1 check",
                "mutation_type": "missing_edge_case"
            })

    return mutants
