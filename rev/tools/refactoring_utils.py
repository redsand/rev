#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refactoring utilities for structuring modules."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import List, Dict, Optional

from rev.config import ROOT
from rev.tools.file_ops import _safe_path


def _get_class_segments(source: str, tree: ast.Module) -> List[Dict[str, any]]:
    """Extract top-level class definitions with their source code."""
    segments: List[Dict[str, any]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            segment = ast.get_source_segment(source, node)
            if segment is None:
                continue
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is None or end is None:
                continue
            segments.append(
                {
                    "name": node.name,
                    "start": start - 1,
                    "end": end,
                    "source": segment.rstrip() + "\n",
                }
            )
    return segments


def split_python_module_classes(
    source_path: str,
    target_directory: Optional[str] = None,
    overwrite: bool = False,
) -> str:
    """Split each top-level class in a Python module into individual files.

    The original module is converted into a package (directory) containing the
    extracted files and an __init__.py aggregator. The original .py file is
    renamed with a .bak suffix for reference.
    """
    try:
        source_file = _safe_path(source_path)
        if not source_file.exists():
            return json.dumps({"error": f"Source file not found: {source_path}"})

        content = source_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return json.dumps({"error": f"Failed to parse {source_path}: {exc}"})

        class_segments = _get_class_segments(content, tree)
        if not class_segments:
            return json.dumps({"error": f"No top-level classes found in {source_path}"})

        if target_directory:
            target_dir = _safe_path(target_directory)
        else:
            target_dir = source_file.with_suffix("")

        target_dir.mkdir(parents=True, exist_ok=True)

        package_init = target_dir / "__init__.py"
        created_files: List[str] = []
        skipped: List[str] = []

        # Determine shared prefix (docstring/imports) by chopping everything before first class
        first_class_start = min(seg["start"] for seg in class_segments)
        shared_prefix = "".join(content.splitlines(keepends=True)[:first_class_start]).strip("\n")

        # Write individual class files
        for seg in class_segments:
            module_name = seg["name"]
            class_file = target_dir / f"{module_name}.py"
            if class_file.exists() and not overwrite:
                skipped.append(class_file.name)
                continue

            parts: List[str] = []
            if shared_prefix:
                parts.append(shared_prefix.rstrip() + "\n\n")
            parts.append(seg["source"].lstrip("\n"))
            class_file.write_text("".join(parts).rstrip() + "\n", encoding="utf-8")
            created_files.append(str(class_file.relative_to(ROOT)))

        # Build remaining content (original minus classes)
        lines = content.splitlines(keepends=True)
        for seg in sorted(class_segments, key=lambda s: s["start"], reverse=True):
            del lines[seg["start"]:seg["end"]]
        remaining_content = "".join(lines).rstrip()

        aggregator_parts: List[str] = []
        if remaining_content:
            aggregator_parts.append(remaining_content.rstrip() + "\n\n")

        aggregator_parts.append("# Auto-generated exports for analyst classes\n")
        for seg in class_segments:
            module_name = seg["name"]
            aggregator_parts.append(f"from .{module_name} import {seg['name']}\n")

        aggregator_parts.append("\n__all__ = [\n")
        for seg in class_segments:
            aggregator_parts.append(f"    '{seg['name']}',\n")
        aggregator_parts.append("]\n")

        package_init.write_text("".join(aggregator_parts), encoding="utf-8")

        # Backup original file so imports resolve to the new package
        backup_path = source_file.with_suffix(f"{source_file.suffix}.bak")
        source_file.rename(backup_path)

        return json.dumps(
            {
                "classes_split": len(class_segments),
                "created_files": created_files,
                "skipped": skipped,
                "package_dir": str(target_dir.relative_to(ROOT)),
                "package_init": str(package_init.relative_to(ROOT)),
                "original_backup": str(backup_path.relative_to(ROOT)),
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
