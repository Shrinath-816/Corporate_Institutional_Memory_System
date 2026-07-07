"""
Module: ingestion/embedder.py

Purpose:
    Embeds EmailChunk objects using SentenceTransformers and stores
    them persistently in ChromaDB with full metadata.

Responsibilities:
    - Initialise the SentenceTransformer embedding model once.
    - Initialise the ChromaDB persistent client and collection.
    - Batch-embed chunk texts for memory and performance efficiency.
    - Store embeddings, documents, and metadata into ChromaDB.
    - Support incremental upserts to avoid duplicate storage.
    - Provide a retrieval function for downstream agent use.

Workflow:
    Phase 1 — Initialise embedding model and ChromaDB client.
    Phase 2 — Accept list of EmailChunk objects.
    Phase 3 — Extract texts and generate embeddings in batches.
    Phase 4 — Upsert documents, embeddings, and metadata to ChromaDB.
    Phase 5 — Log progress and return storage summary.
"""

from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from loguru import logger
from tqdm import tqdm

from config.settings import settings
from schemas.email_schema import EmailChunk
from schemas.memory_schema import VectorSearchResult


# ── Module-level singletons ──────────────────────────────────────────────────
# Initialised once on first use to avoid repeated loading overhead.

_embedding_model: Optional[SentenceTransformer] = None
_chroma_client: Optional[chromadb.PersistentClient] = None
_chroma_collection: Optional[chromadb.Collection] = None


def _get_embedding_model() -> SentenceTransformer:
    """Returns the singleton SentenceTransformer embedding model.

    Loads the model from disk on first call. Subsequent calls return
    the cached instance without reloading.

    Returns:
        The loaded SentenceTransformer model instance.
    """
    global _embedding_model

    if _embedding_model is None:
        logger.info(
            "Loading embedding model: '{}'",
            settings.chromadb.embedding_model,
        )
        _embedding_model = SentenceTransformer(settings.chromadb.embedding_model)
        logger.info("Embedding model loaded successfully.")

    return _embedding_model


