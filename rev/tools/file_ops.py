#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""File operations tools for rev."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import glob
import shlex
from typing import List, Optional

from rev.config import (
    ROOT,
    EXCLUDE_DIRS,
    MAX_FILE_BYTES,
    READ_RETURN_LIMIT,
    SEARCH_MATCH_LIMIT,
    LIST_LIMIT,
    WARN_ON_NEW_FILES,
    SIMILARITY_THRESHOLD,
)
from rev.cache import get_file_cache, get_repo_cache
from rev.tools.workspace_resolver import resolve_workspace_path
from rev.workspace import get_workspace


# ========== Helper Functions ==========

def _allowed_roots() -> list[pathlib.Path]:
    """Return configured roots that file operations may access."""
    return get_workspace().get_allowed_roots()


def _rel_to_root(path: pathlib.Path) -> str:
    """Return a path string relative to the main ROOT (allows .. for extras)."""
    root = get_workspace().root
    try:
        rel = path.relative_to(root)
        return str(rel)
    except ValueError:
        return os.path.relpath(path, root)


def _rel_to_root_posix(path: pathlib.Path) -> str:
    """Return a stable, forward-slash relative path for logs/results."""
    return _rel_to_root(path).replace("\\", "/")


def _safe_path(rel: str) -> pathlib.Path:
    """Resolve a path safely within configured allowed roots."""
    resolved = resolve_workspace_path(rel, purpose="file operation")
    return resolved.abs_path


def _is_text_file(path: pathlib.Path) -> bool:
    """Check if file is text (no null bytes)."""
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(8192)
    except Exception:
        return False


def _should_skip(path: pathlib.Path) -> bool:
    """Check if path should be excluded."""
    return any(part in EXCLUDE_DIRS for part in path.parts)


def _iter_files(include_glob: str, include_dirs: bool = False) -> List[pathlib.Path]:
    """Iterate files (and optionally directories) matching glob pattern."""
    files: List[pathlib.Path] = []

    for base in _allowed_roots():
        all_paths = [pathlib.Path(p) for p in glob.glob(str(base / include_glob), recursive=True)]
        if include_dirs:
            files.extend(p for p in all_paths if p.exists())
        else:
            files.extend(p for p in all_paths if p.is_file())

    return [p for p in files if not _should_skip(p)]


