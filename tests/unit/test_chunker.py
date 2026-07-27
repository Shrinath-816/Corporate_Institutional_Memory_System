"""
Module: tests/unit/test_chunker.py

Purpose:
    Unit tests for ingestion/chunker.py — verifies that CleanEmail
    objects are correctly split into EmailChunk objects with accurate
    metadata propagation and chunk ID generation.

Responsibilities:
    - Test chunk ID generation and sanitisation.
    - Test single-email chunking behaviour, including short-chunk filtering.
    - Test the public chunk_emails() function across multiple emails.
    - Test error handling for empty input.
"""

from datetime import datetime

import pytest

from ingestion.chunker import (
    _build_chunk_id,
    _build_text_splitter,
    _chunk_single_email,
    chunk_emails,
)
from schemas.email_schema import CleanEmail, EmailChunk


# ── _build_chunk_id ───────────────────────────────────────────────────────────

class TestBuildChunkId:
    """Tests for chunk ID generation and sanitisation."""

    def test_generates_expected_format(self) -> None:
        """Chunk ID should follow '{sanitised_id}_chunk_{index}' format."""
        chunk_id = _build_chunk_id("<12345@enron.com>", 0)
        assert chunk_id == "12345@enron.com_chunk_0"

    def test_sanitises_angle_brackets(self) -> None:
        """Angle brackets should be stripped from the message ID."""
        chunk_id = _build_chunk_id("<abc123.evans@thyme>", 2)
        assert "<" not in chunk_id
        assert ">" not in chunk_id

    def test_sanitises_spaces_and_slashes(self) -> None:
        """Spaces and slashes should be replaced with underscores."""
        chunk_id = _build_chunk_id("allen-p/sent mail/1", 0)
        assert " " not in chunk_id
        assert "/" not in chunk_id
        assert chunk_id == "allen-p_sent_mail_1_chunk_0"

    def test_different_indices_produce_different_ids(self) -> None:
        """Same message ID with different chunk indices must be unique."""
        id_0 = _build_chunk_id("<msg@enron.com>", 0)
        id_1 = _build_chunk_id("<msg@enron.com>", 1)
        assert id_0 != id_1


# ── _chunk_single_email ───────────────────────────────────────────────────────

class TestChunkSingleEmail:
    """Tests for chunking an individual CleanEmail object."""

    def test_produces_at_least_one_chunk_for_normal_email(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """A normal-length email body should produce at least one chunk."""
        splitter = _build_text_splitter()
        chunks = _chunk_single_email(sample_clean_email, splitter)

        assert len(chunks) >= 1
        assert all(isinstance(c, EmailChunk) for c in chunks)

    def test_chunk_inherits_parent_metadata(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """Each chunk should inherit sender, receiver, subject, and department."""
        splitter = _build_text_splitter()
        chunks = _chunk_single_email(sample_clean_email, splitter)

        for chunk in chunks:
            assert chunk.sender == sample_clean_email.sender
            assert chunk.receiver == sample_clean_email.receiver
            assert chunk.subject == sample_clean_email.subject
            assert chunk.department == sample_clean_email.department
            assert chunk.message_id == sample_clean_email.message_id

    def test_date_stored_as_iso_string(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """Chunk date field must be an ISO string, not a datetime object."""
        splitter = _build_text_splitter()
        chunks = _chunk_single_email(sample_clean_email, splitter)

        for chunk in chunks:
            assert isinstance(chunk.date, str)
            # Should be parseable back into a datetime
            datetime.fromisoformat(chunk.date)

    def test_filters_out_very_short_chunks(self) -> None:
        """Chunks with fewer than 5 words should be dropped."""
        short_email = CleanEmail(
            message_id="<short@enron.com>",
            date=datetime(2001, 1, 1),
            sender="a@enron.com",
            receiver="b@enron.com",
            subject="Hi",
            body="Ok thanks.",
            word_count=2,
            department="Inbox",
        )
        splitter = _build_text_splitter()
        chunks = _chunk_single_email(short_email, splitter)

        assert chunks == []

    def test_chunk_ids_are_sequential(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """Multiple chunks from the same email must have increasing indices."""
        # Force a long body to guarantee multiple chunks
        long_email = sample_clean_email.model_copy(
            update={"body": "This is an important sentence. " * 200}
        )
        splitter = _build_text_splitter()
        chunks = _chunk_single_email(long_email, splitter)

        indices = [c.chunk_index for c in chunks]
        assert indices == sorted(indices)
        assert indices == list(range(len(chunks)))


# ── chunk_emails (public API) ─────────────────────────────────────────────────

class TestChunkEmails:
    """Tests for the public chunk_emails() batch function."""

    def test_raises_on_empty_list(self) -> None:
        """An empty email list must raise ValueError."""
        with pytest.raises(ValueError, match="No emails provided"):
            chunk_emails([])

    def test_returns_flat_list_across_multiple_emails(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """chunk_emails should return a single flat list, not nested lists."""
        second_email = sample_clean_email.model_copy(
            update={"message_id": "<second@enron.com>"}
        )
        chunks = chunk_emails([sample_clean_email, second_email])

        assert isinstance(chunks, list)
        assert all(isinstance(c, EmailChunk) for c in chunks)

        message_ids = {c.message_id for c in chunks}
        assert sample_clean_email.message_id in message_ids
        assert second_email.message_id in message_ids

    def test_skips_emails_that_produce_no_chunks(
        self, sample_clean_email: CleanEmail
    ) -> None:
        """An email that produces zero chunks should not break the batch."""
        short_email = CleanEmail(
            message_id="<short@enron.com>",
            date=datetime(2001, 1, 1),
            sender="a@enron.com",
            receiver="b@enron.com",
            subject="Hi",
            body="Ok thanks.",
            word_count=2,
            department="Inbox",
        )

        chunks = chunk_emails([sample_clean_email, short_email])

        message_ids = {c.message_id for c in chunks}
        assert sample_clean_email.message_id in message_ids
        assert short_email.message_id not in message_ids