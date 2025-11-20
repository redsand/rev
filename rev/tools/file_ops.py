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

from rev.config import ROOT, EXCLUDE_DIRS, MAX_FILE_BYTES, READ_RETURN_LIMIT, SEARCH_MATCH_LIMIT, LIST_LIMIT
from rev.cache import get_file_cache, get_repo_cache


# ========== Helper Functions ==========

def _safe_path(rel: str) -> pathlib.Path:
    """Resolve path safely within repo root."""
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT)):
        raise ValueError(f"Path escapes repo: {rel}")
    return p


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


def _iter_files(include_glob: str) -> List[pathlib.Path]:
    """Iterate files matching glob pattern."""
    all_paths = [pathlib.Path(p) for p in glob.glob(str(ROOT / include_glob), recursive=True)]
    files = [p for p in all_paths if p.is_file()]
    return [p for p in files if not _should_skip(p)]


def _run_shell(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command."""
    return subprocess.run(
        cmd,
        shell=True,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


# ========== Core File Operations ==========

def read_file(path: str) -> str:
    """Read a file from the repository."""
    p = _safe_path(path)
    if not p.exists():
        return json.dumps({"error": f"Not found: {path}"})
    if p.stat().st_size > MAX_FILE_BYTES:
        return json.dumps({"error": f"Too large (> {MAX_FILE_BYTES} bytes): {path}"})

    # Try to get from cache first
    file_cache = get_file_cache()
    cached_content = file_cache.get_file(p)
    if cached_content is not None:
        return cached_content

    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if len(txt) > READ_RETURN_LIMIT:
            txt = txt[:READ_RETURN_LIMIT] + "\n...[truncated]..."

        # Cache the content
        file_cache.set_file(p, txt)

        return txt
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({"wrote": str(p.relative_to(ROOT)), "bytes": len(content)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def list_dir(pattern: str = "**/*") -> str:
    """List files matching pattern."""
    files = _iter_files(pattern)
    rels = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in files)[:LIST_LIMIT]
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
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
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
        return json.dumps({"deleted": str(p.relative_to(ROOT))})
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
        return json.dumps({
            "moved": str(src_p.relative_to(ROOT)),
            "to": str(dest_p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def append_to_file(path: str, content: str) -> str:
    """Append content to a file."""
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"appended_to": str(p.relative_to(ROOT)), "bytes": len(content)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def replace_in_file(path: str, find: str, replace: str, regex: bool = False) -> str:
    """Find and replace within a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        content = p.read_text(encoding="utf-8", errors="ignore")

        if regex:
            new_content = re.sub(find, replace, content)
        else:
            new_content = content.replace(find, replace)

        if content == new_content:
            return json.dumps({"replaced": 0, "file": str(p.relative_to(ROOT))})

        p.write_text(new_content, encoding="utf-8")
        count = len(content.split(find)) - 1 if not regex else len(re.findall(find, content))
        return json.dumps({
            "replaced": count,
            "file": str(p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def create_directory(path: str) -> str:
    """Create a directory."""
    try:
        p = _safe_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return json.dumps({"created": str(p.relative_to(ROOT))})
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
            "path": str(p.relative_to(ROOT)),
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
        return json.dumps({
            "copied": str(src_p.relative_to(ROOT)),
            "to": str(dest_p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def file_exists(path: str) -> str:
    """Check if a file or directory exists."""
    try:
        p = _safe_path(path)
        return json.dumps({
            "path": path,
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
            "path": str(p.relative_to(ROOT)),
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
            "path": str(p.relative_to(ROOT)) if p != ROOT else ".",
            "tree": "\n".join(tree),
            "files_shown": count
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
