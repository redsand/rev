#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Code refactoring and optimization utilities."""

import json
import re
import shlex
from typing import List, Dict, Any

from rev import config
from rev.tools.utils import _safe_path, _run_shell, quote_cmd_arg


def remove_unused_imports(file_path: str, language: str = "python") -> str:
    """Remove unused imports from a code file.

    Args:
        file_path: Path to code file
        language: Programming language (python, javascript, typescript)

    Returns:
        JSON string with result
    """
    try:
        file = _safe_path(file_path)
        if not file.exists():
            return json.dumps({"file": file_path, "error": f"File not found: {file_path}"})

        if language.lower() == "python":
            # Use autoflake if available
            try:
                result = _run_shell(f"autoflake --remove-all-unused-imports --in-place {quote_cmd_arg(str(file))}")
                if result.returncode == 0:
                    # Invalidate cache for the modified file
                    from rev.cache import get_file_cache
                    file_cache = get_file_cache()
                    if file_cache is not None:
                        file_cache.invalidate_file(file)

                    return json.dumps({
                        "file": str(file),
                        "refactored": file.relative_to(config.ROOT).as_posix(),
                        "removed": "unused imports",
                        "language": "Python",
                        "tool": "autoflake"
                    })
                else:
                    return json.dumps({
                        "file": str(file),
                        "language": "python",
                        "tool": "autoflake",
                        "error": "autoflake not installed or failed. Run: pip install autoflake"
                    })
            except Exception:
                return json.dumps({
                    "file": str(file),
                    "language": "python",
                    "tool": "autoflake",
                    "error": "autoflake not installed. Run: pip install autoflake"
                })

        else:
            return json.dumps({
                "file": str(file),
                "language": language,
                "tool": "unknown",
                "error": f"Language '{language}' not supported yet"
            })

    except Exception as e:
        return json.dumps({
            "file": file_path,
            "language": language,
            "tool": "unknown",
            "error": f"Refactoring failed: {type(e).__name__}: {e}"
        })


def extract_constants(file_path: str, threshold: int = 3) -> str:
    """Identify magic numbers/strings that should be constants.

    Args:
        file_path: Path to code file
        threshold: Minimum occurrences to suggest extraction

    Returns:
        JSON string with suggestions
    """
    try:
        file = _safe_path(file_path)
        if not file.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        content = file.read_text(encoding='utf-8', errors='ignore')

        # Find magic numbers: integers (decimal, hex, octal), floats, negatives
        # Matches: -123, 3.14159, 0xFF, 0o777, 999, etc.
        magic_numbers = re.findall(r'-?\b(?:0x[0-9a-fA-F]+|0o[0-7]+|\d+\.?\d*)\b', content)
        number_counts: Dict[str, int] = {}
        for num in magic_numbers:
            if num not in ['00', '01', '10', '100']:
                number_counts[num] = number_counts.get(num, 0) + 1

        # Find magic strings (quoted strings used multiple times)
        magic_strings = re.findall(r'["\']([^"\']{4,})["\']', content)
        string_counts: Dict[str, int] = {}
        for s in magic_strings:
            if not s.startswith('import ') and not s.startswith('from '):
                string_counts[s] = string_counts.get(s, 0) + 1

        suggestions: List[Dict[str, Any]] = []

        # Suggest constants for repeated numbers
        for num, count in number_counts.items():
            if count >= threshold:
                const_name = f"CONSTANT_{num}"
                suggestions.append({
                    "type": "number",
                    "value": num,
                    "occurrences": count,
                    "suggested_name": const_name
                })

        # Suggest constants for repeated strings
        for string, count in string_counts.items():
            if count >= threshold:
                const_name = string.upper().replace(' ', '_')[:30]
                suggestions.append({
                    "type": "string",
                    "value": string,
                    "occurrences": count,
                    "suggested_name": const_name
                })

        return json.dumps({
            "file": str(file),
            "refactored": file.relative_to(config.ROOT).as_posix(),
            "suggestions": suggestions,
            "count": len(suggestions)
        })

    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {type(e).__name__}: {e}"})


def simplify_conditionals(file_path: str) -> str:
    """Identify complex conditionals that could be simplified.

    Args:
        file_path: Path to code file

    Returns:
        JSON string with suggestions
    """
    try:
        file = _safe_path(file_path)
        if not file.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        content = file.read_text(encoding='utf-8', errors='ignore')
        lines = content.split('\n')

        suggestions: List[Dict[str, Any]] = []

        # Find complex if statements
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Check for multiple conditions
            if stripped.startswith('if ') or stripped.startswith('elif '):
                and_count = line.count(' and ')
                or_count = line.count(' or ')
                paren_depth = line.count('(') - line.count(')')

                if and_count + or_count >= 3 or paren_depth >= 2:
                    suggestions.append({
                        "line": i,
                        "issue": "Complex conditional",
                        "complexity": and_count + or_count,
                        "suggestion": "Consider extracting to a boolean variable or method"
                    })

            # Check for nested ternary
            if line.count('if') >= 2 and line.count('else') >= 2:
                suggestions.append({
                    "line": i,
                    "issue": "Nested ternary operator",
                    "suggestion": "Consider using if-else statements for clarity"
                })

        return json.dumps({
            "file": str(file),
            "complex_conditionals": suggestions,
            "count": len(suggestions)
        })

    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {type(e).__name__}: {e}"})
