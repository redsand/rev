"""
Tests for rev.py intelligent caching system.

This test suite covers:
- IntelligentCache base functionality (TTL, LRU, size limits)
- FileContentCache with modification time tracking
- LLMResponseCache with message hashing
- RepoContextCache with git HEAD tracking
- DependencyTreeCache with file modification tracking
- Cache statistics and management
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path to import rev
sys.path.insert(0, str(Path(__file__).parent.parent))

import rev


class TestIntelligentCache:
    """Test base IntelligentCache functionality."""

    def test_basic_get_set(self):
        """Test basic cache get/set operations."""
        cache = rev.IntelligentCache(name="test", ttl=60)

        # Initially empty
        assert cache.get("key1") is None

        # Set and get
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Get with default
        assert cache.get("nonexistent", "default") == "default"

    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = rev.IntelligentCache(name="test", ttl=1)  # 1 second TTL

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("key1") is None

        # Stats should reflect expiration
        stats = cache.get_stats()
        assert stats["expirations"] >= 1

    def test_lru_eviction(self):
        """Test LRU eviction when max_entries reached."""
        cache = rev.IntelligentCache(name="test", ttl=0, max_entries=3)

        # Add 3 entries (at limit)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert cache.get("key1") == "value1"

        # Add 4th entry - should evict LRU (key2 since key1 was just accessed)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Recently accessed
        assert cache.get("key2") is None      # Evicted (LRU)
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

        # Stats should reflect eviction
        stats = cache.get_stats()
        assert stats["evictions"] >= 1

    def test_size_based_eviction(self):
        """Test size-based eviction."""
        cache = rev.IntelligentCache(
            name="test",
            ttl=0,
            max_entries=100,
            max_size_bytes=100  # Very small limit
        )

        # Add small entry
        cache.set("small", "x")
        assert cache.get("small") == "x"

        # Add large entry - should trigger eviction
        large_value = "x" * 200
        cache.set("large", large_value)

        # Cache should not exceed size limit
        stats = cache.get_stats()
        assert stats["total_size_bytes"] <= 100

    def test_invalidate(self):
        """Test cache invalidation."""
        cache = rev.IntelligentCache(name="test")

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Invalidate
        result = cache.invalidate("key1")
        assert result is True
        assert cache.get("key1") is None

        # Invalidate non-existent key
        result = cache.invalidate("nonexistent")
        assert result is False

    def test_clear(self):
        """Test clearing entire cache."""
        cache = rev.IntelligentCache(name="test")

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

        stats = cache.get_stats()
        assert stats["entries"] == 0
        assert stats["total_size_bytes"] == 0

    def test_hit_rate_statistics(self):
        """Test cache hit rate calculation."""
        cache = rev.IntelligentCache(name="test")

        cache.set("key1", "value1")

        # 2 hits
        cache.get("key1")
        cache.get("key1")

        # 1 miss
        cache.get("key2")

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 66.67  # 2/3 * 100

    def test_metadata(self):
        """Test storing metadata with cache entries."""
        cache = rev.IntelligentCache(name="test")

        cache.set("key1", "value1", metadata={"source": "test", "version": 1})

        # Access internal entry to check metadata
        with cache._lock:
            entry = cache._cache.get("key1")
            assert entry is not None
            assert entry.metadata["source"] == "test"
            assert entry.metadata["version"] == 1


class TestFileContentCache:
    """Test FileContentCache with modification time tracking."""

    def test_file_caching(self):
        """Test caching file contents."""
        cache = rev.FileContentCache()

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as f:
            f.write("original content")
            file_path = Path(f.name)

        try:
            # First read - cache miss
            assert cache.get_file(file_path) is None

            # Set cache
            cache.set_file(file_path, "original content")

            # Second read - cache hit
            cached = cache.get_file(file_path)
            assert cached == "original content"

            # Modify file
            time.sleep(0.1)  # Ensure different mtime
            with open(file_path, 'w') as f:
                f.write("modified content")

            # Should miss cache due to mtime change
            cached = cache.get_file(file_path)
            assert cached is None

        finally:
            file_path.unlink()

    def test_nonexistent_file(self):
        """Test handling of nonexistent files."""
        cache = rev.FileContentCache()

        fake_path = Path("/nonexistent/file.txt")
        assert cache.get_file(fake_path) is None


class TestLLMResponseCache:
    """Test LLMResponseCache with message hashing."""

    def test_message_hashing(self):
        """Test that identical messages produce same hash."""
        cache = rev.LLMResponseCache()

        messages1 = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]

        messages2 = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]

        # Different object, same content
        hash1 = cache._hash_messages(messages1)
        hash2 = cache._hash_messages(messages2)
        assert hash1 == hash2

    def test_response_caching(self):
        """Test caching LLM responses."""
        cache = rev.LLMResponseCache()

        messages = [{"role": "user", "content": "Test query"}]
        response = {"message": {"content": "Test response"}}

        # Initially empty
        assert cache.get_response(messages) is None

        # Cache response
        cache.set_response(messages, response)

        # Should get cached response
        cached = cache.get_response(messages)
        assert cached == response

    def test_tools_affect_hash(self):
        """Test that tools affect cache key."""
        cache = rev.LLMResponseCache()

        messages = [{"role": "user", "content": "Test"}]
        tools = [{"type": "function", "function": {"name": "test"}}]

        response1 = {"message": {"content": "Response 1"}}
        response2 = {"message": {"content": "Response 2"}}

        # Cache with tools
        cache.set_response(messages, response1, tools)

        # Cache without tools (different key)
        cache.set_response(messages, response2, None)

        # Should get different responses
        assert cache.get_response(messages, tools) == response1
        assert cache.get_response(messages, None) == response2


class TestRepoContextCache:
    """Test RepoContextCache with git HEAD tracking."""

    def test_context_caching(self):
        """Test caching repository context."""
        cache = rev.RepoContextCache()

        context = '{"status": "clean", "log": "commit abc123"}'

        # Initially empty
        assert cache.get_context() is None

        # Cache context
        cache.set_context(context)

        # Should get cached context
        cached = cache.get_context()
        assert cached == context


class TestDependencyTreeCache:
    """Test DependencyTreeCache with file modification tracking."""

    def test_python_dependencies_caching(self):
        """Test caching Python dependency analysis."""
        cache = rev.DependencyTreeCache()

        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            with patch('rev.ROOT', Path(tmpdir)):
                # Initially empty
                assert cache.get_dependencies("python") is None

                # Cache result
                result = '{"language": "python", "dependencies": ["requests==2.28.0"]}'
                cache.set_dependencies("python", result)

                # Should get cached result
                cached = cache.get_dependencies("python")
                assert cached == result

                # Modify requirements.txt
                time.sleep(0.1)  # Ensure different mtime
                requirements.write_text("requests==2.31.0\n")

                # Should miss cache due to mtime change
                cached = cache.get_dependencies("python")
                assert cached is None

    def test_javascript_dependencies_caching(self):
        """Test caching JavaScript dependency analysis."""
        cache = rev.DependencyTreeCache()

        with tempfile.TemporaryDirectory() as tmpdir:
            package_json = Path(tmpdir) / "package.json"
            package_json.write_text('{"dependencies": {"express": "^4.0.0"}}')

            with patch('rev.ROOT', Path(tmpdir)):
                result = '{"language": "javascript", "dependencies": ["express"]}'
                cache.set_dependencies("javascript", result)

                cached = cache.get_dependencies("javascript")
                assert cached == result


class TestCacheIntegration:
    """Test integration of caching with existing functions."""

    def test_read_file_uses_cache(self):
        """Test that read_file uses file content cache."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as f:
            f.write("test content")
            file_path = f.name

        try:
            # Clear cache
            rev._FILE_CACHE.clear()

            # First read - should cache
            content1 = rev.read_file(file_path)
            stats1 = rev._FILE_CACHE.get_stats()
            misses1 = stats1["misses"]

            # Second read - should hit cache
            content2 = rev.read_file(file_path)
            stats2 = rev._FILE_CACHE.get_stats()
            hits2 = stats2["hits"]

            assert content1 == content2
            assert hits2 > 0  # Should have cache hits

        finally:
            Path(file_path).unlink()

    def test_get_repo_context_uses_cache(self):
        """Test that get_repo_context uses repo context cache."""
        # Clear cache
        rev._REPO_CACHE.clear()

        # First call - should cache
        context1 = rev.get_repo_context()
        stats1 = rev._REPO_CACHE.get_stats()

        # Second call - should hit cache
        context2 = rev.get_repo_context()
        stats2 = rev._REPO_CACHE.get_stats()

        assert context1 == context2
        assert stats2["hits"] > stats1["hits"]

    def test_analyze_dependencies_uses_cache(self):
        """Test that analyze_dependencies uses dependency cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text("requests==2.28.0\n")

            with patch('rev.ROOT', Path(tmpdir)):
                # Clear cache
                rev._DEP_CACHE.clear()

                # First call - should cache
                result1 = rev.analyze_dependencies("python")
                stats1 = rev._DEP_CACHE.get_stats()

                # Second call - should hit cache
                result2 = rev.analyze_dependencies("python")
                stats2 = rev._DEP_CACHE.get_stats()

                assert result1 == result2
                assert stats2["hits"] > stats1["hits"]


class TestCacheManagement:
    """Test cache management utilities."""

    def test_get_cache_stats(self):
        """Test getting cache statistics."""
        result = rev.get_cache_stats()
        stats = json.loads(result)

        assert "file_content" in stats
        assert "llm_response" in stats
        assert "repo_context" in stats
        assert "dependency_tree" in stats

        # Check structure of stats
        file_stats = stats["file_content"]
        assert "hits" in file_stats
        assert "misses" in file_stats
        assert "hit_rate" in file_stats
        assert "entries" in file_stats

    def test_clear_caches_all(self):
        """Test clearing all caches."""
        # Add some data
        rev._FILE_CACHE.set("test", "value")
        rev._LLM_CACHE.set("test", "value")

        result = rev.clear_caches("all")
        result_data = json.loads(result)

        assert result_data["cleared"] == "all"

        # Verify caches are empty
        assert rev._FILE_CACHE.get("test") is None
        assert rev._LLM_CACHE.get("test") is None

    def test_clear_specific_cache(self):
        """Test clearing a specific cache."""
        # Add data to multiple caches
        rev._FILE_CACHE.set("test", "value1")
        rev._LLM_CACHE.set("test", "value2")

        # Clear only file cache
        result = rev.clear_caches("file_content")
        result_data = json.loads(result)

        assert result_data["cleared"] == "file_content"

        # File cache should be empty, LLM cache should still have data
        assert rev._FILE_CACHE.get("test") is None
        assert rev._LLM_CACHE.get("test") == "value2"

    def test_clear_invalid_cache(self):
        """Test clearing with invalid cache name."""
        result = rev.clear_caches("invalid_cache_name")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "valid_caches" in result_data

    def test_persist_caches(self):
        """Test persisting caches to disk."""
        result = rev.persist_caches()
        result_data = json.loads(result)

        assert result_data["persisted"] is True
        assert "cache_dir" in result_data


class TestCachePersistence:
    """Test cache persistence to disk."""

    def test_save_and_load(self):
        """Test saving and loading cache from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "test_cache.pkl"

            # Create cache with data
            cache1 = rev.IntelligentCache(
                name="test",
                ttl=60,
                persist_path=cache_path
            )
            cache1.set("key1", "value1")
            cache1.set("key2", "value2")

            # Save to disk
            cache1._save_to_disk()

            # Create new cache instance that loads from disk
            cache2 = rev.IntelligentCache(
                name="test",
                ttl=60,
                persist_path=cache_path
            )

            # Should have loaded the data
            assert cache2.get("key1") == "value1"
            assert cache2.get("key2") == "value2"

    def test_expired_entries_cleaned_on_load(self):
        """Test that expired entries are cleaned when loading from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "test_cache.pkl"

            # Create cache with short TTL
            cache1 = rev.IntelligentCache(
                name="test",
                ttl=1,  # 1 second
                persist_path=cache_path
            )
            cache1.set("key1", "value1")
            cache1._save_to_disk()

            # Wait for expiration
            time.sleep(1.1)

            # Load cache - should clean up expired entries
            cache2 = rev.IntelligentCache(
                name="test",
                ttl=1,
                persist_path=cache_path
            )

            # Expired entry should be gone
            assert cache2.get("key1") is None


if __name__ == "__main__":
    # Run tests with basic test runner
    import unittest

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestIntelligentCache))
    suite.addTests(loader.loadTestsFromTestCase(TestFileContentCache))
    suite.addTests(loader.loadTestsFromTestCase(TestLLMResponseCache))
    suite.addTests(loader.loadTestsFromTestCase(TestRepoContextCache))
    suite.addTests(loader.loadTestsFromTestCase(TestDependencyTreeCache))
    suite.addTests(loader.loadTestsFromTestCase(TestCacheIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestCacheManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestCachePersistence))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
