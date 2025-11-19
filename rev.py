#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent.min — CI/CD Agent powered by Ollama
Minimal autonomous agent with single-gate approval and iterative execution.

Features:
- Single upfront approval gate (no repeated prompts)
- Planning mode: generates comprehensive task checklist
- Execution mode: iteratively completes all checklist items
- Automatic testing after each change
- Code operations: review, edit, add, delete, rename files
- Uses Ollama for local LLM inference

Usage:
    python agent.min "Add error handling to API endpoints"
    python agent.min --repl
"""

import os
import re
import sys
import json
import glob
import shlex
import argparse
import pathlib
import subprocess
import tempfile
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib
import platform
from typing import Dict, Any, List, Optional
from enum import Enum

# Ollama integration
try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

# SSH support (optional)
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    paramiko = None

# Configuration
ROOT = pathlib.Path(os.getcwd()).resolve()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama:latest")
MAX_FILE_BYTES = 5 * 1024 * 1024
READ_RETURN_LIMIT = 80_000
SEARCH_MATCH_LIMIT = 2000
LIST_LIMIT = 2000

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".next", "out", "coverage", ".cache",
    ".venv", "venv", "target"
}

ALLOW_CMDS = {
    "python", "pip", "pytest", "ruff", "black", "isort", "mypy",
    "node", "npm", "npx", "pnpm", "prettier", "eslint", "git", "make"
}

# System information (cached)
_SYSTEM_INFO = None


def _get_system_info_cached() -> Dict[str, Any]:
    """Get cached system information."""
    global _SYSTEM_INFO
    if _SYSTEM_INFO is None:
        _SYSTEM_INFO = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "is_windows": platform.system() == "Windows",
            "is_linux": platform.system() == "Linux",
            "is_macos": platform.system() == "Darwin",
            "shell_type": "powershell" if platform.system() == "Windows" else "bash"
        }
    return _SYSTEM_INFO


# ========== Intelligent Caching System ==========

import time
import pickle
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class CacheEntry:
    """A cache entry with metadata."""
    value: Any
    timestamp: float
    size: int = 0
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class IntelligentCache:
    """
    Intelligent cache with TTL, LRU eviction, and size limits.

    Features:
    - Time-to-live (TTL) based expiration
    - LRU (Least Recently Used) eviction
    - Size-based limits
    - Hit/miss statistics
    - Optional disk persistence
    """

    def __init__(
        self,
        name: str = "cache",
        ttl: float = 300,  # 5 minutes default
        max_entries: int = 1000,
        max_size_bytes: int = 100 * 1024 * 1024,  # 100MB
        persist_path: Optional[pathlib.Path] = None
    ):
        self.name = name
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_size_bytes = max_size_bytes
        self.persist_path = persist_path

        # OrderedDict for LRU tracking
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
            "total_size": 0
        }

        # Load from disk if persistence enabled
        if self.persist_path and self.persist_path.exists():
            self._load_from_disk()

    def _compute_size(self, value: Any) -> int:
        """Estimate size of value in bytes."""
        try:
            if isinstance(value, str):
                return len(value.encode('utf-8'))
            elif isinstance(value, (int, float)):
                return 8
            elif isinstance(value, (list, dict)):
                return len(json.dumps(value).encode('utf-8'))
            else:
                return len(pickle.dumps(value))
        except:
            return 0

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry is expired."""
        if self.ttl <= 0:  # TTL of 0 or negative means never expire
            return False
        return (time.time() - entry.timestamp) > self.ttl

    def _evict_lru(self):
        """Evict least recently used entry."""
        if not self._cache:
            return

        # OrderedDict maintains insertion order, so first item is LRU
        key, entry = self._cache.popitem(last=False)
        self.stats["total_size"] -= entry.size
        self.stats["evictions"] += 1

    def _cleanup_expired(self):
        """Remove all expired entries."""
        expired_keys = [
            k for k, v in self._cache.items()
            if self._is_expired(v)
        ]

        for key in expired_keys:
            entry = self._cache.pop(key)
            self.stats["total_size"] -= entry.size
            self.stats["expirations"] += 1

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                self.stats["misses"] += 1
                return default

            entry = self._cache[key]

            # Check if expired
            if self._is_expired(entry):
                self._cache.pop(key)
                self.stats["total_size"] -= entry.size
                self.stats["expirations"] += 1
                self.stats["misses"] += 1
                return default

            # Update access metadata and move to end (most recently used)
            entry.access_count += 1
            entry.last_access = time.time()
            self._cache.move_to_end(key)

            self.stats["hits"] += 1
            return entry.value

    def set(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None):
        """Set value in cache."""
        with self._lock:
            # Compute size
            size = self._compute_size(value)

            # Remove existing entry if present
            if key in self._cache:
                old_entry = self._cache.pop(key)
                self.stats["total_size"] -= old_entry.size

            # Evict entries if we're over limits
            while (len(self._cache) >= self.max_entries or
                   self.stats["total_size"] + size > self.max_size_bytes):
                if not self._cache:
                    break
                self._evict_lru()

            # Create new entry
            entry = CacheEntry(
                value=value,
                timestamp=time.time(),
                size=size,
                access_count=0,
                last_access=time.time(),
                metadata=metadata or {}
            )

            self._cache[key] = entry
            self.stats["total_size"] += size

            # Periodic cleanup of expired entries
            if len(self._cache) % 100 == 0:
                self._cleanup_expired()

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry."""
        with self._lock:
            if key in self._cache:
                entry = self._cache.pop(key)
                self.stats["total_size"] -= entry.size
                return True
            return False

    def clear(self):
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()
            self.stats["total_size"] = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = (
                self.stats["hits"] / total_requests
                if total_requests > 0 else 0
            )

            return {
                "name": self.name,
                "entries": len(self._cache),
                "total_size_bytes": self.stats["total_size"],
                "total_size_mb": round(self.stats["total_size"] / (1024 * 1024), 2),
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": round(hit_rate * 100, 2),
                "evictions": self.stats["evictions"],
                "expirations": self.stats["expirations"],
                "ttl_seconds": self.ttl,
                "max_entries": self.max_entries,
                "max_size_mb": round(self.max_size_bytes / (1024 * 1024), 2)
            }

    def _save_to_disk(self):
        """Persist cache to disk."""
        if not self.persist_path:
            return

        try:
            with self._lock:
                data = {
                    "cache": dict(self._cache),
                    "stats": self.stats
                }
                self.persist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.persist_path, 'wb') as f:
                    pickle.dump(data, f)
        except Exception as e:
            # Don't fail if persistence fails
            pass

    def _load_from_disk(self):
        """Load cache from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            with open(self.persist_path, 'rb') as f:
                data = pickle.load(f)
                self._cache = OrderedDict(data.get("cache", {}))
                self.stats = data.get("stats", self.stats)

                # Clean up expired entries after loading
                self._cleanup_expired()
        except Exception as e:
            # If loading fails, start fresh
            self._cache.clear()
            self.stats = {
                "hits": 0,
                "misses": 0,
                "evictions": 0,
                "expirations": 0,
                "total_size": 0
            }


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

    def __init__(self, **kwargs):
        super().__init__(name="repo_context", ttl=30, **kwargs)  # 30 seconds TTL

    def get_context(self) -> Optional[str]:
        """Get cached repository context."""
        # Use current git HEAD commit as part of cache key
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=ROOT
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
                cwd=ROOT
            )
            head_commit = proc.stdout.strip() if proc.returncode == 0 else "no-git"
        except:
            head_commit = "no-git"

        cache_key = f"context:{head_commit}"
        self.set(cache_key, context, metadata={"commit": head_commit})


class DependencyTreeCache(IntelligentCache):
    """Cache for dependency analysis results."""

    def __init__(self, **kwargs):
        super().__init__(name="dependency_tree", ttl=600, **kwargs)  # 10 minutes TTL

    def get_dependencies(self, language: str) -> Optional[str]:
        """Get cached dependency analysis."""
        # Check if dependency file has changed
        dep_file_path = None

        if language == "python":
            if (ROOT / "requirements.txt").exists():
                dep_file_path = ROOT / "requirements.txt"
            elif (ROOT / "pyproject.toml").exists():
                dep_file_path = ROOT / "pyproject.toml"
        elif language == "javascript":
            if (ROOT / "package.json").exists():
                dep_file_path = ROOT / "package.json"
        elif language == "rust":
            if (ROOT / "Cargo.toml").exists():
                dep_file_path = ROOT / "Cargo.toml"
        elif language == "go":
            if (ROOT / "go.mod").exists():
                dep_file_path = ROOT / "go.mod"

        if dep_file_path and dep_file_path.exists():
            mtime = dep_file_path.stat().st_mtime
            cache_key = f"{language}:{dep_file_path}:{mtime}"
            return self.get(cache_key)

        return None

    def set_dependencies(self, language: str, result: str):
        """Cache dependency analysis."""
        dep_file_path = None

        if language == "python":
            if (ROOT / "requirements.txt").exists():
                dep_file_path = ROOT / "requirements.txt"
            elif (ROOT / "pyproject.toml").exists():
                dep_file_path = ROOT / "pyproject.toml"
        elif language == "javascript":
            if (ROOT / "package.json").exists():
                dep_file_path = ROOT / "package.json"
        elif language == "rust":
            if (ROOT / "Cargo.toml").exists():
                dep_file_path = ROOT / "Cargo.toml"
        elif language == "go":
            if (ROOT / "go.mod").exists():
                dep_file_path = ROOT / "go.mod"

        if dep_file_path and dep_file_path.exists():
            mtime = dep_file_path.stat().st_mtime
            cache_key = f"{language}:{dep_file_path}:{mtime}"
            self.set(cache_key, result, metadata={"language": language, "file": str(dep_file_path)})


# Global cache instances
_CACHE_DIR = ROOT / ".rev_cache"
_FILE_CACHE = FileContentCache(persist_path=_CACHE_DIR / "file_cache.pkl")
_LLM_CACHE = LLMResponseCache(persist_path=_CACHE_DIR / "llm_cache.pkl")
_REPO_CACHE = RepoContextCache(persist_path=_CACHE_DIR / "repo_cache.pkl")
_DEP_CACHE = DependencyTreeCache(persist_path=_CACHE_DIR / "dep_cache.pkl")


def get_all_cache_stats() -> Dict[str, Any]:
    """Get statistics for all caches."""
    return {
        "file_content": _FILE_CACHE.get_stats(),
        "llm_response": _LLM_CACHE.get_stats(),
        "repo_context": _REPO_CACHE.get_stats(),
        "dependency_tree": _DEP_CACHE.get_stats()
    }


def clear_all_caches():
    """Clear all caches."""
    _FILE_CACHE.clear()
    _LLM_CACHE.clear()
    _REPO_CACHE.clear()
    _DEP_CACHE.clear()


