"""
Module: ingestion/chunker.py

Purpose:
    Splits cleaned email bodies into smaller text chunks suitable
    for embedding and storage in ChromaDB.

Responsibilities:
    - Accept a list of CleanEmail objects from the parser.
    - Split each email body into overlapping chunks using
      LangChain's RecursiveCharacterTextSplitter.
    - Attach full metadata to every chunk for downstream filtering.
    - Construct and return validated EmailChunk Pydantic objects.

Workflow:
    Phase 1 — Initialise the text splitter with configured chunk
              size and overlap from settings.
    Phase 2 — Iterate over each CleanEmail object.
    Phase 3 — Split the email body into raw text chunks.
    Phase 4 — Wrap each chunk in an EmailChunk model with metadata.
    Phase 5 — Return the complete flat list of EmailChunk objects.
"""

from loguru import logger
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings
from schemas.email_schema import CleanEmail, EmailChunk


def _build_text_splitter() -> RecursiveCharacterTextSplitter:
    """Constructs the LangChain text splitter using application settings.

    Uses RecursiveCharacterTextSplitter which attempts to split on
    paragraph breaks, then sentence breaks, then word breaks — in that
    order — to preserve semantic coherence within each chunk.

    Returns:
        A configured RecursiveCharacterTextSplitter instance.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.data.chunk_size,
        chunk_overlap=settings.data.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _build_chunk_id(message_id: str, chunk_index: int) -> str:
    """Generates a deterministic unique ID for a chunk.

    Format: '{sanitised_message_id}_chunk_{index}'

    Args:
        message_id: The parent email's message ID.
        chunk_index: The zero-based index of this chunk.

    Returns:
        A unique string ID for this chunk.
    """
    # Sanitise message_id — remove characters invalid for ChromaDB IDs
    sanitised = (
        message_id
        .replace("<", "")
        .replace(">", "")
        .replace(" ", "_")
        .replace("/", "_")
    )
    return f"{sanitised}_chunk_{chunk_index}"


def _chunk_single_email(
    email: CleanEmail,
    splitter: RecursiveCharacterTextSplitter,
) -> list[EmailChunk]:
    """Splits a single CleanEmail body into a list of EmailChunk objects.

    Each chunk inherits the full metadata of its parent email so that
    ChromaDB metadata filtering works correctly at retrieval time.

    Args:
        email: The CleanEmail object whose body will be chunked.
        splitter: The configured RecursiveCharacterTextSplitter instance.

    Returns:
        A list of EmailChunk objects derived from this email. Returns
        an empty list if splitting produces no usable chunks.
    """
    raw_chunks: list[str] = splitter.split_text(email.body)

    if not raw_chunks:
        logger.debug(
            "No chunks produced for message_id='{}'", email.message_id
        )
        return []

    email_chunks: list[EmailChunk] = []

    for index, chunk_text in enumerate(raw_chunks):
        # Skip chunks that are too short to be meaningful after splitting
        if len(chunk_text.split()) < 5:
            continue

        chunk = EmailChunk(
            chunk_id=_build_chunk_id(email.message_id, index),
            message_id=email.message_id,
            chunk_index=index,
            text=chunk_text,
            sender=email.sender,
            receiver=email.receiver,
            subject=email.subject,
            # Store date as ISO string — ChromaDB metadata must be str/int/float
            date=email.date.isoformat(),
            word_count=len(chunk_text.split()),
            department=email.department,
        )
        email_chunks.append(chunk)

    return email_chunks


def chunk_emails(emails: list[CleanEmail]) -> list[EmailChunk]:
    """Chunks all CleanEmail objects into a flat list of EmailChunk objects.

    This is the primary public function of this module. It initialises
    the text splitter once and reuses it across all emails for efficiency.

    Args:
        emails: List of validated CleanEmail objects from the parser.

    Returns:
        A flat list of EmailChunk objects ready for embedding and
        storage in ChromaDB.

    Raises:
        ValueError: If the emails list is empty.
    """
    if not emails:
        raise ValueError("No emails provided for chunking.")

    logger.info(
        "Starting chunking pipeline | emails={} | chunk_size={} | overlap={}",
        len(emails),
        settings.data.chunk_size,
        settings.data.chunk_overlap,
    )

    splitter = _build_text_splitter()
    all_chunks: list[EmailChunk] = []
    empty_count = 0

    for email in emails:
        chunks = _chunk_single_email(email, splitter)

        if not chunks:
            empty_count += 1
            continue

        all_chunks.extend(chunks)

    logger.info(
        "Chunking complete | total_chunks={} | emails_skipped={}",
        len(all_chunks),
        empty_count,
    )

    return all_chunks