def _run_shell(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command.

    SECURITY NOTE: This function uses shell=True for compatibility with existing code,
    but commands passed to it should be properly quoted using quote_cmd_arg() from rev.tools.utils.
    Callers must ensure input is sanitized to prevent command injection.
    """
    import shlex
    # If cmd appears to be a list-style command (starts with '['), parse it as a list
    # Otherwise trust that the caller has properly quoted the command
    return subprocess.run(
        cmd,
        shell=True,  # Required for some git operations, but callers must sanitize
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _calculate_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings (simple edit distance based).

    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Simple Levenshtein-based similarity
    if not str1 or not str2:
        return 0.0

    # Normalize strings
    s1 = str1.lower()
    s2 = str2.lower()

    if s1 == s2:
        return 1.0

    # Calculate Levenshtein distance
    len1, len2 = len(s1), len(s2)
    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    current_row = range(len1 + 1)
    for i in range(1, len2 + 1):
        previous_row, current_row = current_row, [i] + [0] * len1
        for j in range(1, len1 + 1):
            add, delete, change = previous_row[j] + 1, current_row[j - 1] + 1, previous_row[j - 1]
            if s1[j - 1] != s2[i - 1]:
                change += 1
            current_row[j] = min(add, delete, change)

    max_len = max(len(str1), len(str2))
    # Handle edge case where both strings are empty
    if max_len == 0:
        return 1.0  # Empty strings are identical
    distance = current_row[len1]
    return 1.0 - (distance / max_len)


def _check_for_similar_files(path: str) -> dict:
    """Check if similar files exist that could be used instead (Phase 2).

    Args:
        path: Path to the file being created

    Returns:
        Dict with 'warnings' and 'similar_files' if found
    """
    if not WARN_ON_NEW_FILES:
        return {"warnings": [], "similar_files": []}

    try:
        p = _safe_path(path)
        filename = p.name
        filestem = p.stem
        parent_dir = p.parent

        warnings = []
        similar_files = []

        # Check for files with similar names in same directory
        if parent_dir.exists():
            for existing in parent_dir.iterdir():
                if not existing.is_file() or existing == p:
                    continue

                # Check file extension matches
                if existing.suffix == p.suffix:
                    similarity = _calculate_similarity(existing.stem, filestem)
                    if similarity >= SIMILARITY_THRESHOLD:
                        similar_files.append({
                            "path": _rel_to_root(existing),
                            "similarity": f"{similarity:.1%}"
                        })

        if similar_files:
            files_str = ", ".join(f"{s['path']} ({s['similarity']})" for s in similar_files[:3])
            warnings.append(
                f"Similar files exist: {files_str}. "
                f"Consider extending existing files instead of creating new one."
            )

        return {
            "warnings": warnings,
            "similar_files": [s["path"] for s in similar_files]
        }
    except Exception:
        return {"warnings": [], "similar_files": []}


# ========== Core File Operations ==========

def read_file(path: str) -> str:
    """Read a file from the repository."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if not p.exists():
        return json.dumps({"error": f"Not found: {path}"})
    if p.is_dir():
        rel = _rel_to_root_posix(p)
        try:
            children = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}", "path": rel, "is_dir": True})

        entries = []
        for child in children:
            if _should_skip(child):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": _rel_to_root_posix(child),
                    "type": "dir" if child.is_dir() else "file",
                }
            )
            if len(entries) >= LIST_LIMIT:
                break

        pattern = "**/*" if rel in {"", "."} else f"{rel}/**/*"
        return json.dumps(
            {
                "path": rel,
                "is_dir": True,
                "count": len(entries),
                "entries": entries,
                "hint": f"Use list_dir with pattern '{pattern}' for recursive listing.",
            },
            ensure_ascii=False,
        )
    if p.stat().st_size > MAX_FILE_BYTES:
        return json.dumps({"error": f"Too large (> {MAX_FILE_BYTES} bytes): {path}"})

    # Try to get from cache first
    file_cache = get_file_cache()
    if file_cache is not None:
        cached_content = file_cache.get_file(p)
        if cached_content is not None:
            return cached_content

    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if len(txt) > READ_RETURN_LIMIT:
            txt = txt[:READ_RETURN_LIMIT] + "\n...[truncated]..."

        # Cache the content
        if file_cache is not None:
            file_cache.set_file(p, txt)

        return txt
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def write_file(path: str, content: str) -> str:
    """Write content to a file (Phase 2-3: with similarity checking and metrics)."""
    try:
        p = _safe_path(path)

        # Check if creating a new file
        is_new = not p.exists()
        check_result = {"warnings": [], "similar_files": []}

        if is_new:
            # Run similarity check for new files
            check_result = _check_for_similar_files(path)

            if check_result.get('warnings'):
                # Log warnings (visible to user/LLM)
                for warning in check_result['warnings']:
                    print(f"  ⚠️  {warning}")

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

        # Invalidate cache for this file
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(p)

        # Track metrics (Phase 3)
        try:
            from rev.tools.reuse_metrics import track_file_operation
            if is_new:
                track_file_operation('create', _rel_to_root(p),
                                      has_similar=bool(check_result.get('similar_files')))
            else:
                track_file_operation('modify', _rel_to_root(p))
        except Exception:
            # Don't fail if metrics tracking fails
            pass

        result = {
            "wrote": _rel_to_root(p),
            "bytes": len(content),
            "path_abs": str(p),
            "path_rel": _rel_to_root_posix(p),
        }

        # Include warnings and similar files in result for LLM awareness
        if is_new and check_result.get('similar_files'):
            result['warning'] = check_result['warnings'][0] if check_result['warnings'] else ""
            result['similar_files'] = check_result['similar_files']
            result['is_new_file'] = True

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def list_dir(pattern: str = "**/*") -> str:
    """List files matching pattern."""
    # If a model passes a directory path (no glob), treat it as recursive listing.
    if isinstance(pattern, str):
        p = pattern.strip().strip('"').strip("'")
        if p and not re.search(r"[*?\[\]]", p):
            p = p.rstrip("/\\")
            pattern = f"{p}/**/*" if p else "**/*"
    files = _iter_files(pattern, include_dirs=True)
    rels = sorted(_rel_to_root(p).replace("\\", "/") for p in files)[:LIST_LIMIT]
    return json.dumps({"count": len(rels), "files": rels})


