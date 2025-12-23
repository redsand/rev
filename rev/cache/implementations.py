#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cache implementations for specific use cases."""

import json
import hashlib
import pathlib
import subprocess
import threading
from typing import Dict, Any, List, Optional

from .base import IntelligentCache


class FileContentCache(IntelligentCache):
    """Cache for file contents with modification time tracking."""

    def __init__(self, **kwargs):
        super().__init__(name="file_content", ttl=60, **kwargs)

    def get_file(self, file_path: pathlib.Path) -> Optional[str]:
        """Get file content from cache, checking modification time and hash."""
        if not file_path.exists():
            return None

        # Use file path + mtime as cache key
        mtime = file_path.stat().st_mtime
        cache_key = f"{file_path}:{mtime}"

        # Check if we have cached version
        cached = self.get(cache_key)
        if cached is not None:
            return cached

        # Fallback: if mtime changed, check hash to avoid redundant reload
        # This handles cases where mtime is updated but content is identical
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            
            # Look for existing entry with same hash for this file
            prefix = f"{file_path}:"
            with self._lock:
                for k, entry in self._cache.items():
                    if k.startswith(prefix) and entry.metadata.get("hash") == content_hash:
                        # Found match by hash! Update key to current mtime and return.
                        self.set_file(file_path, content)
                        return content
        except Exception:
            pass

        # Invalidate any old versions of this file (thread-safe)
        old_prefix = f"{file_path}:"
        with self._lock:
            to_invalidate = [k for k in self._cache.keys() if k.startswith(old_prefix)]
            for key in to_invalidate:
                self.invalidate(key)

        return None

    def set_file(self, file_path: pathlib.Path, content: str):
        """Cache file content with modification time and hash."""
        if not file_path.exists():
            return

        mtime = file_path.stat().st_mtime
        cache_key = f"{file_path}:{mtime}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.set(cache_key, content, metadata={
            "file_path": str(file_path), 
            "mtime": mtime,
            "hash": content_hash
        })

    def invalidate_file(self, file_path: pathlib.Path):
        """Invalidate all cache entries for a specific file (all mtimes)."""
        prefix = f"{file_path}:"
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_remove:
                self.invalidate(key)


