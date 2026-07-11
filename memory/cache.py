"""
Module: memory/cache.py

Purpose:
    Provides an in-memory caching layer for agent query results to
    reduce redundant LLM calls and ChromaDB lookups.

Responsibilities:
    - Cache agent responses keyed by query hash.
    - Support configurable TTL (time-to-live) per cache entry.
    - Provide cache hit/miss statistics for monitoring.
    - Implement a simple LRU-style eviction when cache exceeds max size.
    - Operate as a pure in-memory cache — no Redis dependency required.

Workflow:
    Phase 1 — Agent receives a query.
    Phase 2 — Cache is checked for existing result via query hash.
    Phase 3 — On hit: return cached result immediately.
    Phase 4 — On miss: agent processes query, result stored in cache.
    Phase 5 — Expired or evicted entries are cleaned automatically.
"""

import hashlib
import time
from collections import OrderedDict
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field


# ── Cache Entry Model ────────────────────────────────────────────────────────

class CacheEntry(BaseModel):
    """Represents a single entry stored in the cache.

    Attributes:
        key: The hashed cache key.
        value: The cached value (agent output or search result).
        created_at: Unix timestamp when this entry was created.
        ttl_seconds: How long this entry remains valid.
        hit_count: Number of times this entry has been retrieved.
    """

    key: str = Field(..., description="Hashed cache key")
    value: Any = Field(..., description="Cached value")
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp of cache entry creation",
    )
    ttl_seconds: int = Field(
        default=3600,
        description="Time-to-live in seconds before entry expires",
    )
    hit_count: int = Field(
        default=0,
        description="Number of times this entry has been served from cache",
    )

    @property
    def is_expired(self) -> bool:
        """Checks whether this cache entry has exceeded its TTL.

        Returns:
            True if the entry has expired, False if still valid.
        """
        return (time.time() - self.created_at) > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Returns the age of this cache entry in seconds.

        Returns:
            Float representing seconds since entry was created.
        """
        return round(time.time() - self.created_at, 2)


# ── Cache Statistics Model ───────────────────────────────────────────────────

class CacheStats(BaseModel):
    """Statistics snapshot of the current cache state.

    Returned by QueryCache.get_stats() for monitoring and dashboards.
    """

    total_entries: int = Field(..., description="Current number of entries in cache")
    max_size: int = Field(..., description="Maximum allowed cache entries")
    total_hits: int = Field(..., description="Total cache hits since startup")
    total_misses: int = Field(..., description="Total cache misses since startup")
    hit_rate_percent: float = Field(..., description="Cache hit rate as a percentage")
    expired_evictions: int = Field(
        ..., description="Total entries removed due to TTL expiry"
    )
    size_evictions: int = Field(
        ..., description="Total entries removed due to max size limit"
    )


# ── Query Cache ──────────────────────────────────────────────────────────────

class QueryCache:
    """In-memory LRU cache for agent query results.

    Uses an OrderedDict to maintain insertion order for LRU eviction.
    Thread-safety is not implemented — suitable for single-threaded
    or async single-event-loop usage patterns.

    Attributes:
        _cache: Ordered dictionary of cache key to CacheEntry.
        _max_size: Maximum number of entries before LRU eviction.
        _default_ttl: Default TTL in seconds for new entries.
        _total_hits: Cumulative hit counter.
        _total_misses: Cumulative miss counter.
        _expired_evictions: Cumulative expired entry removal counter.
        _size_evictions: Cumulative LRU eviction counter.
    """

    def __init__(
        self,
        max_size: int = 500,
        default_ttl_seconds: int = 3600,
    ) -> None:
        """Initialises the QueryCache with size and TTL configuration.

        Args:
            max_size: Maximum number of entries to hold before eviction.
                Defaults to 500.
            default_ttl_seconds: Default TTL for entries in seconds.
                Defaults to 3600 (1 hour).
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._total_hits = 0
        self._total_misses = 0
        self._expired_evictions = 0
        self._size_evictions = 0

        logger.info(
            "QueryCache initialised | max_size={} | default_ttl={}s",
            max_size,
            default_ttl_seconds,
        )

    @staticmethod
    def _build_key(query: str, context: Optional[str] = None) -> str:
        """Generates a deterministic hash key from a query string.

        Combines query and optional context into a SHA-256 hash to
        produce a compact, collision-resistant cache key.

        Args:
            query: The query string to hash.
            context: Optional additional context to include in the hash
                (e.g. agent name, session ID).

        Returns:
            A 16-character hexadecimal hash string.
        """
        raw = f"{query.strip().lower()}::{context or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _evict_expired(self) -> None:
        """Removes all expired entries from the cache.

        Called automatically before get and set operations to keep
        the cache free of stale entries.
        """
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired
        ]

        for key in expired_keys:
            del self._cache[key]
            self._expired_evictions += 1

        if expired_keys:
            logger.debug(
                "Evicted {} expired cache entries.", len(expired_keys)
            )

    def _evict_lru(self) -> None:
        """Evicts the least recently used entry when cache is at max size.

        OrderedDict maintains insertion/access order, so the first
        item is always the least recently used.
        """
        if len(self._cache) >= self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            self._size_evictions += 1
            logger.debug("LRU eviction | key='{}'", evicted_key)

    def get(
        self,
        query: str,
        context: Optional[str] = None,
    ) -> Optional[Any]:
        """Retrieves a cached value for the given query.

        Marks the entry as recently used by moving it to the end of
        the OrderedDict on a cache hit.

        Args:
            query: The query string to look up.
            context: Optional context used during set() for this entry.

        Returns:
            The cached value if found and not expired, None otherwise.
        """
        self._evict_expired()

        key = self._build_key(query, context)
        entry = self._cache.get(key)

        if entry is None:
            self._total_misses += 1
            logger.debug("Cache MISS | key='{}'", key)
            return None

        if entry.is_expired:
            del self._cache[key]
            self._expired_evictions += 1
            self._total_misses += 1
            logger.debug("Cache EXPIRED | key='{}'", key)
            return None

        # Move to end to mark as recently used (LRU maintenance)
        self._cache.move_to_end(key)
        entry.hit_count += 1
        self._total_hits += 1

        logger.debug(
            "Cache HIT | key='{}' | age={}s | hits={}",
            key,
            entry.age_seconds,
            entry.hit_count,
        )

        return entry.value

    def set(
        self,
        query: str,
        value: Any,
        context: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Stores a value in the cache keyed by the query string.

        Evicts expired entries and enforces max size before inserting.

        Args:
            query: The query string used as the cache key basis.
            value: The value to cache (agent output, search results, etc).
            context: Optional context to scope the cache key.
            ttl_seconds: Custom TTL for this entry. Uses default if None.
        """
        self._evict_expired()
        self._evict_lru()

        key = self._build_key(query, context)
        ttl = ttl_seconds or self._default_ttl

        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            ttl_seconds=ttl,
        )

        # Move to end to mark as most recently used
        self._cache.move_to_end(key)

        logger.debug(
            "Cache SET | key='{}' | ttl={}s | size={}",
            key,
            ttl,
            len(self._cache),
        )

    def invalidate(self, query: str, context: Optional[str] = None) -> bool:
        """Removes a specific entry from the cache by query.

        Args:
            query: The query string whose cache entry should be removed.
            context: Optional context used when the entry was stored.

        Returns:
            True if the entry was found and removed, False otherwise.
        """
        key = self._build_key(query, context)

        if key in self._cache:
            del self._cache[key]
            logger.debug("Cache INVALIDATED | key='{}'", key)
            return True

        return False

    def clear(self) -> None:
        """Clears all entries from the cache.

        Used during testing or when a full cache reset is required.
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cache cleared | removed={} entries", count)

    def get_stats(self) -> CacheStats:
        """Returns a statistics snapshot of the current cache state.

        Returns:
            A CacheStats object with hit/miss rates and eviction counts.
        """
        total_requests = self._total_hits + self._total_misses
        hit_rate = (
            round((self._total_hits / total_requests) * 100, 2)
            if total_requests > 0
            else 0.0
        )

        return CacheStats(
            total_entries=len(self._cache),
            max_size=self._max_size,
            total_hits=self._total_hits,
            total_misses=self._total_misses,
            hit_rate_percent=hit_rate,
            expired_evictions=self._expired_evictions,
            size_evictions=self._size_evictions,
        )


# ── Module-level singleton ───────────────────────────────────────────────────
# Shared cache instance imported by agents and orchestrators.

query_cache = QueryCache(
    max_size=500,
    default_ttl_seconds=3600,
)