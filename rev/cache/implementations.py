#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cache implementations for specific use cases."""

import json
import hashlib
import pathlib
import subprocess
from typing import Dict, Any, List, Optional

from .base import IntelligentCache


class FileContentCache(IntelligentCache):
    """Cache for file contents with modification time tracking."""

    def __init__(self, **kwargs):
        super().__init__(name="file_content", ttl=60, **kwargs)

    def get_file(self, file_path: pathlib.Path) -> Optional[str]:
        """Get file content from cache, checking modification time."""
        if not file_path.exists():
            return None

        # Use file path + mtime as cache key
        mtime = file_path.stat().st_mtime
        cache_key = f"{file_path}:{mtime}"

        # Check if we have cached version
        cached = self.get(cache_key)
        if cached is not None:
            return cached

        # Invalidate any old versions of this file
        old_prefix = f"{file_path}:"
        to_invalidate = [k for k in self._cache.keys() if k.startswith(old_prefix)]
        for key in to_invalidate:
            self.invalidate(key)

        return None

    def set_file(self, file_path: pathlib.Path, content: str):
        """Cache file content with modification time."""
        if not file_path.exists():
            return

        mtime = file_path.stat().st_mtime
        cache_key = f"{file_path}:{mtime}"
        self.set(cache_key, content, metadata={"file_path": str(file_path), "mtime": mtime})


class LLMResponseCache(IntelligentCache):
    """Cache for LLM responses based on message hash."""

    def __init__(self, **kwargs):
        super().__init__(name="llm_response", ttl=3600, **kwargs)  # 1 hour TTL

    def _hash_messages(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None) -> str:
        """Create hash of messages for cache key."""
        # Create deterministic string representation
        key_data = json.dumps(messages, sort_keys=True)
        if tools:
            key_data += json.dumps(tools, sort_keys=True)

        # Hash it
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get_response(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None) -> Optional[Dict[str, Any]]:
        """Get cached LLM response."""
        cache_key = self._hash_messages(messages, tools)
        return self.get(cache_key)

    def set_response(self, messages: List[Dict[str, str]], response: Dict[str, Any], tools: Optional[List[Dict]] = None):
        """Cache LLM response."""
        cache_key = self._hash_messages(messages, tools)
        self.set(cache_key, response, metadata={"messages_count": len(messages)})


class RepoContextCache(IntelligentCache):
    """Cache for repository context (git status, log, file tree)."""

    def __init__(self, root: pathlib.Path, **kwargs):
        super().__init__(name="repo_context", ttl=30, **kwargs)  # 30 seconds TTL
        self.root = root

    def get_context(self) -> Optional[str]:
        """Get cached repository context."""
        # Use current git HEAD commit as part of cache key
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.root
            )
            head_commit = proc.stdout.strip() if proc.returncode == 0 else "no-git"
        except:
            head_commit = "no-git"

        cache_key = f"context:{head_commit}"
        return self.get(cache_key)

    def set_context(self, context: str):
        """Cache repository context."""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.root
            )
            head_commit = proc.stdout.strip() if proc.returncode == 0 else "no-git"
        except:
            head_commit = "no-git"

        cache_key = f"context:{head_commit}"
        self.set(cache_key, context, metadata={"commit": head_commit})


class DependencyTreeCache(IntelligentCache):
    """Cache for dependency analysis results."""

    def __init__(self, root: pathlib.Path, **kwargs):
        super().__init__(name="dependency_tree", ttl=600, **kwargs)  # 10 minutes TTL
        self.root = root

    def get_dependencies(self, language: str) -> Optional[str]:
        """Get cached dependency analysis."""
        # Check if dependency file has changed
        dep_file_path = None

        if language == "python":
            if (self.root / "requirements.txt").exists():
                dep_file_path = self.root / "requirements.txt"
            elif (self.root / "pyproject.toml").exists():
                dep_file_path = self.root / "pyproject.toml"
        elif language == "javascript":
            if (self.root / "package.json").exists():
                dep_file_path = self.root / "package.json"
        elif language == "rust":
            if (self.root / "Cargo.toml").exists():
                dep_file_path = self.root / "Cargo.toml"
        elif language == "go":
            if (self.root / "go.mod").exists():
                dep_file_path = self.root / "go.mod"

        if dep_file_path and dep_file_path.exists():
            mtime = dep_file_path.stat().st_mtime
            cache_key = f"{language}:{dep_file_path}:{mtime}"
            return self.get(cache_key)

        return None

    def set_dependencies(self, language: str, result: str):
        """Cache dependency analysis."""
        dep_file_path = None

        if language == "python":
            if (self.root / "requirements.txt").exists():
                dep_file_path = self.root / "requirements.txt"
            elif (self.root / "pyproject.toml").exists():
                dep_file_path = self.root / "pyproject.toml"
        elif language == "javascript":
            if (self.root / "package.json").exists():
                dep_file_path = self.root / "package.json"
        elif language == "rust":
            if (self.root / "Cargo.toml").exists():
                dep_file_path = self.root / "Cargo.toml"
        elif language == "go":
            if (self.root / "go.mod").exists():
                dep_file_path = self.root / "go.mod"

        if dep_file_path and dep_file_path.exists():
            mtime = dep_file_path.stat().st_mtime
            cache_key = f"{language}:{dep_file_path}:{mtime}"
            self.set(cache_key, result, metadata={"language": language, "file": str(dep_file_path)})
