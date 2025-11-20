#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cache management and statistics utilities."""

import json
from typing import Dict, Any, Optional, Callable

# Global cache references - will be set by the main module
_FILE_CACHE = None
_LLM_CACHE = None
_REPO_CACHE = None
_DEP_CACHE = None
_CACHE_DIR = None
_get_all_cache_stats_func: Optional[Callable[[], Dict[str, Any]]] = None
_clear_all_caches_func: Optional[Callable[[], None]] = None
_save_all_caches_func: Optional[Callable[[], None]] = None


def set_cache_references(file_cache=None, llm_cache=None, repo_cache=None, dep_cache=None,
                         cache_dir=None, get_stats_func=None, clear_func=None, save_func=None):
    """Set global cache references.

    Args:
        file_cache: FileContentCache instance
        llm_cache: LLMResponseCache instance
        repo_cache: RepoContextCache instance
        dep_cache: DependencyTreeCache instance
        cache_dir: Path to cache directory
        get_stats_func: Function to get all cache stats
        clear_func: Function to clear all caches
        save_func: Function to save all caches
    """
    global _FILE_CACHE, _LLM_CACHE, _REPO_CACHE, _DEP_CACHE, _CACHE_DIR
    global _get_all_cache_stats_func, _clear_all_caches_func, _save_all_caches_func

    if file_cache is not None:
        _FILE_CACHE = file_cache
    if llm_cache is not None:
        _LLM_CACHE = llm_cache
    if repo_cache is not None:
        _REPO_CACHE = repo_cache
    if dep_cache is not None:
        _DEP_CACHE = dep_cache
    if cache_dir is not None:
        _CACHE_DIR = cache_dir
    if get_stats_func is not None:
        _get_all_cache_stats_func = get_stats_func
    if clear_func is not None:
        _clear_all_caches_func = clear_func
    if save_func is not None:
        _save_all_caches_func = save_func


def get_cache_stats() -> str:
    """Get statistics for all caches.

    Returns:
        JSON string with cache statistics including hit rates, sizes, and performance metrics
    """
    try:
        if _get_all_cache_stats_func is None:
            return json.dumps({
                "error": "Cache system not initialized. Please initialize cache references first.",
                "note": "Use set_cache_references() to initialize"
            })

        stats = _get_all_cache_stats_func()
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
            if _clear_all_caches_func is None:
                # Fallback: clear individual caches
                if _FILE_CACHE is not None:
                    _FILE_CACHE.clear()
                if _LLM_CACHE is not None:
                    _LLM_CACHE.clear()
                if _REPO_CACHE is not None:
                    _REPO_CACHE.clear()
                if _DEP_CACHE is not None:
                    _DEP_CACHE.clear()
            else:
                _clear_all_caches_func()

            return json.dumps({
                "cleared": "all",
                "message": "All caches cleared successfully"
            })
        elif cache_name == "file_content":
            if _FILE_CACHE is not None:
                _FILE_CACHE.clear()
                return json.dumps({
                    "cleared": "file_content",
                    "message": "File content cache cleared"
                })
            else:
                return json.dumps({"error": "File content cache not initialized"})
        elif cache_name == "llm_response":
            if _LLM_CACHE is not None:
                _LLM_CACHE.clear()
                return json.dumps({
                    "cleared": "llm_response",
                    "message": "LLM response cache cleared"
                })
            else:
                return json.dumps({"error": "LLM response cache not initialized"})
        elif cache_name == "repo_context":
            if _REPO_CACHE is not None:
                _REPO_CACHE.clear()
                return json.dumps({
                    "cleared": "repo_context",
                    "message": "Repository context cache cleared"
                })
            else:
                return json.dumps({"error": "Repository context cache not initialized"})
        elif cache_name == "dependency_tree":
            if _DEP_CACHE is not None:
                _DEP_CACHE.clear()
                return json.dumps({
                    "cleared": "dependency_tree",
                    "message": "Dependency tree cache cleared"
                })
            else:
                return json.dumps({"error": "Dependency tree cache not initialized"})
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
        if _save_all_caches_func is None:
            # Fallback: save individual caches
            if _FILE_CACHE is not None and hasattr(_FILE_CACHE, '_save_to_disk'):
                _FILE_CACHE._save_to_disk()
            if _LLM_CACHE is not None and hasattr(_LLM_CACHE, '_save_to_disk'):
                _LLM_CACHE._save_to_disk()
            if _REPO_CACHE is not None and hasattr(_REPO_CACHE, '_save_to_disk'):
                _REPO_CACHE._save_to_disk()
            if _DEP_CACHE is not None and hasattr(_DEP_CACHE, '_save_to_disk'):
                _DEP_CACHE._save_to_disk()
        else:
            _save_all_caches_func()

        cache_dir_str = str(_CACHE_DIR) if _CACHE_DIR is not None else "unknown"
        return json.dumps({
            "persisted": True,
            "message": "All caches saved to disk successfully",
            "cache_dir": cache_dir_str
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to persist caches: {type(e).__name__}: {e}"})
