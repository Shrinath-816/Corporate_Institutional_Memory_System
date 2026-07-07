"""
Module: ingestion/pipeline.py

Purpose:
    Orchestrates the complete end-to-end data ingestion pipeline for
    the Institutional Memory System.

Responsibilities:
    - Coordinate all ingestion stages in the correct sequence:
      parse → extract metadata → chunk → embed → store.
    - Provide a single entry point function for triggering ingestion.
    - Report a structured summary of the pipeline run.
    - Handle failures at each stage gracefully without aborting
      the entire pipeline.
    - Save processed emails to the configured CSV path for reference.

Workflow:
    Phase 1 — Parse raw emails from CSV via email_parser.py
    Phase 2 — Extract semantic metadata via metadata_extractor.py
    Phase 3 — Chunk cleaned emails via chunker.py
    Phase 4 — Embed chunks and store in ChromaDB via embedder.py
    Phase 5 — Persist clean emails to processed CSV
    Phase 6 — Return a PipelineResult summary
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field

from config.settings import settings
from ingestion.email_parser import load_and_parse_emails
from ingestion.metadata_extractor import extract_metadata_batch
from ingestion.chunker import chunk_emails
from ingestion.embedder import embed_and_store, get_collection_stats
from schemas.email_schema import CleanEmail


# ── Pipeline Result Model ────────────────────────────────────────────────────

class PipelineResult(BaseModel):
    """Structured summary of a completed ingestion pipeline run.

    Returned by run_ingestion_pipeline() and logged for observability.
    Useful for health checks, dashboards, and debugging.
    """

    started_at: datetime = Field(..., description="Pipeline start timestamp")
    completed_at: datetime = Field(..., description="Pipeline completion timestamp")
    duration_seconds: float = Field(..., description="Total pipeline duration in seconds")
    emails_parsed: int = Field(..., description="Number of emails parsed from CSV")
    emails_clean: int = Field(..., description="Number of emails that passed cleaning")
    chunks_created: int = Field(..., description="Total chunks produced by chunker")
    chunks_stored: int = Field(..., description="Total chunks stored in ChromaDB")
    collection_total: int = Field(..., description="Total documents in ChromaDB after run")
    metadata_extracted: int = Field(..., description="Number of metadata records extracted")
    processed_csv_saved: bool = Field(
        ..., description="Whether the clean CSV was saved successfully"
    )
    success: bool = Field(..., description="True if all stages completed without error")
    errors: list[str] = Field(
        default_factory=list,
        description="List of non-fatal errors encountered during the run"
    )


# ── Private Stage Functions ──────────────────────────────────────────────────

def _save_processed_csv(
    emails: list[CleanEmail],
    output_path: str,
) -> bool:
    """Persists the list of CleanEmail objects to a CSV file.

    Saves the processed emails so they can be inspected or re-used
    without re-running the parsing stage.

    Args:
        emails: List of CleanEmail objects to persist.
        output_path: File path where the CSV will be written.

    Returns:
        True if the file was saved successfully, False otherwise.
    """
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        records = [
            {
                "message_id": email.message_id,
                "date": email.date.isoformat(),
                "sender": email.sender,
                "receiver": email.receiver,
                "subject": email.subject,
                "body": email.body,
                "word_count": email.word_count,
                "department": email.department or "",
            }
            for email in emails
        ]

        pd.DataFrame(records).to_csv(output_path, index=False, encoding="utf-8")
        logger.info("Processed CSV saved to '{}'", output_path)
        return True

    except Exception as exc:
        logger.error("Failed to save processed CSV: {}", exc)
        return False


def _run_parse_stage(
    csv_path: str,
    max_emails: int,
    errors: list[str],
) -> list[CleanEmail]:
    """Executes the parsing stage of the pipeline.

    Args:
        csv_path: Path to the raw emails CSV file.
        max_emails: Maximum emails to parse.
        errors: Mutable list to append non-fatal error messages to.

    Returns:
        List of CleanEmail objects. Empty list on failure.
    """
    logger.info("── Stage 1: Parsing emails ──")
    try:
        emails = load_and_parse_emails(
            csv_path=csv_path,
            max_emails=max_emails,
        )
        logger.info("Stage 1 complete | clean_emails={}", len(emails))
        return emails
    except Exception as exc:
        error_msg = f"Parse stage failed: {exc}"
        logger.error(error_msg)
        errors.append(error_msg)
        return []


def _run_metadata_stage(
    emails: list[CleanEmail],
    errors: list[str],
) -> int:
    """Executes the metadata extraction stage of the pipeline.

    Args:
        emails: List of CleanEmail objects to extract metadata from.
        errors: Mutable list to append non-fatal error messages to.

    Returns:
        Count of metadata records successfully extracted.
    """
    logger.info("── Stage 2: Extracting metadata ──")
    try:
        metadata_records = extract_metadata_batch(emails)
        logger.info(
            "Stage 2 complete | metadata_records={}", len(metadata_records)
        )
        return len(metadata_records)
    except Exception as exc:
        error_msg = f"Metadata extraction stage failed: {exc}"
        logger.error(error_msg)
        errors.append(error_msg)
        return 0


def _run_chunk_stage(
    emails: list[CleanEmail],
    errors: list[str],
) -> list:
    """Executes the chunking stage of the pipeline.

    Args:
        emails: List of CleanEmail objects to chunk.
        errors: Mutable list to append non-fatal error messages to.

    Returns:
        List of EmailChunk objects. Empty list on failure.
    """
    logger.info("── Stage 3: Chunking emails ──")
    try:
        chunks = chunk_emails(emails)
        logger.info("Stage 3 complete | chunks={}", len(chunks))
        return chunks
    except Exception as exc:
        error_msg = f"Chunking stage failed: {exc}"
        logger.error(error_msg)
        errors.append(error_msg)
        return []


def _run_embed_stage(
    chunks: list,
    errors: list[str],
) -> int:
    """Executes the embedding and storage stage of the pipeline.

    Args:
        chunks: List of EmailChunk objects to embed and store.
        errors: Mutable list to append non-fatal error messages to.

    Returns:
        Count of chunks successfully stored in ChromaDB.
    """
    logger.info("── Stage 4: Embedding and storing chunks ──")
    try:
        stored = embed_and_store(chunks)
        logger.info("Stage 4 complete | stored={}", stored)
        return stored
    except Exception as exc:
        error_msg = f"Embedding stage failed: {exc}"
        logger.error(error_msg)
        errors.append(error_msg)
        return 0


# ── Public Entry Point ───────────────────────────────────────────────────────

def run_ingestion_pipeline(
    csv_path: Optional[str] = None,
    max_emails: Optional[int] = None,
    save_processed_csv: bool = True,
) -> PipelineResult:
    """Runs the complete end-to-end ingestion pipeline.

    This is the single public entry point for the ingestion system.
    It coordinates all four stages in sequence and returns a structured
    PipelineResult summarising the run.

    The pipeline is designed to be fault-tolerant: individual stage
    failures are recorded as errors but do not abort subsequent stages
    where possible.

    Args:
        csv_path: Path to the raw emails CSV. Defaults to settings value.
        max_emails: Maximum emails to ingest. Defaults to settings value.
        save_processed_csv: Whether to persist clean emails to CSV.
            Defaults to True.

    Returns:
        A PipelineResult object containing counts, timing, and any
        errors encountered during the run.
    """
    started_at = datetime.utcnow()
    start_time = time.perf_counter()
    errors: list[str] = []

    resolved_csv_path = csv_path or settings.data.raw_data_path
    resolved_max_emails = max_emails or settings.data.max_emails_to_ingest

    logger.info(
        "═══ Ingestion Pipeline Started ═══ | source='{}' | limit={}",
        resolved_csv_path,
        resolved_max_emails,
    )

    # ── Stage 1: Parse ───────────────────────────────────────────────────────
    emails = _run_parse_stage(
        csv_path=resolved_csv_path,
        max_emails=resolved_max_emails,
        errors=errors,
    )

    if not emails:
        logger.error("Pipeline aborted — no emails parsed.")
        return PipelineResult(
            started_at=started_at,
            completed_at=datetime.utcnow(),
            duration_seconds=round(time.perf_counter() - start_time, 2),
            emails_parsed=0,
            emails_clean=0,
            chunks_created=0,
            chunks_stored=0,
            collection_total=0,
            metadata_extracted=0,
            processed_csv_saved=False,
            success=False,
            errors=errors,
        )

    # ── Stage 2: Extract Metadata ─────────────────────────────────────────────
    metadata_count = _run_metadata_stage(emails=emails, errors=errors)

    # ── Stage 3: Chunk ───────────────────────────────────────────────────────
    chunks = _run_chunk_stage(emails=emails, errors=errors)

    # ── Stage 4: Embed and Store ──────────────────────────────────────────────
    chunks_stored = 0
    if chunks:
        chunks_stored = _run_embed_stage(chunks=chunks, errors=errors)

    # ── Stage 5: Save Processed CSV ───────────────────────────────────────────
    csv_saved = False
    if save_processed_csv and emails:
        csv_saved = _save_processed_csv(
            emails=emails,
            output_path=settings.data.processed_data_path,
        )

    # ── Stage 6: Collect Final Stats ──────────────────────────────────────────
    collection_stats = get_collection_stats()
    completed_at = datetime.utcnow()
    duration = round(time.perf_counter() - start_time, 2)

    result = PipelineResult(
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        emails_parsed=resolved_max_emails,
        emails_clean=len(emails),
        chunks_created=len(chunks),
        chunks_stored=chunks_stored,
        collection_total=collection_stats["total_documents"],
        metadata_extracted=metadata_count,
        processed_csv_saved=csv_saved,
        success=len(errors) == 0,
        errors=errors,
    )

    logger.info(
        "═══ Ingestion Pipeline Complete ═══ | "
        "duration={}s | clean={} | chunks={} | stored={} | errors={}",
        duration,
        len(emails),
        len(chunks),
        chunks_stored,
        len(errors),
    )

    return result


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Allows the pipeline to be triggered directly from the command line.

    Usage:
        python -m ingestion.pipeline
    """
    from config.logging_config import setup_logging

    setup_logging()

    result = run_ingestion_pipeline()

    print("\n══════════ Pipeline Result ══════════")
    print(f"  Success          : {result.success}")
    print(f"  Duration         : {result.duration_seconds}s")
    print(f"  Emails Clean     : {result.emails_clean}")
    print(f"  Chunks Created   : {result.chunks_created}")
    print(f"  Chunks Stored    : {result.chunks_stored}")
    print(f"  Collection Total : {result.collection_total}")
    print(f"  Errors           : {len(result.errors)}")
    if result.errors:
        for error in result.errors:
            print(f"    ✗ {error}")
    print("═════════════════════════════════════\n")