class LLMResponseCache(IntelligentCache):
    """Cache for LLM responses based on message hash.

    Optimized to cache tools hash separately to avoid re-serializing
    the same tools list on every LLM call (5-20ms savings per call).
    """

    def __init__(self, **kwargs):
        super().__init__(name="llm_response", ttl=3600, **kwargs)  # 1 hour TTL
        self._tools_hash_cache = {}  # Cache for tools hash by object id
        self._lock = threading.Lock()  # Thread safety for concurrent access
        self._tools_cache_max_size = 1000  # Limit cache growth to prevent memory leak

    def _hash_tools(self, tools: Optional[List[Dict]]) -> str:
        """Hash tools list with caching to avoid repeated JSON serialization.

        Args:
            tools: Optional list of tool definitions

        Returns:
            Hex hash string (16 chars) or "no-tools"
        """
        if tools is None:
            return "no-tools"

        # Use object id as cache key (same list object = same hash)
        tools_id = id(tools)

        with self._lock:
            if tools_id not in self._tools_hash_cache:
                # Only serialize and hash if not cached
                tools_json = json.dumps(tools, sort_keys=True)
                tool_hash = hashlib.sha256(tools_json.encode()).hexdigest()[:16]

                # Prevent unbounded growth - clear cache if it gets too large
                if len(self._tools_hash_cache) >= self._tools_cache_max_size:
                    self._tools_hash_cache.clear()

                self._tools_hash_cache[tools_id] = tool_hash

            return self._tools_hash_cache[tools_id]

    def _hash_messages(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None, model: Optional[str] = None) -> str:
        """Create hash of messages for cache key.

        Optimized to use cached tools hash instead of re-serializing tools on every call.

        Args:
            messages: List of message dicts
            tools: Optional list of tool definitions
            model: Optional model name to include in cache key

        Returns:
            Hex hash string combining message hash, tools hash, and model
        """
        # Hash messages (still need to do this each time as messages change)
        msg_json = json.dumps(messages, sort_keys=True)
        msg_hash = hashlib.sha256(msg_json.encode()).hexdigest()[:32]

        # Use cached tools hash (avoids 5-20ms of JSON serialization)
        tools_hash = self._hash_tools(tools)

        # Combine hashes
        combined = f"{msg_hash}:{tools_hash}:{model or 'default'}"
        return hashlib.sha256(combined.encode()).hexdigest()

    def get_response(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get cached LLM response.

        Args:
            messages: List of message dicts
            tools: Optional list of tool definitions
            model: Optional model name to match in cache
        """
        cache_key = self._hash_messages(messages, tools, model)
        return self.get(cache_key)

    def set_response(self, messages: List[Dict[str, str]], response: Dict[str, Any], tools: Optional[List[Dict]] = None, model: Optional[str] = None):
        """Cache LLM response.

        Args:
            messages: List of message dicts
            response: LLM response to cache
            tools: Optional list of tool definitions
            model: Optional model name to include in cache key
        """
        cache_key = self._hash_messages(messages, tools, model)
        self.set(cache_key, response, metadata={"messages_count": len(messages), "model": model})


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
        except Exception:
            head_commit = "no-git"  # Git not available or subprocess error

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
        except Exception:
            head_commit = "no-git"  # Git not available or subprocess error

        cache_key = f"context:{head_commit}"
        self.set(cache_key, context, metadata={"commit": head_commit})


class ASTAnalysisCache(IntelligentCache):
    """Cache for AST analysis results with file modification tracking.

    Provides massive speedup for repeated AST analysis (10-1000x on cache hits).
    Files are cached by path + mtime + patterns to ensure correctness.
    """

    def __init__(self, **kwargs):
        super().__init__(name="ast_analysis", ttl=600, **kwargs)  # 10 minutes TTL

    def get_file_analysis(self, file_path: pathlib.Path, patterns: List[str]) -> Optional[dict]:
        """Get cached AST analysis for a file.

        Args:
            file_path: Path to the Python file
            patterns: List of pattern names to check

        Returns:
            Cached analysis dict or None if not cached/expired
        """
        if not file_path.exists():
            return None

        # Cache key includes file path, mtime, and patterns
        mtime = file_path.stat().st_mtime
        patterns_key = ":".join(sorted(patterns))
        cache_key = f"{file_path}:{mtime}:{patterns_key}"

        return self.get(cache_key)

    def set_file_analysis(self, file_path: pathlib.Path, patterns: List[str], result: dict):
        """Cache AST analysis results for a file.

        Args:
            file_path: Path to the Python file
            patterns: List of pattern names that were checked
            result: Analysis result dictionary to cache
        """
        if not file_path.exists():
            return

        mtime = file_path.stat().st_mtime
        patterns_key = ":".join(sorted(patterns))
        cache_key = f"{file_path}:{mtime}:{patterns_key}"

        self.set(cache_key, result, metadata={
            "file": str(file_path),
            "patterns": patterns,
            "mtime": mtime
        })


class DependencyTreeCache(IntelligentCache):
    """Cache for dependency analysis results."""

    def __init__(self, root: pathlib.Path, **kwargs):
        super().__init__(name="dependency_tree", ttl=600, **kwargs)  # 10 minutes TTL
        self.root = root

    lang_config = {
        "python": ["requirements.txt", "pyproject.toml"],
        "javascript": ["package.json"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
    }

    def get_dependencies(self, language: str) -> Optional[str]:
        """Get cached dependency analysis."""
        dep_files = self.lang_config.get(language, [])
        for dep_file in dep_files:
            dep_file_path = self.root / dep_file
            if dep_file_path.exists():
                mtime = dep_file_path.stat().st_mtime
                cache_key = f"{language}:{dep_file_path}:{mtime}"
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result
        return None

    def set_dependencies(self, language: str, result: str):
        """Cache dependency analysis."""
        dep_files = self.lang_config.get(language, [])
        for dep_file in dep_files:
            dep_file_path = self.root / dep_file
            if dep_file_path.exists():
                mtime = dep_file_path.stat().st_mtime
                cache_key = f"{language}:{dep_file_path}:{mtime}"
                self.set(cache_key, result, metadata={"language": language, "file": str(dep_file_path)})
                return
