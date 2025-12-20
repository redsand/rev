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

    The original module is converted into a package (directory) containing the
    extracted files and an __init__.py aggregator.
    """
    try:
        source_file = _safe_path(source_path)
        if target_directory:
            target_dir = _safe_path(target_directory)
        else:
            target_dir = source_file.with_suffix("")
        if not source_file.exists():
            backup_candidate = _find_adjacent_backup(source_file)
            if backup_candidate:
                return json.dumps(
                    {
                        "error": f"Source already split (backup exists): {backup_candidate.name}",
                        "status": "source_already_split",
                        "backup": backup_candidate.relative_to(config.ROOT).as_posix(),
                        "package_dir": target_dir.relative_to(config.ROOT).as_posix(),
                    },
                    indent=2,
                )
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
        lines = content.splitlines(keepends=True)
        first_class_start = min(seg["start"] for seg in class_segments)
        shared_prefix = "".join(lines[:first_class_start]).strip("\n")
        trailing_imports = _collect_trailing_imports(content, tree, first_class_start)

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
            if trailing_imports:
                parts.append("\n".join(trailing_imports).rstrip() + "\n\n")
            parts.append(seg["source"].lstrip("\n"))
            class_file.write_text("".join(parts).rstrip() + "\n", encoding="utf-8")
            created_files.append(class_file.relative_to(config.ROOT).as_posix())

        # Build remaining content (original minus classes)
        lines = content.splitlines(keepends=True)
        for seg in sorted(class_segments, key=lambda s: s["start"], reverse=True):
            del lines[seg["start"]:seg["end"]]
        remaining_content = "".join(lines).rstrip()

        aggregator_parts: List[str] = []
        if remaining_content:
            aggregator_parts.append(remaining_content.rstrip() + "\n\n")

        aggregator_parts.append("# Auto-generated exports for extracted classes\n")
        for seg in class_segments:
            module_name = seg["name"]
            aggregator_parts.append(f"from .{module_name} import {seg['name']}\n")

        aggregator_parts.append("\n__all__ = [\n")
        for seg in class_segments:
            aggregator_parts.append(f"    '{seg['name']}',\n")
        aggregator_parts.append("]\n")

        package_init.write_text("".join(aggregator_parts), encoding="utf-8")

        source_moved_to: Optional[str] = None
        source_move_error: Optional[str] = None
        if delete_source:
            try:
                backup = _compute_backup_path(source_file)
                source_file.rename(backup)
                source_moved_to = backup.relative_to(config.ROOT).as_posix()
            except Exception as e:
                source_move_error = f"{type(e).__name__}: {e}"
                get_logger().log("tools", "FILE_MOVE_ERROR", {
                    "source": source_path,
                    "error": source_move_error
                }, "ERROR")

        try:
            package_module = (
                str(source_file.relative_to(config.ROOT).with_suffix(""))
                .replace("\\", "/")
                .replace("/", ".")
            )
        except ValueError:
            package_module = source_file.with_suffix("").name
        call_site_updates = _rewrite_package_imports(package_module, target_dir)

        return json.dumps(
            {
                "classes_split": len(class_segments),
                "created_files": created_files,
                "skipped": skipped,
                "package_dir": target_dir.relative_to(config.ROOT).as_posix(),
                "package_init": package_init.relative_to(config.ROOT).as_posix(),
                "call_sites_updated": call_site_updates,
                "source_moved_to": source_moved_to,
                "source_move_error": source_move_error,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def _rewrite_package_imports(package_module: str, target_dir: Path) -> List[str]:
    """Rewrite import statements to use consolidated package exports."""
    updated_files: List[str] = []
    pattern = re.compile(rf"^\s*from\s+{re.escape(package_module)}\.[A-Za-z0-9_]+\s+import\s+(.+)$")

    for file_path in config.ROOT.rglob("*.py"):
        try:
            if target_dir in file_path.parents:
                continue

            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
            collected: List[str] = []
            new_lines: List[str] = []
            replaced = False
            existing_idx = None
            for line in lines:
                match = pattern.match(line)
                if match:
                    replaced = True
                    classes = [cls.strip() for cls in match.group(1).split(",") if cls.strip()]
                    collected.extend(classes)
                    continue
                if line.strip().startswith(f"from {package_module} import"):
                    existing_idx = len(new_lines)
                new_lines.append(line)

            if replaced and collected:
                block = _format_import_block(package_module, sorted(set(collected)))
                if existing_idx is not None:
                    new_lines[existing_idx] = block
                else:
                    insert_idx = _find_import_insertion_index(new_lines)
                    new_lines.insert(insert_idx, block)
                file_path.write_text("".join(new_lines), encoding="utf-8")
                updated_files.append(file_path.relative_to(config.ROOT).as_posix())
        except Exception:
            continue

    return updated_files


def _format_import_block(package_module: str, classes: List[str]) -> str:
    if not classes:
        return ""
    if len(classes) <= 4:
        return f"from {package_module} import {', '.join(classes)}\n"
    block = [f"from {package_module} import (\n"]
    for cls in classes:
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
