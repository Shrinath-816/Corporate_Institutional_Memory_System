"""
Module: memory/vector_store.py

Purpose:
    Provides a clean, reusable interface over ChromaDB for all agents
    and orchestrators in the Institutional Memory System.

Responsibilities:
    - Abstract all ChromaDB operations behind a VectorStore class.
    - Support semantic search with optional metadata filtering.
    - Support filtered searches by sender, department, date, and intent.
    - Provide collection statistics for health checks and audits.
    - Decouple agents from direct ChromaDB dependency.

Workflow:
    Phase 1 — Initialise ChromaDB client and collection on first use.
    Phase 2 — Accept search queries from agents.
    Phase 3 — Embed queries and retrieve similar chunks.
    Phase 4 — Return structured VectorSearchResult objects.
"""

from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger
from sentence_transformers import SentenceTransformer

from config.settings import settings
from schemas.memory_schema import VectorSearchResult


class VectorStore:
    """Abstracts all ChromaDB operations for the Institutional Memory System.

    Provides semantic search, filtered search, and collection management
    as a clean interface consumed by all retrieval agents.

    Attributes:
        _client: The ChromaDB persistent client instance.
        _collection: The active ChromaDB collection.
        _embedding_model: The SentenceTransformer model for query embedding.
    """

    def __init__(self) -> None:
        """Initialises the VectorStore with ChromaDB client and embedding model."""
        logger.info(
            "Initialising VectorStore | dir='{}' | collection='{}'",
            settings.chromadb.persist_directory,
            settings.chromadb.collection_name,
        )

        self._embedding_model = SentenceTransformer(
            settings.chromadb.embedding_model
        )

        self._client = chromadb.PersistentClient(
            path=settings.chromadb.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self._collection = self._client.get_or_create_collection(
            name=settings.chromadb.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "VectorStore ready | total_docs={}",
            self._collection.count(),
        )

    def _embed_query(self, query: str) -> list[float]:
        """Embeds a query string into a vector using the embedding model.

        Args:
            query: The natural language query string to embed.

        Returns:
            A list of floats representing the query embedding vector.
        """
        embedding = self._embedding_model.encode(
            query,
            convert_to_numpy=True,
        )
        return embedding.tolist()

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        metadata_filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Performs semantic similarity search against the ChromaDB collection.

        Args:
            query: Natural language query string.
            top_k: Number of results to return. Defaults to settings value.
            metadata_filter: Optional ChromaDB where-clause filter.
                Example: {"sender": "phillip.allen@enron.com"}

        Returns:
            List of VectorSearchResult objects ordered by relevance.

        Raises:
            ValueError: If query is empty.
        """
        if not query or not query.strip():
            raise ValueError("Query must not be empty.")

        k = top_k or settings.chromadb.top_k_results
        total_docs = self._collection.count()

        if total_docs == 0:
            logger.warning("ChromaDB collection is empty.")
            return []

        query_embedding = self._embed_query(query)

        query_kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": min(k, total_docs),
            "include": ["documents", "metadatas", "distances"],
        }

        if metadata_filter:
            query_kwargs["where"] = metadata_filter

        raw = self._collection.query(**query_kwargs)

        results: list[VectorSearchResult] = [
            VectorSearchResult(
                chunk_id=meta.get("message_id", "unknown"),
                text=doc,
                distance=dist,
                metadata=meta,
            )
            for doc, meta, dist in zip(
                raw["documents"][0],
                raw["metadatas"][0],
                raw["distances"][0],
            )
        ]

        logger.debug(
            "VectorStore search | query='{}' | results={}",
            query[:60],
            len(results),
        )

        return results

    def search_by_sender(
        self,
        query: str,
        sender_email: str,
        top_k: Optional[int] = None,
    ) -> list[VectorSearchResult]:
        """Searches for chunks filtered by a specific sender email.

        Args:
            query: Natural language query string.
            sender_email: Email address to filter results by.
            top_k: Number of results to return.

        Returns:
            List of VectorSearchResult objects from the specified sender.
        """
        return self.search(
            query=query,
            top_k=top_k,
            metadata_filter={"sender": sender_email.lower()},
        )

    def search_by_department(
        self,
        query: str,
        department: str,
        top_k: Optional[int] = None,
    ) -> list[VectorSearchResult]:
        """Searches for chunks filtered by department.

        Args:
            query: Natural language query string.
            department: Department name to filter results by.
            top_k: Number of results to return.

        Returns:
            List of VectorSearchResult objects from the specified department.
        """
        return self.search(
            query=query,
            top_k=top_k,
            metadata_filter={"department": department},
        )

    def get_by_message_id(self, message_id: str) -> Optional[VectorSearchResult]:
        """Retrieves a specific chunk by its parent email message ID.

        Args:
            message_id: The email message ID to retrieve chunks for.

        Returns:
            The first matching VectorSearchResult, or None if not found.
        """
        try:
            raw = self._collection.get(
                where={"message_id": message_id},
                include=["documents", "metadatas"],
            )

            if not raw["documents"]:
                return None

            return VectorSearchResult(
                chunk_id=raw["ids"][0],
                text=raw["documents"][0],
                distance=0.0,
                metadata=raw["metadatas"][0],
            )

        except Exception as exc:
            logger.error(
                "Failed to retrieve message_id='{}': {}", message_id, exc
            )
            return None

    def get_stats(self) -> dict:
        """Returns collection statistics for health checks and audits.

        Returns:
            Dictionary containing collection name, document count,
            and persistence directory.
        """
        return {
            "collection_name": settings.chromadb.collection_name,
            "total_documents": self._collection.count(),
            "persist_directory": settings.chromadb.persist_directory,
            "embedding_model": settings.chromadb.embedding_model,
        }

    def delete_collection(self) -> None:
        """Deletes the entire ChromaDB collection.

        Warning: This is irreversible. Used only for testing or reset.
        """
        logger.warning(
            "Deleting ChromaDB collection '{}'",
            settings.chromadb.collection_name,
        )
        self._client.delete_collection(settings.chromadb.collection_name)
        logger.info("Collection deleted.")