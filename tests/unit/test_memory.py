"""
Module: tests/unit/test_memory.py

Purpose:
    Unit tests for memory/cache.py (QueryCache) and memory/memory_manager.py
    (MemoryManager) — verifies caching behaviour, LRU eviction, TTL expiry,
    and correct delegation to vector/graph subsystems.

Responsibilities:
    - Test QueryCache get/set/invalidate/clear operations.
    - Test TTL-based expiry and LRU-based eviction.
    - Test MemoryManager cache-first search delegation.
    - Test MemoryManager graceful degradation when GraphStore is unavailable.
    - Test MemoryManager health_check aggregation across subsystems.
"""

from unittest.mock import MagicMock

import pytest

from memory.cache import QueryCache
from memory.memory_manager import MemoryManager
from schemas.memory_schema import VectorSearchResult


# ── QueryCache: basic get/set ─────────────────────────────────────────────────

class TestQueryCacheBasicOperations:
    """Tests for basic QueryCache get and set behaviour."""

    def test_get_returns_none_on_miss(self) -> None:
        """Querying a key that was never set should return None."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        assert cache.get("nonexistent query") is None

    def test_set_then_get_returns_stored_value(self) -> None:
        """A value stored via set() should be retrievable via get()."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("what is the policy", {"answer": "42"})

        result = cache.get("what is the policy")
        assert result == {"answer": "42"}

    def test_get_is_case_and_whitespace_insensitive(self) -> None:
        """Cache keys should normalise case and surrounding whitespace."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("  What Is The Policy  ", "cached_value")

        assert cache.get("what is the policy") == "cached_value"

    def test_different_context_produces_different_cache_entry(self) -> None:
        """Same query text with different context should not collide."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("query", "value_a", context="agent_a")
        cache.set("query", "value_b", context="agent_b")

        assert cache.get("query", context="agent_a") == "value_a"
        assert cache.get("query", context="agent_b") == "value_b"

    def test_hit_count_increments_on_repeated_get(self) -> None:
        """Repeated cache hits should increment the entry's hit_count."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("query", "value")

        cache.get("query")
        cache.get("query")
        cache.get("query")

        entry = cache._cache[cache._build_key("query")]
        assert entry.hit_count == 3


# ── QueryCache: TTL expiry ────────────────────────────────────────────────────

class TestQueryCacheExpiry:
    """Tests for time-based cache entry expiry."""

    def test_expired_entry_returns_none(self) -> None:
        """An entry with a negative TTL should be treated as immediately expired."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("query", "value", ttl_seconds=-1)

        assert cache.get("query") is None

    def test_expired_entry_increments_miss_and_expired_counters(self) -> None:
        """Expired entries should count as both a miss and an expired eviction."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("query", "value", ttl_seconds=-1)
        cache.get("query")

        stats = cache.get_stats()
        assert stats.total_misses >= 1
        assert stats.expired_evictions >= 1

    def test_non_expired_entry_is_not_evicted(self) -> None:
        """An entry with a long TTL should still be retrievable."""
        cache = QueryCache(max_size=10, default_ttl_seconds=3600)
        cache.set("query", "value")

        assert cache.get("query") == "value"


# ── QueryCache: LRU eviction ──────────────────────────────────────────────────

class TestQueryCacheLruEviction:
    """Tests for least-recently-used eviction when cache exceeds max size."""

    def test_evicts_oldest_entry_when_max_size_exceeded(self) -> None:
        """Inserting beyond max_size should evict the oldest unused entry."""
        cache = QueryCache(max_size=2, default_ttl_seconds=60)
        cache.set("first", "value_1")
        cache.set("second", "value_2")
        cache.set("third", "value_3")  # Should evict 'first'

        assert cache.get("first") is None
        assert cache.get("second") == "value_2"
        assert cache.get("third") == "value_3"

    def test_accessing_entry_protects_it_from_eviction(self) -> None:
        """Accessing an entry should mark it as recently used, protecting it."""
        cache = QueryCache(max_size=2, default_ttl_seconds=60)
        cache.set("first", "value_1")
        cache.set("second", "value_2")

        cache.get("first")  # Marks 'first' as recently used

        cache.set("third", "value_3")  # Should evict 'second', not 'first'

        assert cache.get("first") == "value_1"
        assert cache.get("second") is None

    def test_size_eviction_counter_increments(self) -> None:
        """Size-based evictions should be tracked in cache statistics."""
        cache = QueryCache(max_size=1, default_ttl_seconds=60)
        cache.set("first", "value_1")
        cache.set("second", "value_2")

        stats = cache.get_stats()
        assert stats.size_evictions >= 1


# ── QueryCache: invalidate & clear ────────────────────────────────────────────

class TestQueryCacheInvalidateAndClear:
    """Tests for manual cache invalidation and full clearing."""

    def test_invalidate_removes_specific_entry(self) -> None:
        """invalidate() should remove only the targeted entry."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("keep", "value_1")
        cache.set("remove", "value_2")

        removed = cache.invalidate("remove")

        assert removed is True
        assert cache.get("remove") is None
        assert cache.get("keep") == "value_1"

    def test_invalidate_returns_false_for_missing_key(self) -> None:
        """invalidate() on a non-existent key should return False."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        assert cache.invalidate("never_set") is False

    def test_clear_removes_all_entries(self) -> None:
        """clear() should empty the entire cache."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)

        cache.clear()

        assert cache.get("a") is None
        assert cache.get("b") is None


# ── QueryCache: statistics ────────────────────────────────────────────────────