def _get_chroma_client() -> chromadb.PersistentClient:
    """Returns the singleton ChromaDB persistent client.

    Creates the client and points it to the configured persistence
    directory on first call. Subsequent calls return the cached instance.

    Returns:
        The initialised ChromaDB PersistentClient instance.
    """
    global _chroma_client

    if _chroma_client is None:
        logger.info(
            "Initialising ChromaDB client at '{}'",
            settings.chromadb.persist_directory,
        )
        _chroma_client = chromadb.PersistentClient(
            path=settings.chromadb.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info("ChromaDB client initialised.")

    return _chroma_client


def _get_chroma_collection() -> chromadb.Collection:
    """Returns the singleton ChromaDB collection, creating it if absent.

    Uses get_or_create_collection so that re-runs are safe and do not
    duplicate data when the collection already exists.

    Returns:
        The ChromaDB Collection instance for institutional memory.
    """
    global _chroma_collection

    if _chroma_collection is None:
        client = _get_chroma_client()
        _chroma_collection = client.get_or_create_collection(
            name=settings.chromadb.collection_name,
            # Use cosine similarity — standard for semantic text retrieval
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB collection '{}' ready | existing_docs={}",
            settings.chromadb.collection_name,
            _chroma_collection.count(),
        )

    return _chroma_collection


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Generates embeddings for a list of text strings.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors, one per input text.
    """
    model = _get_embedding_model()
    # convert_to_numpy=False returns Python lists — ChromaDB compatible
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


def _build_metadata(chunk: EmailChunk) -> dict:
    """Constructs the ChromaDB metadata dictionary for a single chunk.

    ChromaDB metadata values must be str, int, or float only.
    None values are replaced with empty strings to avoid storage errors.

    Args:
        chunk: The EmailChunk whose metadata will be stored.

    Returns:
        A flat dictionary of metadata safe for ChromaDB storage.
    """
    return {
        "message_id": chunk.message_id,
        "chunk_index": chunk.chunk_index,
        "sender": chunk.sender,
        "receiver": chunk.receiver,
        "subject": chunk.subject or "",
        "date": chunk.date,
        "word_count": chunk.word_count,
        "department": chunk.department or "",
    }


def embed_and_store(
    chunks: list[EmailChunk],
    batch_size: int = 64,
) -> int:
    """Embeds all EmailChunks and upserts them into ChromaDB.

    Processes chunks in batches to balance memory usage and throughput.
    Uses upsert so that re-running the pipeline is idempotent — existing
    chunks are updated rather than duplicated.

    Args:
        chunks: List of EmailChunk objects to embed and store.
        batch_size: Number of chunks to process per batch. Defaults to 64.

    Returns:
        Total number of chunks successfully stored in ChromaDB.

    Raises:
        ValueError: If the chunks list is empty.
    """
    if not chunks:
        raise ValueError("No chunks provided for embedding.")

    collection = _get_chroma_collection()
    total_stored = 0

    logger.info(
        "Starting embedding pipeline | chunks={} | batch_size={}",
        len(chunks),
        batch_size,
    )

    # Process in batches to avoid OOM on large datasets
    for batch_start in tqdm(
        range(0, len(chunks), batch_size),
        desc="Embedding batches",
        unit="batch",
    ):
        batch = chunks[batch_start : batch_start + batch_size]

        ids = [chunk.chunk_id for chunk in batch]
        texts = [chunk.text for chunk in batch]
        metadatas = [_build_metadata(chunk) for chunk in batch]
        embeddings = _embed_texts(texts)

        try:
            collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            total_stored += len(batch)

        except Exception as exc:
            logger.error(
                "Failed to upsert batch starting at index {}: {}",
                batch_start,
                exc,
            )
            # Continue with next batch rather than aborting entire pipeline
            continue

    logger.info(
        "Embedding complete | stored={} | collection_total={}",
        total_stored,
        collection.count(),
    )

    return total_stored


def search(
    query: str,
    top_k: Optional[int] = None,
    metadata_filter: Optional[dict] = None,
) -> list[VectorSearchResult]:
    """Performs a semantic similarity search against the ChromaDB collection.

    Embeds the query string and retrieves the most similar chunks
    using cosine similarity. Optionally filters results by metadata.

    Args:
        query: The natural language query string to search for.
        top_k: Number of results to return. Defaults to settings value.
        metadata_filter: Optional ChromaDB where-clause filter dictionary.
            Example: {"sender": "phillip.allen@enron.com"}

    Returns:
        A list of VectorSearchResult objects ordered by relevance
        (most similar first).

    Raises:
        ValueError: If the query string is empty.
    """
    if not query or not query.strip():
        raise ValueError("Query string must not be empty.")

    k = top_k or settings.chromadb.top_k_results
    collection = _get_chroma_collection()

    query_embedding = _embed_texts([query])[0]

    query_kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": min(k, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }

    # Only pass where filter if provided — ChromaDB errors on empty where clause
    if metadata_filter:
        query_kwargs["where"] = metadata_filter

    results = collection.query(**query_kwargs)

    search_results: list[VectorSearchResult] = []

    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        search_results.append(
            VectorSearchResult(
                chunk_id=meta.get("message_id", "unknown"),
                text=doc,
                distance=dist,
                metadata=meta,
            )
        )

    logger.debug(
        "Search complete | query='{}' | results={}",
        query[:60],
        len(search_results),
    )

    return search_results


def get_collection_stats() -> dict:
    """Returns basic statistics about the ChromaDB collection.

    Useful for health checks and the audit dashboard.

    Returns:
        A dictionary containing collection name and document count.
    """
    collection = _get_chroma_collection()
    return {
        "collection_name": settings.chromadb.collection_name,
        "total_documents": collection.count(),
        "persist_directory": settings.chromadb.persist_directory,
    }