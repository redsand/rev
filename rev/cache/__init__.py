#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Caching system for rev."""

from typing import Dict, Any

from .base import CacheEntry, IntelligentCache
from .implementations import (
    FileContentCache,
    LLMResponseCache,
    RepoContextCache,
    DependencyTreeCache
)

__all__ = [
    "CacheEntry",
    "IntelligentCache",
    "FileContentCache",
    "LLMResponseCache",
    "RepoContextCache",
    "DependencyTreeCache",
    "get_all_cache_stats",
    "clear_all_caches",
    "save_all_caches",
    "initialize_caches",
    "get_file_cache",
    "get_llm_cache",
    "get_repo_cache",
    "get_dep_cache"
]

# Global cache instances (will be initialized by initialize_caches())
_FILE_CACHE: FileContentCache = None
_LLM_CACHE: LLMResponseCache = None
_REPO_CACHE: RepoContextCache = None
_DEP_CACHE: DependencyTreeCache = None


def initialize_caches(root, cache_dir):
    """Initialize all global cache instances."""
    global _FILE_CACHE, _LLM_CACHE, _REPO_CACHE, _DEP_CACHE

    _FILE_CACHE = FileContentCache(persist_path=cache_dir / "file_cache.pkl")
    _LLM_CACHE = LLMResponseCache(persist_path=cache_dir / "llm_cache.pkl")
    _REPO_CACHE = RepoContextCache(root=root, persist_path=cache_dir / "repo_cache.pkl")
    _DEP_CACHE = DependencyTreeCache(root=root, persist_path=cache_dir / "dep_cache.pkl")


def get_file_cache() -> FileContentCache:
    """Get the global file content cache."""
    return _FILE_CACHE


def get_llm_cache() -> LLMResponseCache:
    """Get the global LLM response cache."""
    return _LLM_CACHE


def get_repo_cache() -> RepoContextCache:
    """Get the global repository context cache."""
    return _REPO_CACHE


def get_dep_cache() -> DependencyTreeCache:
    """Get the global dependency tree cache."""
    return _DEP_CACHE


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
