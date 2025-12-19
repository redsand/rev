#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data format conversion utilities."""

import json
import csv
from typing import Optional

from rev import config
from rev.tools.utils import _safe_path


def convert_json_to_yaml(json_path: str, yaml_path: str = None) -> str:
    """Convert JSON file to YAML format.

    Args:
        json_path: Path to JSON file
        yaml_path: Output YAML path (optional, defaults to .yaml extension)

    Returns:
        JSON string with conversion result
    """
    try:
        import yaml
    except ImportError:
        return json.dumps({"error": "PyYAML not installed. Run: pip install pyyaml"})

    try:
        json_file = _safe_path(json_path)
        if not json_file.exists():
            return json.dumps({"error": f"File not found: {json_path}"})

        # Read JSON
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Determine output path
        if yaml_path is None:
            yaml_path = json_path.rsplit('.', 1)[0] + '.yaml'
        yaml_file = _safe_path(yaml_path)

        # Write YAML
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        with open(yaml_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return json.dumps({
            "converted": json_file.relative_to(config.ROOT).as_posix(),
            "to": yaml_file.relative_to(config.ROOT).as_posix(),
            "format": "YAML"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})


def convert_yaml_to_json(yaml_path: str, json_path: str = None) -> str:
    """Convert YAML file to JSON format.

    Args:
        yaml_path: Path to YAML file
        json_path: Output JSON path (optional, defaults to .json extension)

    Returns:
        JSON string with conversion result
    """
    try:
        import yaml
    except ImportError:
        return json.dumps({"error": "PyYAML not installed. Run: pip install pyyaml"})

    try:
        yaml_file = _safe_path(yaml_path)
        if not yaml_file.exists():
            return json.dumps({"error": f"File not found: {yaml_path}"})

        # Read YAML
        with open(yaml_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # Determine output path
        if json_path is None:
            json_path = yaml_path.rsplit('.', 1)[0] + '.json'
        json_file = _safe_path(json_path)

        # Write JSON
        json_file.parent.mkdir(parents=True, exist_ok=True)
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return json.dumps({
            "converted": yaml_file.relative_to(config.ROOT).as_posix(),
            "to": json_file.relative_to(config.ROOT).as_posix(),
            "format": "JSON"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})


def convert_csv_to_json(csv_path: str, json_path: str = None) -> str:
    """Convert CSV file to JSON format.

    Args:
        csv_path: Path to CSV file
        json_path: Output JSON path (optional)

    Returns:
        JSON string with conversion result
    """
    try:
        csv_file = _safe_path(csv_path)
        if not csv_file.exists():
            return json.dumps({"error": f"File not found: {csv_path}"})

        # Read CSV
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            data = list(reader)

        # Determine output path
        if json_path is None:
            json_path = csv_path.rsplit('.', 1)[0] + '.json'
        json_file = _safe_path(json_path)

        # Write JSON
        json_file.parent.mkdir(parents=True, exist_ok=True)
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return json.dumps({
            "converted": csv_file.relative_to(config.ROOT).as_posix(),
            "to": json_file.relative_to(config.ROOT).as_posix(),
            "rows": len(data),
            "format": "JSON"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})


def convert_json_to_csv(json_path: str, csv_path: str = None) -> str:
    """Convert JSON file (array of objects) to CSV format.

    Args:
        json_path: Path to JSON file (must contain array of objects)
        csv_path: Output CSV path (optional)

    Returns:
        JSON string with conversion result
    """
    try:
        json_file = _safe_path(json_path)
        if not json_file.exists():
            return json.dumps({"error": f"File not found: {json_path}"})

        # Read JSON
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list) or not data:
            return json.dumps({"error": "JSON must contain a non-empty array of objects"})

        # Determine output path
        if csv_path is None:
            csv_path = json_path.rsplit('.', 1)[0] + '.csv'
        csv_file = _safe_path(csv_path)

        # Write CSV
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            if data:
                fieldnames = list(data[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)

        return json.dumps({
            "converted": json_file.relative_to(config.ROOT).as_posix(),
            "to": csv_file.relative_to(config.ROOT).as_posix(),
            "rows": len(data),
            "format": "CSV"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})


def convert_env_to_json(env_path: str, json_path: str = None) -> str:
    """Convert .env file to JSON format.

    Args:
        env_path: Path to .env file
        json_path: Output JSON path (optional)

    Returns:
        JSON string with conversion result
    """
    try:
        env_file = _safe_path(env_path)
        if not env_file.exists():
            return json.dumps({"error": f"File not found: {env_path}"})

        # Parse .env file
        data = {}
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes if present
                        value = value.strip().strip('"').strip("'")
                        data[key.strip()] = value

        # Determine output path
        if json_path is None:
            json_path = env_path + '.json'
        json_file = _safe_path(json_path)

        # Write JSON
        json_file.parent.mkdir(parents=True, exist_ok=True)
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return json.dumps({
            "converted": env_file.relative_to(config.ROOT).as_posix(),
            "to": json_file.relative_to(config.ROOT).as_posix(),
            "variables": len(data),
            "format": "JSON"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})
