#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base cache classes for rev."""

import time
import json
import pickle
import threading
import pathlib
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


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
        except Exception:
            return 0  # Return 0 on serialization error (but allow KeyboardInterrupt)

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
