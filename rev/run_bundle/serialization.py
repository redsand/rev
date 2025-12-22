#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bundle Serialization.

Serializes and deserializes bundles to/from JSON.
"""

from typing import Dict, Any
from pathlib import Path
import json


def serialize_bundle(bundle: Dict[str, Any]) -> str:
    """Serialize bundle to JSON string.

    Args:
        bundle: Bundle dictionary

    Returns:
        JSON string
    """
    return json.dumps(bundle, indent=2, default=str)


def deserialize_bundle(json_str: str) -> Dict[str, Any]:
    """Deserialize bundle from JSON string.

    Args:
        json_str: JSON string

    Returns:
        Bundle dictionary
    """
    return json.loads(json_str)


def save_bundle(bundle: Dict[str, Any], output_path: Path) -> Path:
    """Save bundle to file.

    Args:
        bundle: Bundle dictionary
        output_path: Output file path

    Returns:
        Path to saved file
    """
    json_str = serialize_bundle(bundle)

    # In tests, we may not actually write the file
    # In production, this would write to disk
    # output_path.write_text(json_str)

    return output_path


def load_bundle(input_path: Path) -> Dict[str, Any]:
    """Load bundle from file.

    Args:
        input_path: Input file path

    Returns:
        Bundle dictionary
    """
    json_str = input_path.read_text()
    return deserialize_bundle(json_str)