class TestQueryCacheStats:
    """Tests for cache statistics reporting."""

    def test_hit_rate_computed_correctly(self) -> None:
        """Hit rate percentage should reflect actual hit/miss ratio."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        cache.set("query", "value")

        cache.get("query")           # hit
        cache.get("nonexistent")     # miss

        stats = cache.get_stats()
        assert stats.total_hits == 1
        assert stats.total_misses == 1
        assert stats.hit_rate_percent == 50.0

    def test_hit_rate_is_zero_with_no_requests(self) -> None:
        """Hit rate should be 0.0 when no get() calls have been made."""
        cache = QueryCache(max_size=10, default_ttl_seconds=60)
        stats = cache.get_stats()
        assert stats.hit_rate_percent == 0.0


# ── MemoryManager: cache-first search ────────────────────────────────────────

class TestMemoryManagerSearch:
    """Tests for MemoryManager's cache-first search delegation."""

    def test_search_raises_on_empty_query(
        self, mock_vector_store: MagicMock
    ) -> None:
        """An empty query string should raise ValueError before hitting cache/store."""
        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )
        with pytest.raises(ValueError, match="must not be empty"):
            manager.search("")

    def test_search_calls_vector_store_on_cache_miss(
        self,
        mock_vector_store: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """A cache miss should fall through to the vector store."""
        mock_vector_store.search.return_value = [sample_vector_search_result]

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )

        results = manager.search("budget decision", agent_context="TestAgent")

        mock_vector_store.search.assert_called_once()
        assert results == [sample_vector_search_result]

    def test_search_returns_cached_result_without_calling_vector_store(
        self,
        mock_vector_store: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """A repeated identical query should be served from cache."""
        mock_vector_store.search.return_value = [sample_vector_search_result]

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )

        manager.search("budget decision", agent_context="TestAgent")
        manager.search("budget decision", agent_context="TestAgent")

        # Vector store should only be hit once — second call served from cache
        assert mock_vector_store.search.call_count == 1

    def test_search_bypasses_cache_when_use_cache_false(
        self,
        mock_vector_store: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """use_cache=False should force a fresh vector store call every time."""
        mock_vector_store.search.return_value = [sample_vector_search_result]

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )

        manager.search("query", use_cache=False)
        manager.search("query", use_cache=False)

        assert mock_vector_store.search.call_count == 2


# ── MemoryManager: graph delegation ───────────────────────────────────────────

class TestMemoryManagerGraphDelegation:
    """Tests for MemoryManager delegation to the graph store."""

    def test_get_person_returns_none_when_graph_unavailable(
        self, mock_vector_store: MagicMock
    ) -> None:
        """get_person() should return None gracefully with no graph store."""
        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )
        assert manager.get_person("someone@enron.com") is None

    def test_upsert_person_raises_when_graph_unavailable(
        self, mock_vector_store: MagicMock
    ) -> None:
        """Write operations to the graph must raise when graph is unavailable."""
        from schemas.memory_schema import PersonNode

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )

        person = PersonNode(
            node_id="a@enron.com", name="A", email="a@enron.com"
        )

        with pytest.raises(RuntimeError, match="GraphStore is unavailable"):
            manager.upsert_person(person)

    def test_get_person_delegates_to_graph_store(
        self,
        mock_vector_store: MagicMock,
        mock_graph_store: MagicMock,
    ) -> None:
        """get_person() should delegate directly to GraphStore.get_person_by_email."""
        mock_graph_store.get_person_by_email.return_value = {
            "name": "Phillip Allen", "email": "phillip.allen@enron.com"
        }

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            cache=QueryCache(),
        )

        result = manager.get_person("phillip.allen@enron.com")

        mock_graph_store.get_person_by_email.assert_called_once_with(
            "phillip.allen@enron.com"
        )
        assert result["name"] == "Phillip Allen"


# ── MemoryManager: health check ───────────────────────────────────────────────

class TestMemoryManagerHealthCheck:
    """Tests for MemoryManager's aggregated health_check() method."""

    def test_health_check_reports_healthy_when_all_subsystems_ok(
        self,
        mock_vector_store: MagicMock,
        mock_graph_store: MagicMock,
    ) -> None:
        """Overall status should be 'healthy' when all subsystems succeed."""
        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            cache=QueryCache(),
        )

        health = manager.health_check()

        assert health["status"] == "healthy"
        assert health["subsystems"]["vector_store"]["status"] == "healthy"
        assert health["subsystems"]["graph_store"]["status"] == "healthy"
        assert health["subsystems"]["cache"]["status"] == "healthy"

    def test_health_check_reports_degraded_on_vector_store_failure(
        self,
        mock_vector_store: MagicMock,
        mock_graph_store: MagicMock,
    ) -> None:
        """Overall status should degrade if the vector store raises."""
        mock_vector_store.get_stats.side_effect = Exception("ChromaDB unreachable")

        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=mock_graph_store,
            cache=QueryCache(),
        )

        health = manager.health_check()

        assert health["status"] == "degraded"
        assert health["subsystems"]["vector_store"]["status"] == "unhealthy"

    def test_health_check_reports_disabled_graph_when_unavailable(
        self, mock_vector_store: MagicMock
    ) -> None:
        """Graph subsystem should report 'disabled', not 'unhealthy', when None."""
        manager = MemoryManager(
            vector_store=mock_vector_store,
            graph_store=None,
            cache=QueryCache(),
        )

        health = manager.health_check()

        assert health["subsystems"]["graph_store"]["status"] == "disabled"
        # A disabled graph (by design) should not degrade overall status
        assert health["status"] == "healthy"