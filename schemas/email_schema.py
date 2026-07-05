"""
Module: schemas/email_schema.py

Purpose:
    Pydantic models representing the structure of email data at every
    stage of the ingestion pipeline.

Responsibilities:
    - Define the raw parsed email structure as ingested from the CSV.
    - Define the cleaned and validated email structure used downstream.
    - Define the chunked email fragment structure stored in ChromaDB.
    - Enforce type safety and field-level validation across the pipeline.

Workflow:
    RawEmail → CleanEmail → EmailChunk → ChromaDB storage
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, EmailStr


class RawEmail(BaseModel):
    """Represents a single email as parsed directly from the Enron CSV.

    No cleaning or validation is applied at this stage — this model
    captures the raw state of data before the cleaning pipeline runs.
    """

    file_path: str = Field(..., description="Original file path identifier from CSV")
    message_id: Optional[str] = Field(None, description="Unique email message ID")
    date: Optional[str] = Field(None, description="Raw unparsed date string")
    sender: Optional[str] = Field(None, description="Raw sender email address")
    receiver: Optional[str] = Field(None, description="Raw receiver email address(es)")
    subject: Optional[str] = Field(None, description="Email subject line")
    body: Optional[str] = Field(None, description="Raw email body text")


class CleanEmail(BaseModel):
    """Represents a fully cleaned and validated email ready for embedding.

    All fields are normalised, validated, and stripped of noise. This is
    the canonical email representation used by the ingestion pipeline.
    """

    message_id: str = Field(..., description="Unique email message ID")
    date: datetime = Field(..., description="Parsed and validated email timestamp")
    sender: str = Field(..., description="Normalised sender email address")
    receiver: str = Field(..., description="Normalised receiver email address(es)")
    subject: str = Field(default="", description="Cleaned subject line")
    body: str = Field(..., description="Cleaned email body with noise removed")
    word_count: int = Field(..., ge=1, description="Word count of cleaned body")
    department: Optional[str] = Field(
        None, description="Inferred department from sender domain or folder path"
    )

    @field_validator("body")
    @classmethod
    def body_must_have_content(cls, value: str) -> str:
        """Ensures the email body is not empty or whitespace only.

        Args:
            value: The email body string to validate.

        Returns:
            Stripped body string if valid.

        Raises:
            ValueError: If the body is empty or contains only whitespace.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Email body must not be empty after cleaning.")
        return stripped

    @field_validator("sender")
    @classmethod
    def sender_must_be_valid(cls, value: str) -> str:
        """Normalises sender to lowercase and strips whitespace.

        Args:
            value: The raw sender string.

        Returns:
            Lowercase, stripped sender string.

        Raises:
            ValueError: If sender is empty after stripping.
        """
        normalised = value.strip().lower()
        if not normalised:
            raise ValueError("Sender email must not be empty.")
        return normalised


class EmailChunk(BaseModel):
    """Represents a single text chunk derived from a CleanEmail body.

    One CleanEmail can produce multiple EmailChunks. Each chunk is the
    atomic unit stored in ChromaDB with its associated metadata.
    """

    chunk_id: str = Field(
        ..., description="Unique ID for this chunk: '{message_id}_chunk_{index}'"
    )
    message_id: str = Field(..., description="Parent email message ID")
    chunk_index: int = Field(..., ge=0, description="Zero-based index of this chunk")
    text: str = Field(..., description="The chunk text to be embedded")
    sender: str = Field(..., description="Sender email address for metadata filtering")
    receiver: str = Field(..., description="Receiver(s) for metadata filtering")
    subject: str = Field(default="", description="Subject line for metadata filtering")
    date: str = Field(..., description="ISO format date string for metadata filtering")
    word_count: int = Field(..., ge=1, description="Word count of this chunk")
    department: Optional[str] = Field(
        None, description="Inferred department for metadata filtering"
    )