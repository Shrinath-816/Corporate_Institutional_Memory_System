"""
Module: memory/memory_manager.py

Purpose:
    Provides a unified interface over all memory subsystems — ChromaDB
    vector store, Neo4j graph store, and in-memory query cache —
    for use by all agents and orchestrators.

Responsibilities:
    - Initialise and hold references to VectorStore, GraphStore, and QueryCache.
    - Expose a single search() method that checks cache first, then vector store.
    - Expose graph operations through a clean delegating interface.
    - Provide a unified health check across all memory subsystems.
    - Act as the single dependency injected into every agent.

Workflow:
    Phase 1 — Initialise all three memory subsystems on startup.
    Phase 2 — Agent calls memory_manager.search() with a query.
    Phase 3 — Cache is checked first for existing result.
    Phase 4 — On miss: VectorStore is queried and result is cached.
    Phase 5 — Graph operations are delegated to GraphStore directly.
    Phase 6 — Health check aggregates status from all subsystems.
"""

from typing import Any, Optional
from loguru import logger

from memory.vector_store import VectorStore
from memory.graph_store import GraphStore
from memory.cache import QueryCache, query_cache
from schemas.memory_schema import (
    VectorSearchResult,
    PersonNode,
    DecisionNode,
    ProjectNode,
    PolicyNode,
    GraphRelationship,
)


