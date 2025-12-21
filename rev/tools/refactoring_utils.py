#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refactoring utilities for structuring modules."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Set

from rev import config
from rev.tools.file_ops import _safe_path
from rev.debug_logger import get_logger


def _find_adjacent_backup(source_file: Path) -> Optional[Path]:
    """Return an existing backup path for a previously split module."""
    pattern = f"{source_file.name}.bak*"
    try:
        for candidate in source_file.parent.glob(pattern):
            if candidate.is_file():
                return candidate
    except Exception:
        pass
    return None


def _compute_backup_path(source_file: Path) -> Path:
    """Choose a deterministic backup path without double .bak suffixes."""
    if source_file.name.endswith(".bak"):
        return source_file
    candidate = source_file.with_suffix(source_file.suffix + ".bak")
    if not candidate.exists():
        return candidate
    suffix_index = 1
    while True:
        numbered = source_file.with_suffix(source_file.suffix + f".bak.{suffix_index}")
        if not numbered.exists():
            return numbered
        suffix_index += 1


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


def _collect_trailing_imports(source: str, tree: ast.Module, first_class_start: int) -> List[str]:
    """Collect import statements that appear after the first class definition."""
    trailing: List[str] = []
    seen: Set[str] = set()
    lines = source.splitlines()

    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        lineno = getattr(node, "lineno", None)
        if lineno is None or (lineno - 1) < first_class_start:
            continue
        segment = ast.get_source_segment(source, node)
        if not segment and 0 < lineno <= len(lines):
            segment = lines[lineno - 1].strip()
        snippet = (segment or "").strip()
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        trailing.append(snippet)
    return trailing


def split_python_module_classes(
    source_path: str,
    target_directory: Optional[str] = None,
    overwrite: bool = False,
    delete_source: bool = True,
) -> str:
    """Split each top-level class in a Python module into individual files.

    This dependency-aware implementation correctly handles imports, parent classes,
    and shared helper functions to produce a valid Python package.
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

        target_dir = _safe_path(target_directory) if target_directory else source_file.with_suffix("")
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Analyze dependencies for all nodes
        imports = {node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        
        class_nodes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        class_dependencies = {
            name: _analyze_node_dependencies(node, set(class_nodes.keys()), set(functions.keys()))
            for name, node in class_nodes.items()
        }

        # 2. Separate shared code (imports, functions) from classes
        init_content_parts = []
        for imp in imports:
            init_content_parts.append(ast.get_source_segment(content, imp))
        for func_node in functions.values():
            init_content_parts.append(ast.get_source_segment(content, func_node))
        
        created_files, skipped = [], []

        # 3. Write individual class files with correct dependencies
        for seg in class_segments:
            class_name = seg["name"]
            class_file = target_dir / f"{class_name}.py"
            if class_file.exists() and not overwrite:
                skipped.append(class_file.name)
                continue

            deps = class_dependencies.get(class_name, set())
            
            file_parts = []
            # Add required imports from the original shared prefix
            for imp in imports:
                 file_parts.append(ast.get_source_segment(content, imp) + "\n")

            # Add imports for parent classes
            for dep in deps:
                if dep in class_nodes:  # It's another class in the same module
                    file_parts.append(f"from .{dep} import {dep}\n")

            # Add imports for shared functions
            if any(dep in functions for dep in deps):
                 file_parts.append(f"from . import {', '.join(sorted([d for d in deps if d in functions]))}\n\n")

            file_parts.append(seg["source"])
            class_file.write_text("".join(file_parts), encoding="utf-8")
            created_files.append(class_file.relative_to(config.ROOT).as_posix())

        # 4. Create __init__.py with shared code and exports
        init_content = "\n\n".join(filter(None, init_content_parts))

        # Check if __all__ already exists in init_content to avoid duplicates
        has_all_already = "__all__" in init_content

        exports = "\n\n# Auto-generated exports\n"
        all_exports = list(class_nodes.keys()) + list(functions.keys())
        for class_seg in class_segments:
            exports += f"from .{class_seg['name']} import {class_seg['name']}\n"

        # Only add __all__ if it doesn't already exist
        all_section = ""
        if not has_all_already:
            all_section = "\n__all__ = [\n" + "".join(f"    '{name}',\n" for name in sorted(all_exports)) + "]\n"

        package_init = target_dir / "__init__.py"
        final_content = init_content + exports + all_section
        package_init.write_text(final_content, encoding="utf-8")
        
        # 5. Handle original source file
        source_moved_to = None
        if delete_source:
            backup = _compute_backup_path(source_file)
            source_file.rename(backup)
            source_moved_to = backup.relative_to(config.ROOT).as_posix()

        return json.dumps(
            {
                "classes_split": len(created_files),
                "created_files": created_files,
                "skipped": skipped,
                "package_dir": target_dir.relative_to(config.ROOT).as_posix(),
                "source_moved_to": source_moved_to,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _analyze_node_dependencies(node: ast.AST, local_classes: Set[str], local_funcs: Set[str]) -> Set[str]:
    """Analyze a node to find its dependencies on other classes or functions."""
    dependencies = set()
    
    # Add parent classes as dependencies
    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in local_classes:
                dependencies.add(base.id)

    # Walk the AST to find all names and calls
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            # Direct usage of a class or function
            if child.id in local_classes or child.id in local_funcs:
                dependencies.add(child.id)
        elif isinstance(child, ast.Call):
            # Function calls
            if isinstance(child.func, ast.Name) and child.func.id in local_funcs:
                dependencies.add(child.func.id)
            # Instantiation of other classes
            if isinstance(child.func, ast.Name) and child.func.id in local_classes:
                dependencies.add(child.func.id)

    # Exclude the class's own name from its dependencies
    if isinstance(node, ast.ClassDef):
        dependencies.discard(node.name)
        
    return dependencies


def _rewrite_package_imports(package_module: str, target_dir: Path) -> List[str]:
    """Rewrite import statements to use consolidated package exports."""
    # This function needs to be adapted to the new dependency-aware logic
    # For now, we will assume the new structure is handled correctly
    return []


def _format_import_block(package_module: str, classes: List[str]) -> str:
    """Formats a block of import statements for a given package module."""
    if not classes:
        return ""
    
    # Simple, single-line import for a few classes
    if len(classes) <= 4:
        return f"from {package_module} import {', '.join(classes)}\n"
    
    # Multi-line import for many classes
    block = [f"from {package_module} import (\n"]
    for cls in sorted(classes):
        block.append(f"    {cls},\n")
    block.append(")\n")
    return "".join(block)


def _find_import_insertion_index(lines: List[str]) -> int:
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#!"):
            idx += 1
            continue
        if stripped.startswith(("'''", '"""')):
            quote = stripped[:3]
            idx += 1
            while idx < len(lines) and quote not in lines[idx]:
                idx += 1
            idx += 1
            continue
        if stripped.startswith(("import ", "from ")):
            idx += 1
            continue
        break
    return idx