def save_all_caches():
    """Persist all caches to disk."""
    _FILE_CACHE._save_to_disk()
    _LLM_CACHE._save_to_disk()
    _REPO_CACHE._save_to_disk()
    _DEP_CACHE._save_to_disk()


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskLevel(Enum):
    """Risk levels for tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Task:
    """Represents a single task in the execution plan."""
    def __init__(self, description: str, action_type: str = "general", dependencies: List[int] = None):
        self.description = description
        self.action_type = action_type  # edit, add, delete, rename, test, review
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.dependencies = dependencies or []  # List of task indices this task depends on
        self.task_id = None  # Will be set when added to plan

        # Advanced planning features
        self.risk_level = RiskLevel.LOW  # Risk assessment
        self.risk_reasons = []  # List of reasons for risk level
        self.impact_scope = []  # List of files/modules affected
        self.estimated_changes = 0  # Estimated number of lines/files changed
        self.breaking_change = False  # Whether this might break existing functionality
        self.rollback_plan = None  # Rollback instructions if things go wrong
        self.validation_steps = []  # Steps to validate task completion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "action_type": self.action_type,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "dependencies": self.dependencies,
            "task_id": self.task_id,
            "risk_level": self.risk_level.value,
            "risk_reasons": self.risk_reasons,
            "impact_scope": self.impact_scope,
            "estimated_changes": self.estimated_changes,
            "breaking_change": self.breaking_change,
            "rollback_plan": self.rollback_plan,
            "validation_steps": self.validation_steps
        }


class ExecutionPlan:
    """Manages the task checklist for iterative execution with dependency tracking."""
    def __init__(self):
        self.tasks: List[Task] = []
        self.current_index = 0
        self.lock = threading.Lock()  # Thread-safe operations

    def add_task(self, description: str, action_type: str = "general", dependencies: List[int] = None):
        task = Task(description, action_type, dependencies)
        task.task_id = len(self.tasks)
        self.tasks.append(task)

    def get_current_task(self) -> Optional[Task]:
        """Get the next task (for sequential execution compatibility)."""
        if self.current_index < len(self.tasks):
            return self.tasks[self.current_index]
        return None

    def get_executable_tasks(self, max_count: int = 1) -> List[Task]:
        """Get tasks that are ready to execute (all dependencies met)."""
        with self.lock:
            executable = []
            for task in self.tasks:
                if task.status != TaskStatus.PENDING:
                    continue

                # Check if all dependencies are completed
                deps_met = all(
                    self.tasks[dep_id].status == TaskStatus.COMPLETED
                    for dep_id in task.dependencies
                    if dep_id < len(self.tasks)
                )

                if deps_met:
                    executable.append(task)
                    if len(executable) >= max_count:
                        break

            return executable

    def mark_task_in_progress(self, task: Task):
        """Mark a task as in progress."""
        with self.lock:
            task.status = TaskStatus.IN_PROGRESS

    def mark_task_completed(self, task: Task, result: str = None):
        """Mark a specific task as completed."""
        with self.lock:
            task.status = TaskStatus.COMPLETED
            task.result = result

    def mark_task_failed(self, task: Task, error: str):
        """Mark a specific task as failed."""
        with self.lock:
            task.status = TaskStatus.FAILED
            task.error = error

    def mark_completed(self, result: str = None):
        """Legacy method for sequential execution compatibility."""
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.COMPLETED
            self.tasks[self.current_index].result = result
            self.current_index += 1

    def mark_failed(self, error: str):
        """Legacy method for sequential execution compatibility."""
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.FAILED
            self.tasks[self.current_index].error = error

    def is_complete(self) -> bool:
        """Check if all tasks are done (completed or failed)."""
        return all(
            task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            for task in self.tasks
        )

    def has_pending_tasks(self) -> bool:
        """Check if there are any pending or in-progress tasks."""
        return any(
            task.status in [TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
            for task in self.tasks
        )

    def get_summary(self) -> str:
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        in_progress = sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)
        total = len(self.tasks)
        return f"Progress: {completed}/{total} completed, {failed} failed, {in_progress} in progress"

    def analyze_dependencies(self) -> Dict[str, Any]:
        """Analyze task dependencies and create optimal ordering.

        Returns:
            Dict with dependency graph, execution order, and parallel opportunities
        """
        dependency_graph = {}
        reverse_deps = {}  # Which tasks depend on each task

        for task in self.tasks:
            task_id = task.task_id
            dependency_graph[task_id] = task.dependencies.copy()

            # Build reverse dependency map
            for dep_id in task.dependencies:
                if dep_id not in reverse_deps:
                    reverse_deps[dep_id] = []
                reverse_deps[dep_id].append(task_id)

        # Find tasks with no dependencies (can start immediately)
        root_tasks = [t.task_id for t in self.tasks if not t.dependencies]

        # Find critical path (longest chain of dependencies)
        def get_depth(task_id, visited=None):
            if visited is None:
                visited = set()
            if task_id in visited:
                return 0
            visited.add(task_id)

            if task_id >= len(self.tasks):
                return 0

            deps = self.tasks[task_id].dependencies
            if not deps:
                return 1
            return 1 + max(get_depth(dep_id, visited.copy()) for dep_id in deps)

        critical_path = []
        max_depth = 0
        for task in self.tasks:
            depth = get_depth(task.task_id)
            if depth > max_depth:
                max_depth = depth
                critical_path = [task.task_id]

        # Find parallelizable tasks (tasks at same depth level with no interdependencies)
        parallel_groups = []
        processed = set()

        for depth in range(max_depth):
            group = []
            for task in self.tasks:
                if task.task_id in processed:
                    continue
                task_depth = get_depth(task.task_id)
                if task_depth == depth + 1:
                    group.append(task.task_id)
                    processed.add(task.task_id)
            if group:
                parallel_groups.append(group)

        return {
            "dependency_graph": dependency_graph,
            "reverse_dependencies": reverse_deps,
            "root_tasks": root_tasks,
            "critical_path_length": max_depth,
            "parallel_groups": parallel_groups,
            "total_tasks": len(self.tasks),
            "parallelization_potential": sum(len(g) for g in parallel_groups if len(g) > 1)
        }

    def assess_impact(self, task: Task) -> Dict[str, Any]:
        """Assess the potential impact of a task.

        Args:
            task: The task to assess

        Returns:
            Dict with impact analysis including affected files, dependencies, etc.
        """
        impact = {
            "task_id": task.task_id,
            "description": task.description,
            "action_type": task.action_type,
            "affected_files": [],
            "affected_modules": [],
            "dependent_tasks": [],
            "estimated_scope": "unknown"
        }

        # Analyze based on action type
        if task.action_type == "delete":
            impact["estimated_scope"] = "high"
            impact["warning"] = "Destructive operation - data loss possible"
        elif task.action_type in ["edit", "add"]:
            impact["estimated_scope"] = "medium"
        elif task.action_type in ["review", "test"]:
            impact["estimated_scope"] = "low"

        # Find dependent tasks
        for other_task in self.tasks:
            if task.task_id in other_task.dependencies:
                impact["dependent_tasks"].append({
                    "task_id": other_task.task_id,
                    "description": other_task.description
                })

        # Extract file patterns from description
        file_patterns = re.findall(r'(?:in |to |for |file |module )[\w/.-]+\.[a-z]+', task.description.lower())
        impact["affected_files"] = list(set(file_patterns))

        # Estimate affected modules from description
        module_patterns = re.findall(r'(?:in |to |for )(\w+)(?:\s+module| package| service)', task.description.lower())
        impact["affected_modules"] = list(set(module_patterns))

        return impact

    def evaluate_risk(self, task: Task) -> RiskLevel:
        """Evaluate the risk level of a task.

        Args:
            task: The task to evaluate

        Returns:
            RiskLevel enum value
        """
        risk_score = 0
        task.risk_reasons = []

        # Risk factors

        # 1. Action type risk
        action_risks = {
            "delete": 3,
            "edit": 2,
            "add": 1,
            "rename": 2,
            "test": 0,
            "review": 0
        }
        action_risk = action_risks.get(task.action_type, 1)
        risk_score += action_risk

        if action_risk >= 2:
            task.risk_reasons.append(f"Destructive/modifying action: {task.action_type}")

        # 2. Keywords indicating risk
        high_risk_keywords = [
            "database", "schema", "migration", "production", "deploy",
            "auth", "security", "password", "token", "api key",
            "config", "configuration", "settings"
        ]

        desc_lower = task.description.lower()
        for keyword in high_risk_keywords:
            if keyword in desc_lower:
                risk_score += 1
                task.risk_reasons.append(f"High-risk component: {keyword}")
                break

        # 3. Scope of changes
        if any(word in desc_lower for word in ["all", "entire", "whole", "every"]):
            risk_score += 1
            task.risk_reasons.append("Wide scope of changes")

        # 4. Breaking changes indicators
        breaking_indicators = ["breaking", "incompatible", "remove support", "deprecate"]
        if any(indicator in desc_lower for indicator in breaking_indicators):
            risk_score += 2
            task.breaking_change = True
            task.risk_reasons.append("Potentially breaking change")

        # 5. Dependencies
        if len(task.dependencies) > 3:
            risk_score += 1
            task.risk_reasons.append(f"Many dependencies ({len(task.dependencies)})")

        # Map score to risk level
        if risk_score >= 5:
            return RiskLevel.CRITICAL
        elif risk_score >= 3:
            return RiskLevel.HIGH
        elif risk_score >= 1:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def create_rollback_plan(self, task: Task) -> str:
        """Create a rollback plan for a task.

        Args:
            task: The task to create rollback plan for

        Returns:
            String describing rollback procedure
        """
        rollback_steps = []

        # Action-specific rollback
        if task.action_type == "add":
            rollback_steps.append("Delete the newly created files")
            rollback_steps.append("Run: git clean -fd (after review)")

        elif task.action_type == "edit":
            rollback_steps.append("Revert changes using: git checkout -- <files>")
            rollback_steps.append("Or apply inverse patch")

        elif task.action_type == "delete":
            rollback_steps.append("⚠️  CRITICAL: Deleted files cannot be recovered without backup")
            rollback_steps.append("Restore from git history: git checkout HEAD~1 -- <files>")
            rollback_steps.append("Or restore from backup if available")

        elif task.action_type == "rename":
            rollback_steps.append("Rename files back to original names")
            rollback_steps.append("Update imports and references")

        # General rollback steps
        rollback_steps.append("")
        rollback_steps.append("General rollback procedure:")
        rollback_steps.append("1. Stop any running services")
        rollback_steps.append("2. Revert code changes: git reset --hard HEAD")
        rollback_steps.append("3. If changes were committed: git revert <commit-hash>")
        rollback_steps.append("4. Run tests to verify rollback: pytest / npm test")
        rollback_steps.append("5. Review logs for any issues")

        # Database rollback
        if "database" in task.description.lower() or "migration" in task.description.lower():
            rollback_steps.append("")
            rollback_steps.append("Database rollback:")
            rollback_steps.append("1. Run down migration: alembic downgrade -1")
            rollback_steps.append("2. Or restore from database backup")
            rollback_steps.append("3. Verify data integrity")

        return "\n".join(rollback_steps)

    def generate_validation_steps(self, task: Task) -> List[str]:
        """Generate validation steps for a task.

        Args:
            task: The task to generate validation for

        Returns:
            List of validation steps
        """
        steps = []

        # Common validation
        steps.append("Check for syntax errors")

        if task.action_type in ["add", "edit"]:
            steps.append("Run linter to check code quality")
            steps.append("Verify imports and dependencies")

        if task.action_type in ["add", "edit", "delete", "rename"]:
            steps.append("Run test suite: pytest / npm test")
            steps.append("Check for failing tests")

        # Specific validations
        if "api" in task.description.lower():
            steps.append("Test API endpoints manually or with integration tests")
            steps.append("Verify response formats and status codes")

        if "database" in task.description.lower():
            steps.append("Run database migrations")
            steps.append("Verify schema changes")
            steps.append("Check data integrity")

        if "security" in task.description.lower():
            steps.append("Run security scanner: bandit / npm audit")
            steps.append("Check for exposed secrets")

        if task.action_type == "delete":
            steps.append("Verify no references to deleted code remain")
            steps.append("Check import statements")
            steps.append("Run full test suite")

        steps.append("Review git diff for unintended changes")

        return steps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "current_index": self.current_index,
            "summary": self.get_summary()
        }


# ========== File System Utilities ==========

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
    cached_content = _FILE_CACHE.get_file(p)
    if cached_content is not None:
        return cached_content

    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if len(txt) > READ_RETURN_LIMIT:
            txt = txt[:READ_RETURN_LIMIT] + "\n...[truncated]..."

        # Cache the content
        _FILE_CACHE.set_file(p, txt)

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


def git_diff(pathspec: str = ".", staged: bool = False, context: int = 3) -> str:
    """Get git diff for pathspec."""
    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(shlex.quote(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})


def apply_patch(patch: str, dry_run: bool = False) -> str:
    """Apply a unified diff patch."""
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(patch)
        tf.flush()
        tfp = tf.name
    try:
        args = ["git", "apply"]
        if dry_run:
            args.append("--check")
        args.extend(["--3way", "--reject", tfp])
        proc = _run_shell(" ".join(shlex.quote(a) for a in args))
        return json.dumps({
            "rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "dry_run": dry_run
        })
    finally:
        try:
            os.unlink(tfp)
        except Exception:
            pass


def run_cmd(cmd: str, timeout: int = 300) -> str:
    """Run a shell command."""
    parts0 = shlex.split(cmd)[:1]
    ok = parts0 and (parts0[0] in ALLOW_CMDS or parts0[0] == "npx")
    if not ok:
        return json.dumps({"blocked": parts0, "allow": sorted(ALLOW_CMDS)})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:]
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})


def run_tests(cmd: str = "pytest -q", timeout: int = 600) -> str:
    """Run test suite."""
    p0 = shlex.split(cmd)[0]
    if p0 not in ALLOW_CMDS and p0 != "npx":
        return json.dumps({"blocked": p0})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-4000:]
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})


def get_repo_context(commits: int = 6) -> str:
    """Get repository context."""
    # Try to get from cache first
    cached_context = _REPO_CACHE.get_context()
    if cached_context is not None:
        return cached_context

    # Generate context
    st = _run_shell("git status -s")
    lg = _run_shell(f"git log -n {int(commits)} --oneline")
    top = []
    for p in sorted(ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})

    context = json.dumps({
        "status": st.stdout,
        "log": lg.stdout,
        "top_level": top[:100]
    })

    # Cache it
    _REPO_CACHE.set_context(context)

    return context


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
        import shutil
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


# ========== Additional Git Operations ==========

def git_commit(message: str, files: str = ".") -> str:
    """Commit changes to git."""
    try:
        # Add files
        add_result = _run_shell(f"git add {shlex.quote(files)}")
        if add_result.returncode != 0:
            return json.dumps({"error": f"git add failed: {add_result.stderr}"})

        # Commit
        commit_result = _run_shell(f"git commit -m {shlex.quote(message)}")
        if commit_result.returncode != 0:
            return json.dumps({"error": f"git commit failed: {commit_result.stderr}"})

        return json.dumps({
            "committed": True,
            "message": message,
            "output": commit_result.stdout
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_status() -> str:
    """Get git status."""
    try:
        result = _run_shell("git status")
        return json.dumps({
            "status": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_log(count: int = 10, oneline: bool = False) -> str:
    """Get git log."""
    try:
        cmd = f"git log -n {int(count)}"
        if oneline:
            cmd += " --oneline"
        result = _run_shell(cmd)
        return json.dumps({
            "log": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_branch(action: str = "list", branch_name: str = None) -> str:
    """Git branch operations (list, create, switch, current)."""
    try:
        if action == "list":
            result = _run_shell("git branch -a")
            return json.dumps({
                "action": "list",
                "branches": result.stdout,
                "returncode": result.returncode
            })
        elif action == "current":
            result = _run_shell("git branch --show-current")
            return json.dumps({
                "action": "current",
                "branch": result.stdout.strip(),
                "returncode": result.returncode
            })
        elif action == "create" and branch_name:
            result = _run_shell(f"git branch {shlex.quote(branch_name)}")
            return json.dumps({
                "action": "create",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        elif action == "switch" and branch_name:
            result = _run_shell(f"git checkout {shlex.quote(branch_name)}")
            return json.dumps({
                "action": "switch",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        else:
            return json.dumps({"error": f"Invalid action or missing branch_name: {action}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Utility Tools ==========

def install_package(package: str) -> str:
    """Install a Python package."""
    try:
        result = _run_shell(f"pip install {shlex.quote(package)}", timeout=300)
        return json.dumps({
            "installed": package,
            "returncode": result.returncode,
            "output": result.stdout + result.stderr
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def web_fetch(url: str) -> str:
    """Fetch content from a URL."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return json.dumps({
            "url": url,
            "status_code": response.status_code,
            "content": response.text[:50000],  # Limit to 50KB
            "headers": dict(response.headers)
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def execute_python(code: str) -> str:
    """Execute Python code in a safe context."""
    try:
        # Create a restricted namespace
        namespace = {
            '__builtins__': __builtins__,
            'json': json,
            'os': os,
            're': re,
            'pathlib': pathlib
        }

        # Capture output
        import io
        import contextlib
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exec(code, namespace)

        return json.dumps({
            "executed": True,
            "output": output.getvalue()
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def get_system_info() -> str:
    """Get system information (OS, version, architecture, shell type)."""
    try:
        info = _get_system_info_cached()
        return json.dumps(info)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== SSH Remote Execution Support ==========

class SSHConnectionManager:
    """Manage SSH connections to remote hosts."""

    def __init__(self):
        self.connections = {}  # {connection_id: {"client": SSHClient, "host": str, "user": str}}

    def connect(self, host: str, username: str, password: str = None, key_file: str = None,
                port: int = 22) -> Dict[str, Any]:
        """Connect to a remote host via SSH."""
        if not SSH_AVAILABLE:
            return {"error": "SSH not available. Install with: pip install paramiko"}

        connection_id = f"{username}@{host}:{port}"

        try:
            # Close existing connection if any
            if connection_id in self.connections:
                self.disconnect(connection_id)

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect with password or key
            if key_file:
                client.connect(host, port=port, username=username, key_filename=key_file, timeout=10)
            elif password:
                client.connect(host, port=port, username=username, password=password, timeout=10)
            else:
                # Try default SSH keys
                client.connect(host, port=port, username=username, timeout=10)

            self.connections[connection_id] = {
                "client": client,
                "host": host,
                "username": username,
                "port": port,
                "connected_at": json.dumps({"timestamp": "now"})  # Placeholder
            }

            return {
                "connected": True,
                "connection_id": connection_id,
                "host": host,
                "username": username,
                "port": port
            }

        except Exception as e:
            return {"error": f"SSH connection failed: {type(e).__name__}: {e}"}

    def execute(self, connection_id: str, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute a command on a remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

            exit_status = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8', errors='ignore')
            stderr_text = stderr.read().decode('utf-8', errors='ignore')

            return {
                "connection_id": connection_id,
                "command": command,
                "exit_code": exit_status,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "success": exit_status == 0
            }

        except Exception as e:
            return {"error": f"Command execution failed: {type(e).__name__}: {e}"}

    def copy_file_to_remote(self, connection_id: str, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Copy a file to the remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()

            return {
                "copied": True,
                "local_path": local_path,
                "remote_path": remote_path,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"File copy failed: {type(e).__name__}: {e}"}

    def copy_file_from_remote(self, connection_id: str, remote_path: str, local_path: str) -> Dict[str, Any]:
        """Copy a file from the remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            sftp = client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()

            return {
                "copied": True,
                "remote_path": remote_path,
                "local_path": local_path,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"File copy failed: {type(e).__name__}: {e}"}

    def disconnect(self, connection_id: str) -> Dict[str, Any]:
        """Disconnect from a remote host."""
        if connection_id not in self.connections:
            return {"error": f"Connection not found: {connection_id}"}

        try:
            client = self.connections[connection_id]["client"]
            client.close()
            del self.connections[connection_id]

            return {
                "disconnected": True,
                "connection_id": connection_id
            }

        except Exception as e:
            return {"error": f"Disconnect failed: {type(e).__name__}: {e}"}

    def list_connections(self) -> Dict[str, Any]:
        """List all active SSH connections."""
        return {
            "connections": [
                {
                    "connection_id": conn_id,
                    "host": info["host"],
                    "username": info["username"],
                    "port": info["port"]
                }
                for conn_id, info in self.connections.items()
            ]
        }


# Global SSH connection manager
ssh_manager = SSHConnectionManager()


def ssh_connect(host: str, username: str, password: str = None, key_file: str = None, port: int = 22) -> str:
    """Connect to a remote host via SSH."""
    result = ssh_manager.connect(host, username, password, key_file, port)
    return json.dumps(result)


def ssh_exec(connection_id: str, command: str, timeout: int = 30) -> str:
    """Execute a command on a remote host."""
    result = ssh_manager.execute(connection_id, command, timeout)
    return json.dumps(result)


def ssh_copy_to(connection_id: str, local_path: str, remote_path: str) -> str:
    """Copy a file to the remote host."""
    result = ssh_manager.copy_file_to_remote(connection_id, local_path, remote_path)
    return json.dumps(result)


def ssh_copy_from(connection_id: str, remote_path: str, local_path: str) -> str:
    """Copy a file from the remote host."""
    result = ssh_manager.copy_file_from_remote(connection_id, remote_path, local_path)
    return json.dumps(result)


def ssh_disconnect(connection_id: str) -> str:
    """Disconnect from a remote host."""
    result = ssh_manager.disconnect(connection_id)
    return json.dumps(result)


def ssh_list_connections() -> str:
    """List all active SSH connections."""
    result = ssh_manager.list_connections()
    return json.dumps(result)


# ========== File Format Conversion Tools ==========

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
            "converted": str(json_file.relative_to(ROOT)),
            "to": str(yaml_file.relative_to(ROOT)),
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
            "converted": str(yaml_file.relative_to(ROOT)),
            "to": str(json_file.relative_to(ROOT)),
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
        import csv

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
            "converted": str(csv_file.relative_to(ROOT)),
            "to": str(json_file.relative_to(ROOT)),
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
        import csv

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
            "converted": str(json_file.relative_to(ROOT)),
            "to": str(csv_file.relative_to(ROOT)),
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
            "converted": str(env_file.relative_to(ROOT)),
            "to": str(json_file.relative_to(ROOT)),
            "variables": len(data),
            "format": "JSON"
        })
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {type(e).__name__}: {e}"})


# ========== Code Refactoring Utilities ==========

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
            return json.dumps({"error": f"File not found: {file_path}"})

        if language.lower() == "python":
            # Use autoflake if available
            try:
                result = _run_shell(f"autoflake --remove-all-unused-imports --in-place {shlex.quote(str(file))}")
                if result.returncode == 0:
                    return json.dumps({
                        "refactored": str(file.relative_to(ROOT)),
                        "removed": "unused imports",
                        "language": "Python"
                    })
                else:
                    return json.dumps({"error": "autoflake not installed or failed. Run: pip install autoflake"})
            except Exception:
                return json.dumps({"error": "autoflake not installed. Run: pip install autoflake"})

        else:
            return json.dumps({"error": f"Language '{language}' not supported yet"})

    except Exception as e:
        return json.dumps({"error": f"Refactoring failed: {type(e).__name__}: {e}"})


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

        # Find magic numbers (excluding 0, 1, common values)
        magic_numbers = re.findall(r'\b\d{2,}\b', content)
        number_counts = {}
        for num in magic_numbers:
            if num not in ['00', '01', '10', '100']:
                number_counts[num] = number_counts.get(num, 0) + 1

        # Find magic strings (quoted strings used multiple times)
        magic_strings = re.findall(r'["\']([^"\']{4,})["\']', content)
        string_counts = {}
        for s in magic_strings:
            if not s.startswith('import ') and not s.startswith('from '):
                string_counts[s] = string_counts.get(s, 0) + 1

        suggestions = []

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
            "file": str(file.relative_to(ROOT)),
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

        suggestions = []

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
            "file": str(file.relative_to(ROOT)),
            "complex_conditionals": suggestions,
            "count": len(suggestions)
        })

    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {type(e).__name__}: {e}"})


# ========== Dependency Management ==========

def analyze_dependencies(language: str = "auto") -> str:
    """Analyze project dependencies and check for issues.

    Args:
        language: Language/ecosystem (python, javascript, auto)

    Returns:
        JSON string with dependency analysis
    """
    try:
        if language == "auto":
            # Auto-detect from project files
            if (ROOT / "requirements.txt").exists() or (ROOT / "pyproject.toml").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"
            elif (ROOT / "Cargo.toml").exists():
                language = "rust"
            elif (ROOT / "go.mod").exists():
                language = "go"

        # Try to get from cache first
        cached_result = _DEP_CACHE.get_dependencies(language)
        if cached_result is not None:
            return cached_result

        result = {
            "language": language,
            "dependencies": [],
            "issues": []
        }

        if language == "python":
            # Check requirements.txt
            req_file = ROOT / "requirements.txt"
            if req_file.exists():
                content = req_file.read_text(encoding='utf-8')
                deps = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
                result["dependencies"] = deps
                result["count"] = len(deps)
                result["file"] = "requirements.txt"

                # Check for unpinned versions
                unpinned = [d for d in deps if '==' not in d and '>=' not in d]
                if unpinned:
                    result["issues"].append({
                        "type": "unpinned_versions",
                        "count": len(unpinned),
                        "packages": unpinned[:10]
                    })

            # Check for virtual environment
            if not (ROOT / "venv").exists() and not (ROOT / ".venv").exists():
                result["issues"].append({
                    "type": "no_virtual_environment",
                    "message": "No virtual environment detected"
                })

        elif language == "javascript":
            pkg_file = ROOT / "package.json"
            if pkg_file.exists():
                pkg_data = json.loads(pkg_file.read_text(encoding='utf-8'))
                deps = pkg_data.get("dependencies", {})
                dev_deps = pkg_data.get("devDependencies", {})

                result["dependencies"] = list(deps.keys())
                result["dev_dependencies"] = list(dev_deps.keys())
                result["count"] = len(deps) + len(dev_deps)
                result["file"] = "package.json"

                # Check for caret/tilde versions
                risky_versions = []
                for pkg, ver in {**deps, **dev_deps}.items():
                    if ver.startswith('^') or ver.startswith('~'):
                        risky_versions.append(f"{pkg}@{ver}")

                if risky_versions:
                    result["issues"].append({
                        "type": "flexible_versions",
                        "count": len(risky_versions),
                        "message": "Using ^ or ~ version ranges",
                        "packages": risky_versions[:10]
                    })

        # Cache the result
        result_json = json.dumps(result)
        _DEP_CACHE.set_dependencies(language, result_json)

        return result_json

    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {type(e).__name__}: {e}"})


def update_dependencies(language: str = "auto", major: bool = False) -> str:
    """Update project dependencies to latest versions.

    Args:
        language: Language/ecosystem (python, javascript, auto)
        major: Allow major version updates (default: False)

    Returns:
        JSON string with update results
    """
    try:
        if language == "auto":
            if (ROOT / "requirements.txt").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"

        if language == "python":
            # Update using pip-upgrader or similar
            cmd = "pip list --outdated --format=json"
            result = _run_shell(cmd)

            if result.returncode == 0:
                outdated = json.loads(result.stdout) if result.stdout else []
                return json.dumps({
                    "language": "python",
                    "outdated": outdated,
                    "count": len(outdated),
                    "message": "Use 'pip install --upgrade <package>' to update"
                })
            else:
                return json.dumps({"error": "Failed to check outdated packages"})

        elif language == "javascript":
            # Check for npm updates
            cmd = "npm outdated --json"
            result = _run_shell(cmd, timeout=60)

            try:
                outdated = json.loads(result.stdout) if result.stdout else {}
                return json.dumps({
                    "language": "javascript",
                    "outdated": outdated,
                    "count": len(outdated),
                    "message": "Use 'npm update' to update dependencies"
                })
            except:
                return json.dumps({
                    "language": "javascript",
                    "message": "No outdated packages found or npm not available"
                })

        return json.dumps({"error": f"Language '{language}' not supported"})

    except Exception as e:
        return json.dumps({"error": f"Update check failed: {type(e).__name__}: {e}"})


# ========== Security Scanning ==========

def scan_dependencies_vulnerabilities(language: str = "auto") -> str:
    """Scan dependencies for known vulnerabilities.

    Args:
        language: Language/ecosystem (python, javascript, auto)

    Returns:
        JSON string with vulnerability report
    """
    try:
        if language == "auto":
            if (ROOT / "requirements.txt").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"

        result = {
            "language": language,
            "vulnerabilities": [],
            "tool": ""
        }

        if language == "python":
            # Try safety first
            cmd = "safety check --json --file requirements.txt"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode == 0 or proc.stdout:
                try:
                    safety_data = json.loads(proc.stdout) if proc.stdout else []
                    result["tool"] = "safety"
                    result["vulnerabilities"] = safety_data
                    result["count"] = len(safety_data)
                    return json.dumps(result)
                except:
                    pass

            # Try pip-audit as fallback
            cmd = "pip-audit --format json"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode == 0 or proc.stdout:
                try:
                    audit_data = json.loads(proc.stdout) if proc.stdout else {"dependencies": []}
                    result["tool"] = "pip-audit"
                    result["vulnerabilities"] = audit_data.get("dependencies", [])
                    result["count"] = len(audit_data.get("dependencies", []))
                    return json.dumps(result)
                except:
                    pass

            return json.dumps({
                "error": "No security scanning tool available",
                "message": "Install safety or pip-audit: pip install safety pip-audit"
            })

        elif language == "javascript":
            # Use npm audit
            cmd = "npm audit --json"
            proc = _run_shell(cmd, timeout=60)

            try:
                audit_data = json.loads(proc.stdout) if proc.stdout else {}
                vulnerabilities = audit_data.get("vulnerabilities", {})

                result["tool"] = "npm audit"
                result["vulnerabilities"] = vulnerabilities
                result["count"] = len(vulnerabilities)
                result["summary"] = audit_data.get("metadata", {})

                return json.dumps(result)
            except:
                return json.dumps({
                    "language": "javascript",
                    "message": "npm audit not available or no vulnerabilities found"
                })

        return json.dumps({"error": f"Language '{language}' not supported"})

    except Exception as e:
        return json.dumps({"error": f"Vulnerability scan failed: {type(e).__name__}: {e}"})


def scan_code_security(path: str = ".", tool: str = "auto") -> str:
    """Perform static security analysis on code.

    Args:
        path: Path to scan (file or directory)
        tool: Security tool to use (bandit, semgrep, auto)

    Returns:
        JSON string with security findings
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        findings = []
        tools_used = []

        # Python: Use bandit
        if tool in ["auto", "bandit"]:
            cmd = f"bandit -r {shlex.quote(str(scan_path))} -f json"
            proc = _run_shell(cmd, timeout=120)

            if proc.returncode != 127:  # Command exists
                try:
                    bandit_data = json.loads(proc.stdout) if proc.stdout else {}
                    results = bandit_data.get("results", [])
                    findings.extend(results)
                    tools_used.append("bandit")
                except:
                    pass

        # Multi-language: Use semgrep
        if tool in ["auto", "semgrep"]:
            cmd = f"semgrep --config=auto --json {shlex.quote(str(scan_path))}"
            proc = _run_shell(cmd, timeout=120)

            if proc.returncode != 127:
                try:
                    semgrep_data = json.loads(proc.stdout) if proc.stdout else {}
                    results = semgrep_data.get("results", [])
                    findings.extend(results)
                    tools_used.append("semgrep")
                except:
                    pass

        if not tools_used:
            return json.dumps({
                "error": "No security scanning tools available",
                "message": "Install bandit (Python) or semgrep: pip install bandit semgrep"
            })

        # Categorize by severity
        by_severity = {}
        for finding in findings:
            severity = finding.get("severity", "MEDIUM").upper()
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(finding)

        return json.dumps({
            "scanned": str(scan_path.relative_to(ROOT)),
            "tools": tools_used,
            "findings": findings,
            "count": len(findings),
            "by_severity": {k: len(v) for k, v in by_severity.items()}
        })

    except Exception as e:
        return json.dumps({"error": f"Security scan failed: {type(e).__name__}: {e}"})


def detect_secrets(path: str = ".") -> str:
    """Scan for accidentally committed secrets and credentials.

    Args:
        path: Path to scan

    Returns:
        JSON string with detected secrets
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Try detect-secrets tool
        cmd = f"detect-secrets scan {shlex.quote(str(scan_path))}"
        proc = _run_shell(cmd, timeout=60)

        if proc.returncode == 127:
            return json.dumps({
                "error": "detect-secrets not installed",
                "message": "Install with: pip install detect-secrets"
            })

        try:
            secrets_data = json.loads(proc.stdout) if proc.stdout else {}
            results = secrets_data.get("results", {})

            # Count total secrets
            total_secrets = sum(len(secrets) for secrets in results.values())

            # Get summary by file
            by_file = {}
            for file_path, secrets in results.items():
                by_file[file_path] = len(secrets)

            return json.dumps({
                "scanned": str(scan_path.relative_to(ROOT)),
                "tool": "detect-secrets",
                "secrets_found": total_secrets,
                "files_with_secrets": len(results),
                "by_file": by_file
            })
        except:
            return json.dumps({
                "scanned": str(scan_path.relative_to(ROOT)),
                "message": "No secrets detected or scan completed successfully"
            })

    except Exception as e:
        return json.dumps({"error": f"Secret detection failed: {type(e).__name__}: {e}"})


def check_license_compliance(path: str = ".") -> str:
    """Check dependency licenses for compliance issues.

    Args:
        path: Project path

    Returns:
        JSON string with license information
    """
    try:
        # Python: Use pip-licenses
        if (ROOT / "requirements.txt").exists():
            cmd = "pip-licenses --format=json"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode != 127:
                try:
                    licenses = json.loads(proc.stdout) if proc.stdout else []

                    # Flag potentially problematic licenses
                    restricted = ["GPL-3.0", "AGPL-3.0", "GPL-2.0"]
                    issues = []

                    for pkg in licenses:
                        license_name = pkg.get("License", "")
                        if any(r in license_name for r in restricted):
                            issues.append({
                                "package": pkg.get("Name"),
                                "license": license_name,
                                "issue": "Restrictive license"
                            })

                    return json.dumps({
                        "language": "python",
                        "tool": "pip-licenses",
                        "total_packages": len(licenses),
                        "licenses": licenses,
                        "compliance_issues": issues,
                        "issue_count": len(issues)
                    })
                except:
                    pass

        # JavaScript: Use license-checker
        if (ROOT / "package.json").exists():
            cmd = "npx license-checker --json"
            proc = _run_shell(cmd, timeout=60)

            try:
                licenses = json.loads(proc.stdout) if proc.stdout else {}

                restricted = ["GPL-3.0", "AGPL-3.0", "GPL-2.0"]
                issues = []

                for pkg_name, pkg_info in licenses.items():
                    license_name = pkg_info.get("licenses", "")
                    if any(r in str(license_name) for r in restricted):
                        issues.append({
                            "package": pkg_name,
                            "license": license_name,
                            "issue": "Restrictive license"
                        })

                return json.dumps({
                    "language": "javascript",
                    "tool": "license-checker",
                    "total_packages": len(licenses),
                    "compliance_issues": issues,
                    "issue_count": len(issues)
                })
            except:
                pass

        return json.dumps({
            "message": "No license checking tool available",
            "install": "pip install pip-licenses (Python) or npm install license-checker (JavaScript)"
        })

    except Exception as e:
        return json.dumps({"error": f"License check failed: {type(e).__name__}: {e}"})


# ========== Cache Management ==========

def get_cache_stats() -> str:
    """Get statistics for all caches.

    Returns:
        JSON string with cache statistics including hit rates, sizes, and performance metrics
    """
    try:
        stats = get_all_cache_stats()
        return json.dumps(stats, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to get cache stats: {type(e).__name__}: {e}"})


def clear_caches(cache_name: str = "all") -> str:
    """Clear one or all caches.

    Args:
        cache_name: Name of cache to clear (file_content, llm_response, repo_context, dependency_tree, or all)

    Returns:
        JSON string with result
    """
    try:
        if cache_name == "all":
            clear_all_caches()
            return json.dumps({
                "cleared": "all",
                "message": "All caches cleared successfully"
            })
        elif cache_name == "file_content":
            _FILE_CACHE.clear()
            return json.dumps({
                "cleared": "file_content",
                "message": "File content cache cleared"
            })
        elif cache_name == "llm_response":
            _LLM_CACHE.clear()
            return json.dumps({
                "cleared": "llm_response",
                "message": "LLM response cache cleared"
            })
        elif cache_name == "repo_context":
            _REPO_CACHE.clear()
            return json.dumps({
                "cleared": "repo_context",
                "message": "Repository context cache cleared"
            })
        elif cache_name == "dependency_tree":
            _DEP_CACHE.clear()
            return json.dumps({
                "cleared": "dependency_tree",
                "message": "Dependency tree cache cleared"
            })
        else:
            return json.dumps({
                "error": f"Unknown cache: {cache_name}",
                "valid_caches": ["file_content", "llm_response", "repo_context", "dependency_tree", "all"]
            })
    except Exception as e:
        return json.dumps({"error": f"Failed to clear cache: {type(e).__name__}: {e}"})


def persist_caches() -> str:
    """Save all caches to disk for persistence across sessions.

    Returns:
        JSON string with result
    """
    try:
        save_all_caches()
        return json.dumps({
            "persisted": True,
            "message": "All caches saved to disk successfully",
            "cache_dir": str(_CACHE_DIR)
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to persist caches: {type(e).__name__}: {e}"})


# ========== MCP (Model Context Protocol) Support ==========

class MCPClient:
    """Client for Model Context Protocol servers."""

    def __init__(self):
        self.servers = {}
        self.tools = {}

    def add_server(self, name: str, command: str, args: List[str] = None) -> Dict[str, Any]:
        """Add an MCP server."""
        try:
            # Store server configuration
            self.servers[name] = {
                "command": command,
                "args": args or [],
                "connected": False
            }
            return {"added": name, "command": command}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def list_servers(self) -> Dict[str, Any]:
        """List configured MCP servers."""
        return {"servers": list(self.servers.keys())}

    def call_mcp_tool(self, server: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on an MCP server."""
        try:
            if server not in self.servers:
                return {"error": f"Server not found: {server}"}

            # For now, return a placeholder
            # Full MCP implementation would use stdio communication
            return {
                "mcp_call": True,
                "server": server,
                "tool": tool,
                "note": "MCP server communication would happen here"
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


# Global MCP client instance
mcp_client = MCPClient()


def mcp_add_server(name: str, command: str, args: str = "") -> str:
    """Add an MCP server."""
    arg_list = args.split() if args else []
    result = mcp_client.add_server(name, command, arg_list)
    return json.dumps(result)


def mcp_list_servers() -> str:
    """List MCP servers."""
    result = mcp_client.list_servers()
    return json.dumps(result)


def mcp_call_tool(server: str, tool: str, arguments: str = "{}") -> str:
    """Call an MCP tool."""
    try:
        args_dict = json.loads(arguments)
        result = mcp_client.call_mcp_tool(server, tool, args_dict)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON arguments: {e}"})


# ========== Ollama Integration ==========

# Debug mode - set to True to see API requests/responses
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"

def ollama_chat(messages: List[Dict[str, str]], tools: List[Dict] = None) -> Dict[str, Any]:
    """Send chat request to Ollama.

    Note: Ollama's tool/function calling support varies by model and version.
    This implementation sends tools in OpenAI format but gracefully falls back
    if the model doesn't support them.

    For cloud models (ending with -cloud), this handles authentication flow.
    """
    # Try to get cached response first
    cached_response = _LLM_CACHE.get_response(messages, tools)
    if cached_response is not None:
        if OLLAMA_DEBUG:
            print("[DEBUG] Using cached LLM response")
        return cached_response

    url = f"{OLLAMA_BASE_URL}/api/chat"

    # Build base payload
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False
    }

    # Try with tools first if provided
    if tools:
        payload["tools"] = tools

    if OLLAMA_DEBUG:
        print(f"[DEBUG] Ollama request to {url}")
        print(f"[DEBUG] Model: {OLLAMA_MODEL}")
        print(f"[DEBUG] Messages: {json.dumps(messages, indent=2)}")
        if tools:
            print(f"[DEBUG] Tools: {len(tools)} tools provided")

    # Retry with increasing timeouts: 10m, 20m, 30m
    max_retries = 3
    base_timeout = 600  # 10 minutes

    # Track if we've already prompted for auth in this call
    auth_prompted = False

    for attempt in range(max_retries):
        timeout = base_timeout * (attempt + 1)  # 600, 1200, 1800

        if OLLAMA_DEBUG and attempt > 0:
            print(f"[DEBUG] Retry attempt {attempt + 1}/{max_retries} with timeout {timeout}s ({timeout // 60}m)")

        try:
            resp = requests.post(url, json=payload, timeout=timeout)

            if OLLAMA_DEBUG:
                print(f"[DEBUG] Response status: {resp.status_code}")
                print(f"[DEBUG] Response: {resp.text[:500]}")

            # Handle 401 Unauthorized for cloud models
            if resp.status_code == 401:
                try:
                    error_data = resp.json()
                    signin_url = error_data.get("signin_url")

                    if signin_url and not auth_prompted:
                        auth_prompted = True
                        print("\n" + "=" * 60)
                        print("OLLAMA CLOUD AUTHENTICATION REQUIRED")
                        print("=" * 60)
                        print(f"\nModel '{OLLAMA_MODEL}' requires authentication.")
                        print(f"\nTo authenticate:")
                        print(f"1. Visit this URL in your browser:")
                        print(f"   {signin_url}")
                        print(f"\n2. Sign in with your Ollama account")
                        print(f"3. Authorize this device")
                        print("\n" + "=" * 60)

                        # Wait for user to authenticate
                        try:
                            input("\nPress Enter after completing authentication, or Ctrl+C to cancel...")
                        except KeyboardInterrupt:
                            return {"error": "Authentication cancelled by user"}

                        # Retry the request after authentication
                        print("\nRetrying request...")
                        continue
                    else:
                        # If we've already prompted or no signin_url, return error
                        return {"error": f"Ollama API error: {resp.status_code} {resp.reason} - {resp.text}"}

                except json.JSONDecodeError:
                    return {"error": f"Ollama API error: {resp.status_code} {resp.reason}"}

            # If we get a 400 and we sent tools, try again without tools
            if resp.status_code == 400 and tools:
                if OLLAMA_DEBUG:
                    print("[DEBUG] Got 400 with tools, retrying without tools...")

                # Retry without tools
                payload_no_tools = {
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False
                }
                resp = requests.post(url, json=payload_no_tools, timeout=timeout)

            resp.raise_for_status()
            response = resp.json()

            # Cache the successful response
            _LLM_CACHE.set_response(messages, response, tools)

            return response

        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Request timed out after {timeout}s, will retry with longer timeout...")
                continue  # Retry with longer timeout
            else:
                return {"error": f"Ollama API timeout after {max_retries} attempts (final timeout: {timeout}s)"}

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = f" - {resp.text}"
            except:
                pass
            return {"error": f"Ollama API error: {e}{error_detail}"}

        except Exception as e:
            return {"error": f"Ollama API error: {e}"}


# ========== Tool Definitions ==========

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files matching glob pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search code for pattern (regex)",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "include": {"type": "string", "description": "File pattern to include"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Get unified diff for changes",
            "parameters": {
                "type": "object",
                "properties": {
                    "pathspec": {"type": "string", "description": "Path to diff (default: .)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff patch",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "Unified diff patch"},
                    "dry_run": {"type": "boolean", "description": "Check without applying"}
                },
                "required": ["patch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_cmd",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run test suite",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Test command (default: pytest -q)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_repo_context",
            "description": "Get repository context (status, log, structure)",
            "parameters": {
                "type": "object",
                "properties": {
                    "commits": {"type": "integer", "description": "Number of recent commits"}
                }
            }
        }
    },
    # File operations
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file to delete"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"}
                },
                "required": ["src", "dest"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_to_file",
            "description": "Append content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "content": {"type": "string", "description": "Content to append"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Find and replace text within a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "find": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "regex": {"type": "boolean", "description": "Use regex matching"}
                },
                "required": ["path", "find", "replace"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "Get file metadata (size, modified time, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "copy_file",
            "description": "Copy a file to a new location",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"}
                },
                "required": ["src", "dest"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_exists",
            "description": "Check if a file or directory exists",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to check"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": "Read specific line range from a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "start": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end": {"type": "integer", "description": "End line number (inclusive)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tree_view",
            "description": "Generate a tree view of directory structure",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: .)"},
                    "max_depth": {"type": "integer", "description": "Maximum depth (default: 3)"},
                    "max_files": {"type": "integer", "description": "Maximum files to show (default: 100)"}
                }
            }
        }
    },
    # Git operations
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit changes to git",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "files": {"type": "string", "description": "Files to add (default: .)"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git status",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Get git log",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of commits (default: 10)"},
                    "oneline": {"type": "boolean", "description": "Use oneline format"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "Git branch operations (list, create, switch, current)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: list, current, create, or switch"},
                    "branch_name": {"type": "string", "description": "Branch name (for create/switch)"}
                }
            }
        }
    },
    # Utility tools
    {
        "type": "function",
        "function": {
            "name": "install_package",
            "description": "Install a Python package using pip",
            "parameters": {
                "type": "object",
                "properties": {
                    "package": {"type": "string", "description": "Package name"}
                },
                "required": ["package"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get system information (OS, version, architecture, shell type)",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    # SSH remote execution tools
    {
        "type": "function",
        "function": {
            "name": "ssh_connect",
            "description": "Connect to a remote host via SSH",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Remote host address"},
                    "username": {"type": "string", "description": "SSH username"},
                    "password": {"type": "string", "description": "SSH password (optional)"},
                    "key_file": {"type": "string", "description": "Path to SSH key file (optional)"},
                    "port": {"type": "integer", "description": "SSH port (default: 22)"}
                },
                "required": ["host", "username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_exec",
            "description": "Execute a command on a remote host via SSH",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "SSH connection ID (username@host:port)"},
                    "command": {"type": "string", "description": "Command to execute"},
                    "timeout": {"type": "integer", "description": "Command timeout in seconds (default: 30)"}
                },
                "required": ["connection_id", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_copy_to",
            "description": "Copy a file to the remote host via SFTP",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "SSH connection ID"},
                    "local_path": {"type": "string", "description": "Local file path"},
                    "remote_path": {"type": "string", "description": "Remote file path"}
                },
                "required": ["connection_id", "local_path", "remote_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_copy_from",
            "description": "Copy a file from the remote host via SFTP",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "SSH connection ID"},
                    "remote_path": {"type": "string", "description": "Remote file path"},
                    "local_path": {"type": "string", "description": "Local file path"}
                },
                "required": ["connection_id", "remote_path", "local_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_disconnect",
            "description": "Disconnect from a remote host",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "SSH connection ID"}
                },
                "required": ["connection_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_list_connections",
            "description": "List all active SSH connections",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    # MCP tools
    {
        "type": "function",
        "function": {
            "name": "mcp_add_server",
            "description": "Add an MCP (Model Context Protocol) server",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Server name"},
                    "command": {"type": "string", "description": "Command to run server"},
                    "args": {"type": "string", "description": "Space-separated arguments"}
                },
                "required": ["name", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_list_servers",
            "description": "List configured MCP servers",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call_tool",
            "description": "Call a tool on an MCP server",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "Server name"},
                    "tool": {"type": "string", "description": "Tool name"},
                    "arguments": {"type": "string", "description": "JSON-encoded arguments"}
                },
                "required": ["server", "tool"]
            }
        }
    },
    # File conversion utilities
    {
        "type": "function",
        "function": {
            "name": "convert_json_to_yaml",
            "description": "Convert JSON file to YAML format",
            "parameters": {
                "type": "object",
                "properties": {
                    "json_path": {"type": "string", "description": "Path to JSON file"},
                    "yaml_path": {"type": "string", "description": "Output YAML path (optional)"}
                },
                "required": ["json_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_yaml_to_json",
            "description": "Convert YAML file to JSON format",
            "parameters": {
                "type": "object",
                "properties": {
                    "yaml_path": {"type": "string", "description": "Path to YAML file"},
                    "json_path": {"type": "string", "description": "Output JSON path (optional)"}
                },
                "required": ["yaml_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_csv_to_json",
            "description": "Convert CSV file to JSON array",
            "parameters": {
                "type": "object",
                "properties": {
                    "csv_path": {"type": "string", "description": "Path to CSV file"},
                    "json_path": {"type": "string", "description": "Output JSON path (optional)"}
                },
                "required": ["csv_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_json_to_csv",
            "description": "Convert JSON array to CSV file",
            "parameters": {
                "type": "object",
                "properties": {
                    "json_path": {"type": "string", "description": "Path to JSON file"},
                    "csv_path": {"type": "string", "description": "Output CSV path (optional)"}
                },
                "required": ["json_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_env_to_json",
            "description": "Convert .env file to JSON format",
            "parameters": {
                "type": "object",
                "properties": {
                    "env_path": {"type": "string", "description": "Path to .env file"},
                    "json_path": {"type": "string", "description": "Output JSON path (optional)"}
                },
                "required": ["env_path"]
            }
        }
    },
    # Code refactoring utilities
    {
        "type": "function",
        "function": {
            "name": "remove_unused_imports",
            "description": "Remove unused imports from Python files (requires autoflake)",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file"},
                    "language": {"type": "string", "description": "Language (default: python)"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_constants",
            "description": "Identify magic numbers and strings that should be constants",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file"},
                    "threshold": {"type": "integer", "description": "Minimum occurrences (default: 3)"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simplify_conditionals",
            "description": "Find overly complex conditional statements",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file"}
                },
                "required": ["file_path"]
            }
        }
    },
    # Dependency management
    {
        "type": "function",
        "function": {
            "name": "analyze_dependencies",
            "description": "Analyze project dependencies and check for issues",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Language (auto/python/javascript)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_dependencies",
            "description": "Check for outdated dependencies",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Language (auto/python/javascript)"},
                    "major": {"type": "boolean", "description": "Include major version updates"}
                }
            }
        }
    },
    # Security scanning
    {
        "type": "function",
        "function": {
            "name": "scan_dependencies_vulnerabilities",
            "description": "Scan dependencies for known vulnerabilities (requires safety/pip-audit/npm)",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Language (auto/python/javascript)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_code_security",
            "description": "Perform static code security analysis (requires bandit/semgrep)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to scan (default: .)"},
                    "tool": {"type": "string", "description": "Tool to use (auto/bandit/semgrep)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detect_secrets",
            "description": "Scan for accidentally committed secrets (requires detect-secrets)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to scan (default: .)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_license_compliance",
            "description": "Check dependency licenses for compliance issues",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to scan (default: .)"}
                }
            }
        }
    },
    # Cache management
    {
        "type": "function",
        "function": {
            "name": "get_cache_stats",
            "description": "Get statistics for all caches including hit rates and sizes",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_caches",
            "description": "Clear one or all caches to free memory",
            "parameters": {
                "type": "object",
                "properties": {
                    "cache_name": {"type": "string", "description": "Cache to clear (file_content, llm_response, repo_context, dependency_tree, or all)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "persist_caches",
            "description": "Save all caches to disk for persistence across sessions",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# ========== Tool Execution ==========

def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool and return result."""
    print(f"  → Executing: {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")

    try:
        # Original tools
        if name == "read_file":
            return read_file(args["path"])
        elif name == "write_file":
            return write_file(args["path"], args["content"])
        elif name == "list_dir":
            return list_dir(args.get("pattern", "**/*"))
        elif name == "search_code":
            return search_code(args["pattern"], args.get("include", "**/*"))
        elif name == "git_diff":
            return git_diff(args.get("pathspec", "."))
        elif name == "apply_patch":
            return apply_patch(args["patch"], args.get("dry_run", False))
        elif name == "run_cmd":
            return run_cmd(args["cmd"], args.get("timeout", 300))
        elif name == "run_tests":
            return run_tests(args.get("cmd", "pytest -q"), args.get("timeout", 600))
        elif name == "get_repo_context":
            return get_repo_context(args.get("commits", 6))

        # File operations
        elif name == "delete_file":
            return delete_file(args["path"])
        elif name == "move_file":
            return move_file(args["src"], args["dest"])
        elif name == "append_to_file":
            return append_to_file(args["path"], args["content"])
        elif name == "replace_in_file":
            return replace_in_file(args["path"], args["find"], args["replace"], args.get("regex", False))
        elif name == "create_directory":
            return create_directory(args["path"])
        elif name == "get_file_info":
            return get_file_info(args["path"])
        elif name == "copy_file":
            return copy_file(args["src"], args["dest"])
        elif name == "file_exists":
            return file_exists(args["path"])
        elif name == "read_file_lines":
            return read_file_lines(args["path"], args.get("start", 1), args.get("end"))
        elif name == "tree_view":
            return tree_view(args.get("path", "."), args.get("max_depth", 3), args.get("max_files", 100))

        # Git operations
        elif name == "git_commit":
            return git_commit(args["message"], args.get("files", "."))
        elif name == "git_status":
            return git_status()
        elif name == "git_log":
            return git_log(args.get("count", 10), args.get("oneline", False))
        elif name == "git_branch":
            return git_branch(args.get("action", "list"), args.get("branch_name"))

        # Utility tools
        elif name == "install_package":
            return install_package(args["package"])
        elif name == "web_fetch":
            return web_fetch(args["url"])
        elif name == "execute_python":
            return execute_python(args["code"])
        elif name == "get_system_info":
            return get_system_info()

        # SSH remote execution tools
        elif name == "ssh_connect":
            return ssh_connect(args["host"], args["username"], args.get("password"),
                             args.get("key_file"), args.get("port", 22))
        elif name == "ssh_exec":
            return ssh_exec(args["connection_id"], args["command"], args.get("timeout", 30))
        elif name == "ssh_copy_to":
            return ssh_copy_to(args["connection_id"], args["local_path"], args["remote_path"])
        elif name == "ssh_copy_from":
            return ssh_copy_from(args["connection_id"], args["remote_path"], args["local_path"])
        elif name == "ssh_disconnect":
            return ssh_disconnect(args["connection_id"])
        elif name == "ssh_list_connections":
            return ssh_list_connections()

        # MCP tools
        elif name == "mcp_add_server":
            return mcp_add_server(args["name"], args["command"], args.get("args", ""))
        elif name == "mcp_list_servers":
            return mcp_list_servers()
        elif name == "mcp_call_tool":
            return mcp_call_tool(args["server"], args["tool"], args.get("arguments", "{}"))

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Planning Mode ==========

PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

Your job is to:
1. Understand the user's request
2. Analyze the repository structure
3. Create a comprehensive, ordered checklist of tasks

IMPORTANT - System Context:
You will be provided with the operating system information. Use this to:
- Choose appropriate shell commands (bash for Linux/Mac, PowerShell for Windows)
- Select platform-specific tools and utilities
- Use correct path separators and file conventions
- Adapt commands to the target environment

Break down the work into atomic tasks:
- Review: Analyze existing code
- Edit: Modify existing files
- Add: Create new files
- Delete: Remove files
- Rename: Move/rename files
- Test: Run tests to validate changes

Return ONLY a JSON array of tasks in this format:
[
  {"description": "Review current API endpoint structure", "action_type": "review"},
  {"description": "Add error handling to /api/users endpoint", "action_type": "edit"},
  {"description": "Create tests for error cases", "action_type": "add"},
  {"description": "Run test suite to validate changes", "action_type": "test"}
]

Be thorough but concise. Each task should be independently executable."""


def planning_mode(user_request: str, enable_advanced_analysis: bool = True) -> ExecutionPlan:
    """Generate execution plan from user request with advanced analysis.

    Args:
        user_request: The user's task request
        enable_advanced_analysis: Enable dependency, impact, and risk analysis

    Returns:
        ExecutionPlan with comprehensive task breakdown and analysis
    """
    print("=" * 60)
    print("PLANNING MODE")
    print("=" * 60)

    # Get system and repository context
    print("→ Analyzing system and repository...")
    sys_info = _get_system_info_cached()
    context = get_repo_context()

    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user", "content": f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

Repository context:
{context}

User request:
{user_request}

Generate a comprehensive execution plan."""}
    ]

    print("→ Generating execution plan...")
    response = ollama_chat(messages)

    if "error" in response:
        print(f"Error: {response['error']}")
        sys.exit(1)

    # Parse the plan
    plan = ExecutionPlan()
    try:
        content = response.get("message", {}).get("content", "")
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            tasks_data = json.loads(json_match.group(0))
            for task_data in tasks_data:
                plan.add_task(
                    task_data.get("description", "Unknown task"),
                    task_data.get("action_type", "general")
                )
        else:
            print("Warning: Could not parse JSON plan, using fallback")
            plan.add_task(user_request, "general")
    except Exception as e:
        print(f"Warning: Error parsing plan: {e}")
        plan.add_task(user_request, "general")

    # Advanced planning analysis
    if enable_advanced_analysis and len(plan.tasks) > 0:
        print("\n→ Performing advanced planning analysis...")

        # 1. Dependency Analysis
        print("  ├─ Analyzing task dependencies...")
        dep_analysis = plan.analyze_dependencies()

        # 2. Risk Evaluation for each task
        print("  ├─ Evaluating risks...")
        high_risk_tasks = []
        for task in plan.tasks:
            task.risk_level = plan.evaluate_risk(task)
            if task.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                high_risk_tasks.append(task)

        # 3. Impact Assessment
        print("  ├─ Assessing impact scope...")
        for task in plan.tasks:
            impact = plan.assess_impact(task)
            task.impact_scope = impact.get("affected_files", []) + impact.get("affected_modules", [])
            task.estimated_changes = len(task.impact_scope)

        # 4. Generate Rollback Plans for risky tasks
        print("  ├─ Creating rollback plans...")
        for task in plan.tasks:
            if task.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]:
                task.rollback_plan = plan.create_rollback_plan(task)

        # 5. Generate Validation Steps
        print("  └─ Generating validation steps...")
        for task in plan.tasks:
            task.validation_steps = plan.generate_validation_steps(task)

    # Display plan
    print("\n" + "=" * 60)
    print("EXECUTION PLAN")
    print("=" * 60)
    for i, task in enumerate(plan.tasks, 1):
        risk_emoji = {
            RiskLevel.LOW: "🟢",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.HIGH: "🟠",
            RiskLevel.CRITICAL: "🔴"
        }.get(task.risk_level, "⚪")

        print(f"{i}. [{task.action_type.upper()}] {task.description}")

        if enable_advanced_analysis:
            print(f"   Risk: {risk_emoji} {task.risk_level.value.upper()}", end="")
            if task.risk_reasons:
                print(f" ({task.risk_reasons[0]})")
            else:
                print()

            if task.dependencies:
                dep_desc = [f"#{d+1}" for d in task.dependencies]
                print(f"   Depends on: {', '.join(dep_desc)}")

            if task.breaking_change:
                print("   ⚠️  Warning: Potentially breaking change")

    print("=" * 60)

    # Display analysis summary
    if enable_advanced_analysis:
        print("\n" + "=" * 60)
        print("PLANNING ANALYSIS SUMMARY")
        print("=" * 60)

        # Risk summary
        risk_counts = {}
        for level in RiskLevel:
            count = sum(1 for t in plan.tasks if t.risk_level == level)
            if count > 0:
                risk_counts[level] = count

        print(f"Total tasks: {len(plan.tasks)}")
        print(f"Risk distribution:")
        for level, count in sorted(risk_counts.items(), key=lambda x: ["low", "medium", "high", "critical"].index(x[0].value)):
            emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}[level.value]
            print(f"  {emoji} {level.value.upper()}: {count}")

        # Dependency insights
        if dep_analysis["parallelization_potential"] > 0:
            print(f"\n⚡ Parallelization potential: {dep_analysis['parallelization_potential']} tasks can run concurrently")
            print(f"   Critical path length: {dep_analysis['critical_path_length']} steps")

        # High-risk warnings
        critical_tasks = [t for t in plan.tasks if t.risk_level == RiskLevel.CRITICAL]
        high_risk_tasks = [t for t in plan.tasks if t.risk_level == RiskLevel.HIGH]

        if critical_tasks:
            print(f"\n🔴 CRITICAL: {len(critical_tasks)} high-risk task(s) require extra caution")
            for task in critical_tasks:
                print(f"   - Task #{task.task_id + 1}: {task.description[:60]}...")
                if task.rollback_plan:
                    print(f"     Rollback plan available")

        if high_risk_tasks:
            print(f"\n🟠 WARNING: {len(high_risk_tasks)} task(s) have elevated risk")

        print("=" * 60)

    return plan


# ========== Execution Mode ==========

EXECUTION_SYSTEM = """You are an autonomous CI/CD agent executing tasks.

IMPORTANT - System Context:
You will be provided with OS information. Use this to:
- Choose correct shell commands (bash for Linux/Mac, PowerShell/cmd for Windows)
- Select platform-specific tools and file paths
- Use appropriate path separators (/ for Unix, \\ for Windows)
- Adapt commands to the target environment

You have these tools available:
- read_file: Read file contents
- write_file: Create or modify files
- list_dir: List files matching pattern
- search_code: Search code with regex
- git_diff: View current changes
- apply_patch: Apply unified diff patches
- run_cmd: Execute shell commands (use shell-appropriate syntax)
- run_tests: Run test suite
- get_repo_context: Get repo status
- get_system_info: Get OS, version, architecture, and shell type

Work methodically:
1. Understand the current task
2. Gather necessary information (read files, search code)
3. Make changes (edit, add, or delete files)
4. Validate changes (run tests)
5. Report completion

Use unified diffs (apply_patch) for editing files. Always preserve formatting.
After making changes, run tests to ensure nothing broke.

Be concise. Execute the task and report success or failure."""


# Destructive operations that require confirmation
SCARY_OPERATIONS = {
    "keywords": ["delete", "remove", "rm ", "clean", "reset", "force", "destroy", "drop", "truncate"],
    "git_commands": ["reset --hard", "clean -f", "clean -fd", "push --force", "push -f"],
    "action_types": ["delete"]  # Task action types that are destructive
}


def is_scary_operation(tool_name: str, args: Dict[str, Any], action_type: str = "") -> tuple[bool, str]:
    """
    Check if an operation is potentially destructive and requires confirmation.
    Returns: (is_scary: bool, reason: str)
    """
    # Check action type
    if action_type in SCARY_OPERATIONS["action_types"]:
        return True, f"Destructive action type: {action_type}"

    # Check for file deletion
    if tool_name == "run_cmd":
        cmd = args.get("cmd", "").lower()

        # Check for dangerous git commands
        for git_cmd in SCARY_OPERATIONS["git_commands"]:
            if git_cmd in cmd:
                return True, f"Dangerous git command: {git_cmd}"

        # Check for scary keywords
        for keyword in SCARY_OPERATIONS["keywords"]:
            if keyword in cmd:
                return True, f"Potentially destructive command contains: {keyword}"

    # Check for patch operations without dry-run
    if tool_name == "apply_patch" and not args.get("dry_run", False):
        return True, "Applying patch (not dry-run)"

    return False, ""


def prompt_scary_operation(operation: str, reason: str) -> bool:
    """
    Prompt user to confirm a scary operation.
    Returns True if user approves, False otherwise.
    """
    print(f"\n{'='*60}")
    print(f"⚠️  POTENTIALLY DESTRUCTIVE OPERATION DETECTED")
    print(f"{'='*60}")
    print(f"Operation: {operation}")
    print(f"Reason: {reason}")
    print(f"{'='*60}")

    try:
        response = input("Continue with this operation? [y/N]: ").strip().lower()
        return response in ["y", "yes"]
    except (KeyboardInterrupt, EOFError):
        print("\n[Cancelled by user]")
        return False


def execution_mode(plan: ExecutionPlan, approved: bool = False, auto_approve: bool = True) -> bool:
    """Execute all tasks in the plan iteratively.

    Args:
        plan: ExecutionPlan with tasks to execute
        approved: Legacy parameter (ignored, kept for compatibility)
        auto_approve: If True (default), runs autonomously without initial approval.
                      Scary operations still require confirmation regardless.

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("EXECUTION MODE")
    print("=" * 60)

    # No upfront approval needed - runs autonomously
    # Scary operations will still prompt individually
    if not auto_approve:
        print("\nThis will execute all tasks with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    # Get system info for context
    sys_info = _get_system_info_cached()
    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{EXECUTION_SYSTEM}"""

    messages = [{"role": "system", "content": system_context}]
    max_iterations = 10000  # Very high limit to effectively remove restriction
    iteration = 0

    while not plan.is_complete() and iteration < max_iterations:
        iteration += 1
        current_task = plan.get_current_task()

        print(f"\n[Task {plan.current_index + 1}/{len(plan.tasks)}] {current_task.description}")
        print(f"[Type: {current_task.action_type}]")

        current_task.status = TaskStatus.IN_PROGRESS

        # Add task to conversation
        messages.append({
            "role": "user",
            "content": f"""Task: {current_task.description}
Action type: {current_task.action_type}

Execute this task completely. When done, respond with TASK_COMPLETE."""
        })

        # Execute task with tool calls
        task_iterations = 0
        max_task_iterations = 10000  # Very high limit to effectively remove restriction
        task_complete = False

        while task_iterations < max_task_iterations and not task_complete:
            task_iterations += 1

            # Try with tools, fall back to no-tools if needed
            response = ollama_chat(messages, tools=TOOLS)

            if "error" in response:
                error_msg = response['error']
                print(f"  ✗ Error: {error_msg}")

                # If we keep getting errors, try without tools
                if "400" in error_msg and task_iterations < 3:
                    print(f"  → Retrying without tool support...")
                    response = ollama_chat(messages, tools=None)

                if "error" in response:
                    plan.mark_failed(error_msg)
                    break

            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # Add assistant response to conversation
            messages.append(msg)

            # Execute tool calls FIRST before checking completion
            if tool_calls:
                for tool_call in tool_calls:
                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    tool_args = func.get("arguments", {})

                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}

                    # Check if this is a scary operation
                    is_scary, scary_reason = is_scary_operation(
                        tool_name,
                        tool_args,
                        current_task.action_type
                    )

                    if is_scary:
                        operation_desc = f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(tool_args.items())[:3])})"
                        if not prompt_scary_operation(operation_desc, scary_reason):
                            print(f"  ✗ Operation cancelled by user")
                            plan.mark_failed("User cancelled destructive operation")
                            task_complete = True
                            break

                    result = execute_tool(tool_name, tool_args)

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "content": result
                    })

                    # Check for test failures
                    if tool_name == "run_tests":
                        try:
                            result_data = json.loads(result)
                            if result_data.get("rc", 0) != 0:
                                print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                        except:
                            pass

            # Check if task is complete AFTER executing tool calls
            if "TASK_COMPLETE" in content or "task complete" in content.lower():
                print(f"  ✓ Task completed")
                plan.mark_completed(content)
                task_complete = True
                break

            # If model responds but doesn't use tools and doesn't complete task
            if not tool_calls and content:
                # Model is thinking/responding without tool calls
                print(f"  → {content[:200]}")

                # If model keeps responding without tools or completion, it might not support them
                if task_iterations >= 3:
                    print(f"  ⚠ Model not using tools. Marking task as needs manual intervention.")
                    plan.mark_failed("Model does not support tool calling. Consider using a model with tool support.")
                    break

        if not task_complete and task_iterations >= max_task_iterations:
            print(f"  ✗ Task exceeded iteration limit")
            plan.mark_failed("Exceeded iteration limit")

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○"
        }.get(task.status, "?")

        print(f"{status_icon} {i}. {task.description} [{task.status.value}]")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


def execute_single_task(task: Task, plan: ExecutionPlan, sys_info: Dict[str, Any], auto_approve: bool = True) -> bool:
    """Execute a single task (for concurrent execution).

    Returns:
        True if task completed successfully, False otherwise
    """
    print(f"\n[Task {task.task_id + 1}/{len(plan.tasks)}] {task.description}")
    print(f"[Type: {task.action_type}]")

    plan.mark_task_in_progress(task)

    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{EXECUTION_SYSTEM}"""

    messages = [{"role": "system", "content": system_context}]

    # Add task to conversation
    messages.append({
        "role": "user",
        "content": f"""Task: {task.description}
Action type: {task.action_type}

Execute this task completely. When done, respond with TASK_COMPLETE."""
    })

    # Execute task with tool calls
    task_iterations = 0
    max_task_iterations = 10000
    task_complete = False

    while task_iterations < max_task_iterations and not task_complete:
        task_iterations += 1

        # Try with tools, fall back to no-tools if needed
        response = ollama_chat(messages, tools=TOOLS)

        if "error" in response:
            error_msg = response['error']
            print(f"  ✗ Error: {error_msg}")

            # If we keep getting errors, try without tools
            if "400" in error_msg and task_iterations < 3:
                print(f"  → Retrying without tool support...")
                response = ollama_chat(messages, tools=None)

            if "error" in response:
                plan.mark_task_failed(task, error_msg)
                return False

        msg = response.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Add assistant response to conversation
        messages.append(msg)

        # Execute tool calls FIRST before checking completion
        if tool_calls:
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_args = func.get("arguments", {})

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                # Check if this is a scary operation
                is_scary, scary_reason = is_scary_operation(
                    tool_name,
                    tool_args,
                    task.action_type
                )

                if is_scary:
                    operation_desc = f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(tool_args.items())[:3])})"
                    if not prompt_scary_operation(operation_desc, scary_reason):
                        print(f"  ✗ Operation cancelled by user")
                        plan.mark_task_failed(task, "User cancelled destructive operation")
                        return False

                result = execute_tool(tool_name, tool_args)

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "content": result
                })

                # Check for test failures
                if tool_name == "run_tests":
                    try:
                        result_data = json.loads(result)
                        if result_data.get("rc", 0) != 0:
                            print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                    except:
                        pass

        # Check if task is complete AFTER executing tool calls
        if "TASK_COMPLETE" in content or "task complete" in content.lower():
            print(f"  ✓ Task completed")
            plan.mark_task_completed(task, content)
            return True

        # If model responds but doesn't use tools and doesn't complete task
        if not tool_calls and content:
            # Model is thinking/responding without tool calls
            print(f"  → {content[:200]}")

            # If model keeps responding without tools or completion, it might not support them
            if task_iterations >= 3:
                print(f"  ⚠ Model not using tools. Marking task as needs manual intervention.")
                plan.mark_task_failed(task, "Model does not support tool calling. Consider using a model with tool support.")
                return False

    if not task_complete:
        print(f"  ✗ Task exceeded iteration limit")
        plan.mark_task_failed(task, "Exceeded iteration limit")
        return False

    return True


def concurrent_execution_mode(plan: ExecutionPlan, max_workers: int = 2, auto_approve: bool = True) -> bool:
    """Execute tasks in the plan concurrently with dependency tracking.

    Args:
        plan: ExecutionPlan with tasks to execute
        max_workers: Maximum number of concurrent tasks (default: 2)
        auto_approve: If True (default), runs autonomously without initial approval

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("CONCURRENT EXECUTION MODE")
    print("=" * 60)
    print(f"  ℹ️  Max concurrent tasks: {max_workers}")

    if not auto_approve:
        print("\nThis will execute tasks in parallel with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting concurrent autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    # Get system info for context
    sys_info = _get_system_info_cached()

    # Use ThreadPoolExecutor for concurrent execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        while plan.has_pending_tasks():
            # Get tasks that are ready to execute (dependencies met)
            available_slots = max_workers - len(futures)
            if available_slots > 0:
                executable_tasks = plan.get_executable_tasks(max_count=available_slots)

                # Submit new tasks
                for task in executable_tasks:
                    future = executor.submit(execute_single_task, task, plan, sys_info, auto_approve)
                    futures[future] = task

            # Wait for at least one task to complete
            if futures:
                done, _ = as_completed(futures.keys()), None
                for future in list(done):
                    task = futures.pop(future)
                    try:
                        success = future.result()
                        if not success:
                            print(f"  ⚠ Task {task.task_id + 1} failed: {task.error}")
                    except Exception as e:
                        print(f"  ✗ Task {task.task_id + 1} crashed: {e}")
                        plan.mark_task_failed(task, str(e))
                    break  # Process one completion at a time
            else:
                # No tasks running and no tasks ready - check if we're stuck
                if plan.has_pending_tasks():
                    print("  ⚠ Warning: Tasks have unmet dependencies. Possible deadlock.")
                    break

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○"
        }.get(task.status, "?")

        deps_str = f" (depends on: {task.dependencies})" if task.dependencies else ""
        print(f"{status_icon} {i}. {task.description} [{task.status.value}]{deps_str}")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


# ========== REPL Mode ==========

def repl_mode():
    """Interactive REPL for iterative development with session memory."""
    print("agent.min REPL - Type /exit to quit, /help for commands")
    print("  ℹ️  Running in autonomous mode - destructive operations will prompt")

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": ""
    }

    while True:
        try:
            user_input = input("\nagent> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL")
            break

        if not user_input:
            continue

        if user_input in ["/exit", "/quit", ":q"]:
            print("Exiting REPL")
            if session_context["tasks_completed"]:
                print(f"\nSession Summary:")
                print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
                print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
                print(f"  - Files modified: {len(session_context['files_modified'])}")
            break

        if user_input == "/help":
            print("""
Commands:
  /exit, /quit, :q  - Exit REPL
  /help             - Show this help
  /status           - Show session summary
  /clear            - Clear session memory

Otherwise, describe a task and the agent will plan and execute it.
Autonomous mode: destructive operations require confirmation, others run automatically.
            """)
            continue

        if user_input == "/status":
            print(f"\nSession Summary:")
            print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
            print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
            print(f"  - Files modified: {len(session_context['files_modified'])}")
            if session_context["last_summary"]:
                print(f"\nLast execution:")
                print(f"  {session_context['last_summary']}")
            continue

        if user_input == "/clear":
            session_context = {
                "tasks_completed": [],
                "files_modified": set(),
                "files_reviewed": set(),
                "last_summary": ""
            }
            print("Session memory cleared")
            continue

        # Execute task with auto-approve (no initial prompt, scary ops still prompt)
        plan = planning_mode(user_input)
        success = execution_mode(plan, auto_approve=True)

        # Update session context
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED:
                session_context["tasks_completed"].append(task.description)
                # Track files for context
                if task.action_type in ["review", "read"]:
                    # Extract file names from task description
                    import re
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_reviewed"].update(files)
                elif task.action_type in ["edit", "add", "write"]:
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_modified"].update(files)

        session_context["last_summary"] = plan.get_summary()


# ========== Main Entry Point ==========

def main():
    global OLLAMA_MODEL, OLLAMA_BASE_URL

    parser = argparse.ArgumentParser(
        description="agent.min - Autonomous CI/CD agent powered by Ollama"
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Task description (one-shot mode)"
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Interactive REPL mode"
    )
    parser.add_argument(
        "--model",
        default=OLLAMA_MODEL,
        help=f"Ollama model (default: {OLLAMA_MODEL})"
    )
    parser.add_argument(
        "--base-url",
        default=OLLAMA_BASE_URL,
        help=f"Ollama base URL (default: {OLLAMA_BASE_URL})"
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Prompt for approval before execution (default: auto-approve)"
    )
    parser.add_argument(
        "-j", "--parallel",
        type=int,
        default=2,
        metavar="N",
        help="Number of concurrent tasks to run in parallel (default: 2, use 1 for sequential)"
    )

    args = parser.parse_args()

    # Update module globals for ollama_chat function
    OLLAMA_MODEL = args.model
    OLLAMA_BASE_URL = args.base_url

    print(f"agent.min - CI/CD Agent")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Ollama: {OLLAMA_BASE_URL}")
    print(f"Repository: {ROOT}")
    if args.parallel > 1:
        print(f"Parallel execution: {args.parallel} concurrent tasks")
    if not args.prompt:
        print("  ℹ️  Autonomous mode: destructive operations will prompt for confirmation")
    print()

    try:
        if args.repl or not args.task:
            repl_mode()
        else:
            task_description = " ".join(args.task)
            plan = planning_mode(task_description)
            # Use concurrent execution if parallel > 1, otherwise sequential
            if args.parallel > 1:
                concurrent_execution_mode(plan, max_workers=args.parallel, auto_approve=not args.prompt)
            else:
                execution_mode(plan, auto_approve=not args.prompt)
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