def search_code(pattern: str, include: str = "**/*", regex: bool = True,
                case_sensitive: bool = False, max_matches: int = SEARCH_MATCH_LIMIT) -> str:
    """Search code for pattern."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rex = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})

    matches = []
    for p in _iter_files(include, include_dirs=False):
        rel = _rel_to_root(p).replace("\\", "/")
        if p.stat().st_size > MAX_FILE_BYTES or not _is_text_file(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if rex.search(line):
                        matches.append({"file": rel, "line": i, "text": line.rstrip("\n")})
                        if len(matches) >= max_matches:
                            return json.dumps({"matches": matches, "truncated": True})
        except Exception:
            pass
    return json.dumps({"matches": matches, "truncated": False})


# ========== Additional File Operations ==========

def delete_file(path: str) -> str:
    """Delete a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.is_dir():
            return json.dumps({"error": f"Cannot delete directory (use delete_directory): {path}"})
        p.unlink()

        # Invalidate cache for this file
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(p)

        return json.dumps({"deleted": _rel_to_root(p), "path_abs": str(p), "path_rel": _rel_to_root_posix(p)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def move_file(src: str, dest: str) -> str:
    """Move or rename a file."""
    try:
        src_p = _safe_path(src)
        dest_p = _safe_path(dest)
        if not src_p.exists():
            return json.dumps({"error": f"Source not found: {src}"})
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        src_p.rename(dest_p)

        # Invalidate cache for both source and destination
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(src_p)
            file_cache.invalidate_file(dest_p)

        return json.dumps(
            {
                "moved": _rel_to_root(src_p),
                "to": _rel_to_root(dest_p),
                "src_path_abs": str(src_p),
                "src_path_rel": _rel_to_root_posix(src_p),
                "dest_path_abs": str(dest_p),
                "dest_path_rel": _rel_to_root_posix(dest_p),
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def append_to_file(path: str, content: str) -> str:
    """Append content to a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)

        # Invalidate cache for this file
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(p)

        return json.dumps(
            {"appended_to": _rel_to_root(p), "bytes": len(content), "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def replace_in_file(path: str, find: str, replace: str, regex: bool = False) -> str:
    """Find and replace within a file."""
    try:
        # Validate find parameter
        if not find:
            return json.dumps({"error": "find parameter cannot be empty"})

        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        content = p.read_text(encoding="utf-8", errors="ignore")

        # Determine match count up front (used for no-op detection and error messages).
        if regex:
            match_count = len(re.findall(find, content))
        else:
            match_count = content.count(find)

        if match_count == 0:
            return json.dumps(
                {"replaced": 0, "file": _rel_to_root(p), "path_abs": str(p), "path_rel": _rel_to_root_posix(p)}
            )

        if regex:
            new_content = re.sub(find, replace, content)
        else:
            new_content = content.replace(find, replace)

        if content == new_content:
            return json.dumps(
                {
                    "replaced": 0,
                    "matches": match_count,
                    "file": _rel_to_root(p),
                    "path_abs": str(p),
                    "path_rel": _rel_to_root_posix(p),
                }
            )

        # Safety: prevent breaking Python syntax on edits to .py files.
        # Validate the resulting content before writing it.
        if p.suffix.lower() == ".py":
            try:
                import ast

                ast.parse(new_content, filename=str(p))
            except SyntaxError as e:
                return json.dumps(
                    {
                        "error": f"SyntaxError: {e.msg} (line {e.lineno}:{e.offset})",
                        "replaced": match_count,
                        "file": _rel_to_root(p),
                        "path_abs": str(p),
                        "path_rel": _rel_to_root_posix(p),
                        "syntax_error": {
                            "msg": e.msg,
                            "lineno": e.lineno,
                            "offset": e.offset,
                            "text": getattr(e, "text", None),
                        },
                    }
                )

        p.write_text(new_content, encoding="utf-8")

        # Invalidate cache for this file
        file_cache = get_file_cache()
        if file_cache is not None:
            file_cache.invalidate_file(p)

        count = match_count
        return json.dumps(
            {
                "replaced": count,
                "file": _rel_to_root(p),
                "path_abs": str(p),
                "path_rel": _rel_to_root_posix(p),
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def create_directory(path: str) -> str:
    """Create a directory."""
    try:
        p = _safe_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return json.dumps({"created": _rel_to_root(p), "path_abs": str(p), "path_rel": _rel_to_root_posix(p)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def get_file_info(path: str) -> str:
    """Get file metadata."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        stat = p.stat()
        return json.dumps({
            "path": _rel_to_root(p),
            "path_abs": str(p),
            "path_rel": _rel_to_root_posix(p),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir()
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def copy_file(src: str, dest: str) -> str:
    """Copy a file."""
    try:
        src_p = _safe_path(src)
        dest_p = _safe_path(dest)
        if not src_p.exists():
            return json.dumps({"error": f"Source not found: {src}"})
        if src_p.is_dir():
            return json.dumps({"error": f"Cannot copy directory: {src}"})
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_p, dest_p)
        return json.dumps(
            {
                "copied": _rel_to_root(src_p),
                "to": _rel_to_root(dest_p),
                "src_path_abs": str(src_p),
                "src_path_rel": _rel_to_root_posix(src_p),
                "dest_path_abs": str(dest_p),
                "dest_path_rel": _rel_to_root_posix(dest_p),
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def file_exists(path: str) -> str:
    """Check if a file or directory exists."""
    try:
        p = _safe_path(path)
        return json.dumps({
            "path": path,
            "path_abs": str(p),
            "path_rel": _rel_to_root_posix(p),
            "exists": p.exists(),
            "is_file": p.is_file() if p.exists() else False,
            "is_dir": p.is_dir() if p.exists() else False
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def read_file_lines(path: str, start: int = 1, end: int = None) -> str:
    """Read specific lines from a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.stat().st_size > MAX_FILE_BYTES:
            return json.dumps({"error": f"Too large (> {MAX_FILE_BYTES} bytes): {path}"})

        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        start_idx = max(0, start - 1)  # Convert to 0-based index
        end_idx = len(lines) if end is None else min(len(lines), end)

        selected_lines = lines[start_idx:end_idx]
        return json.dumps({
            "path": _rel_to_root(p),
            "path_abs": str(p),
            "path_rel": _rel_to_root_posix(p),
            "start": start,
            "end": end_idx,
            "total_lines": len(lines),
            "lines": selected_lines
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tree_view(path: str = ".", max_depth: int = 3, max_files: int = 100) -> str:
    """Generate a tree view of directory structure."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if not p.is_dir():
            return json.dumps({"error": f"Not a directory: {path}"})

        tree = []
        count = 0

        def build_tree(dir_path, prefix="", depth=0):
            nonlocal count
            if depth > max_depth or count >= max_files:
                return

            try:
                items = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                for idx, item in enumerate(items):
                    if count >= max_files:
                        break

                    is_last = idx == len(items) - 1
                    current_prefix = "└── " if is_last else "├── "
                    tree.append(prefix + current_prefix + item.name)
                    count += 1

                    if item.is_dir() and item.name not in EXCLUDE_DIRS:
                        extension = "    " if is_last else "│   "
                        build_tree(item, prefix + extension, depth + 1)
            except PermissionError:
                pass

        tree.append(p.name if p != ROOT else ".")
        build_tree(p)

        return json.dumps({
            "path": _rel_to_root(p) if p != ROOT else ".",
            "path_abs": str(p),
            "path_rel": _rel_to_root_posix(p) if p != ROOT else ".",
            "tree": "\n".join(tree),
            "files_shown": count
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