class MemoryManager:
    """Unified interface over all memory subsystems.

    Acts as the single memory dependency for every agent and orchestrator
    in the system. Abstracts VectorStore, GraphStore, and QueryCache
    behind one clean interface, eliminating direct subsystem coupling.

    Attributes:
        _vector_store: ChromaDB vector store instance.
        _graph_store: Neo4j graph store instance.
        _cache: In-memory query result cache instance.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        graph_store: Optional[GraphStore] = None,
        cache: Optional[QueryCache] = None,
    ) -> None:
        """Initialises the MemoryManager with all memory subsystems.

        Accepts optional injected instances to support testing with mocks.
        Creates default instances if none are provided.

        Args:
            vector_store: Optional VectorStore instance. Created if None.
            graph_store: Optional GraphStore instance. Created if None.
            cache: Optional QueryCache instance. Uses module singleton if None.
        """
        logger.info("Initialising MemoryManager...")

        self._vector_store = vector_store or VectorStore()
        self._cache = cache or query_cache

        # GraphStore requires Neo4j — initialise with warning if unavailable
        if graph_store is not None:
            self._graph_store: Optional[GraphStore] = graph_store
        else:
            try:
                self._graph_store = GraphStore()
            except Exception as exc:
                logger.warning(
                    "GraphStore unavailable — graph features disabled: {}", exc
                )
                self._graph_store = None

        logger.info("MemoryManager initialised successfully.")

    # ── Vector Search with Cache ─────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        metadata_filter: Optional[dict] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
        agent_context: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        """Searches for relevant chunks — cache first, then vector store.

        This is the primary retrieval method used by all agents. It checks
        the in-memory cache before hitting ChromaDB to avoid redundant
        embedding and similarity computations for repeated queries.

        Args:
            query: Natural language query string.
            top_k: Number of results to return.
            metadata_filter: Optional ChromaDB where-clause filter.
            use_cache: Whether to check and populate the cache.
                Defaults to True.
            cache_ttl: Optional custom TTL for this cache entry.
            agent_context: Optional agent name to scope cache key,
                preventing cross-agent cache pollution.

        Returns:
            List of VectorSearchResult objects ordered by relevance.

        Raises:
            ValueError: If query string is empty.
        """
        if not query or not query.strip():
            raise ValueError("Search query must not be empty.")

        cache_context = f"{agent_context}:{str(metadata_filter)}"

        # ── Cache check ──────────────────────────────────────────────────────
        if use_cache:
            cached = self._cache.get(query, context=cache_context)
            if cached is not None:
                logger.debug(
                    "MemoryManager cache hit | agent='{}' | query='{}'",
                    agent_context,
                    query[:60],
                )
                return cached

        # ── Vector store search ──────────────────────────────────────────────
        results = self._vector_store.search(
            query=query,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )

        # ── Cache the result ─────────────────────────────────────────────────
        if use_cache and results:
            self._cache.set(
                query=query,
                value=results,
                context=cache_context,
                ttl_seconds=cache_ttl,
            )

        return results

    def search_by_sender(
        self,
        query: str,
        sender_email: str,
        top_k: Optional[int] = None,
    ) -> list[VectorSearchResult]:
        """Searches ChromaDB filtered by a specific sender email.

        Args:
            query: Natural language query string.
            sender_email: Email address to filter results by.
            top_k: Number of results to return.

        Returns:
            List of VectorSearchResult objects from the specified sender.
        """
        return self._vector_store.search_by_sender(
            query=query,
            sender_email=sender_email,
            top_k=top_k,
        )

    def search_by_department(
        self,
        query: str,
        department: str,
        top_k: Optional[int] = None,
    ) -> list[VectorSearchResult]:
        """Searches ChromaDB filtered by department.

        Args:
            query: Natural language query string.
            department: Department name to filter by.
            top_k: Number of results to return.

        Returns:
            List of VectorSearchResult objects from the department.
        """
        return self._vector_store.search_by_department(
            query=query,
            department=department,
            top_k=top_k,
        )

    # ── Graph Operations ─────────────────────────────────────────────────────

    def upsert_person(self, person: PersonNode) -> None:
        """Creates or updates a Person node in the knowledge graph.

        Args:
            person: PersonNode object to upsert.
        """
        self._require_graph()
        self._graph_store.upsert_person(person)  # type: ignore[union-attr]

    def upsert_decision(self, decision: DecisionNode) -> None:
        """Creates or updates a Decision node in the knowledge graph.

        Args:
            decision: DecisionNode object to upsert.
        """
        self._require_graph()
        self._graph_store.upsert_decision(decision)  # type: ignore[union-attr]

    def upsert_project(self, project: ProjectNode) -> None:
        """Creates or updates a Project node in the knowledge graph.

        Args:
            project: ProjectNode object to upsert.
        """
        self._require_graph()
        self._graph_store.upsert_project(project)  # type: ignore[union-attr]

    def upsert_policy(self, policy: PolicyNode) -> None:
        """Creates or updates a Policy node in the knowledge graph.

        Args:
            policy: PolicyNode object to upsert.
        """
        self._require_graph()
        self._graph_store.upsert_policy(policy)  # type: ignore[union-attr]

    def create_relationship(self, relationship: GraphRelationship) -> None:
        """Creates a directed relationship between two graph nodes.

        Args:
            relationship: GraphRelationship object defining the edge.
        """
        self._require_graph()
        self._graph_store.create_relationship(relationship)  # type: ignore[union-attr]

    def get_person(self, email: str) -> Optional[dict]:
        """Retrieves a Person node by email address from the graph.

        Args:
            email: Email address to look up.

        Returns:
            Dictionary of person properties, or None if not found.
        """
        if not self._graph_store:
            return None
        return self._graph_store.get_person_by_email(email)

    def get_decisions_by_person(self, email: str) -> list[dict]:
        """Retrieves all decisions linked to a person from the graph.

        Args:
            email: Email address of the person.

        Returns:
            List of decision property dictionaries.
        """
        if not self._graph_store:
            return []
        return self._graph_store.get_decisions_by_person(email)

    def get_decisions_by_department(self, department: str) -> list[dict]:
        """Retrieves all decisions for a department from the graph.

        Args:
            department: Department name to filter by.

        Returns:
            List of decision property dictionaries.
        """
        if not self._graph_store:
            return []
        return self._graph_store.get_decisions_by_department(department)

    def get_communication_network(self, email: str) -> list[dict]:
        """Retrieves all people a person has communicated with.

        Args:
            email: Email address of the central person.

        Returns:
            List of connected person property dictionaries.
        """
        if not self._graph_store:
            return []
        return self._graph_store.get_communication_network(email)

    def search_decisions_graph(self, keyword: str) -> list[dict]:
        """Keyword search over Decision nodes in the graph.

        Args:
            keyword: Keyword to search in decision summaries.

        Returns:
            List of matching decision property dictionaries.
        """
        if not self._graph_store:
            return []
        return self._graph_store.search_decisions(keyword)

    # ── Cache Operations ─────────────────────────────────────────────────────

    def invalidate_cache(
        self,
        query: str,
        context: Optional[str] = None,
    ) -> bool:
        """Removes a specific query result from the cache.

        Args:
            query: The query string whose cache entry to remove.
            context: Optional context used when entry was stored.

        Returns:
            True if entry was found and removed, False otherwise.
        """
        return self._cache.invalidate(query, context=context)

    def clear_cache(self) -> None:
        """Clears all entries from the query cache."""
        self._cache.clear()

    # ── Health Check ─────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Returns aggregated health status from all memory subsystems.

        Used by the FastAPI health endpoint and the audit orchestrator
        to verify system readiness.

        Returns:
            Dictionary with status and stats for each subsystem.
        """
        health: dict[str, Any] = {
            "status": "healthy",
            "subsystems": {},
        }

        # Vector store health
        try:
            vector_stats = self._vector_store.get_stats()
            health["subsystems"]["vector_store"] = {
                "status": "healthy",
                **vector_stats,
            }
        except Exception as exc:
            health["subsystems"]["vector_store"] = {
                "status": "unhealthy",
                "error": str(exc),
            }
            health["status"] = "degraded"

        # Graph store health
        if self._graph_store:
            try:
                graph_stats = self._graph_store.get_stats()
                health["subsystems"]["graph_store"] = {
                    "status": "healthy",
                    **graph_stats,
                }
            except Exception as exc:
                health["subsystems"]["graph_store"] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }
                health["status"] = "degraded"
        else:
            health["subsystems"]["graph_store"] = {
                "status": "disabled",
                "reason": "Neo4j unavailable at startup",
            }

        # Cache health
        try:
            cache_stats = self._cache.get_stats()
            health["subsystems"]["cache"] = {
                "status": "healthy",
                **cache_stats.model_dump(),
            }
        except Exception as exc:
            health["subsystems"]["cache"] = {
                "status": "unhealthy",
                "error": str(exc),
            }
            health["status"] = "degraded"

        return health

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _require_graph(self) -> None:
        """Raises an error if the graph store is not available.

        Raises:
            RuntimeError: If GraphStore was not initialised successfully.
        """
        if not self._graph_store:
            raise RuntimeError(
                "GraphStore is unavailable. "
                "Ensure Neo4j is running and credentials are correct."
            )

    def close(self) -> None:
        """Closes all subsystem connections gracefully.

        Should be called on application shutdown via FastAPI lifespan
        or explicit teardown.
        """
        if self._graph_store:
            self._graph_store.close()

        logger.info("MemoryManager shut down cleanly.")


# ── Module-level singleton ────────────────────────────────────────────────────
# Shared instance imported by all agents and orchestrators.

memory_manager = MemoryManager()