"""
Module: ingestion/email_parser.py

Purpose:
    Parses and cleans raw Enron email data from the CSV file into
    validated CleanEmail objects ready for the chunking pipeline.

Responsibilities:
    - Read raw emails from the CSV file using pandas.
    - Extract structured fields: message_id, date, sender, receiver,
      subject, and body from raw email text.
    - Remove noise: forwarded headers, reply chains, signatures,
      auto-replies, and calendar invites.
    - Validate and construct CleanEmail Pydantic models.
    - Skip and log malformed or empty emails gracefully.

Workflow:
    Phase 1 — Load raw CSV into a pandas DataFrame.
    Phase 2 — Parse each raw email string into structured fields.
    Phase 3 — Clean the extracted body text.
    Phase 4 — Validate fields and construct CleanEmail objects.
    Phase 5 — Return a list of CleanEmail objects for downstream use.
"""

import re  
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import settings
from schemas.email_schema import CleanEmail, RawEmail


# ── Noise patterns to strip from email bodies ───────────────────────────────

# Matches forwarded message header blocks
_FORWARDED_PATTERN = re.compile(
    r"-+\s*Forwarded by.*?-+", flags=re.DOTALL | re.IGNORECASE
)

# Matches reply quote lines starting with ">"
_REPLY_QUOTE_PATTERN = re.compile(r"^>.*$", flags=re.MULTILINE)

# Matches "Original Message" separator blocks
_ORIGINAL_MESSAGE_PATTERN = re.compile(
    r"-+\s*Original Message\s*-+.*", flags=re.DOTALL | re.IGNORECASE
)

# Matches common email signature separators
_SIGNATURE_PATTERN = re.compile(
    r"(_{3,}|-{3,})\s*\n.*", flags=re.DOTALL
)

# Matches inline header blocks inside forwarded emails
_INLINE_HEADER_PATTERN = re.compile(
    r"^\s*(From|To|Cc|Sent|Subject|Date)\s*:.*$",
    flags=re.MULTILINE | re.IGNORECASE
)

# Matches auto-reply and calendar invite subjects
_AUTO_REPLY_SUBJECTS = re.compile(
    r"(out of office|auto[\s-]?reply|automatic reply|"
    r"calendar|meeting request|accepted:|declined:)",
    flags=re.IGNORECASE
)


def _extract_field(raw_text: str, field: str) -> Optional[str]:
    """Extracts a single header field value from raw email text.

    Args:
        raw_text: The full raw email string including headers and body.
        field: The header field name to extract (e.g. 'From', 'Subject').

    Returns:
        The extracted field value as a string, or None if not found.
    """
    match = re.search(rf"^{field}:\s*(.+)$", raw_text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_body(raw_text: str) -> Optional[str]:
    """Extracts the email body by splitting on the first blank line.

    Email format: headers are separated from the body by a blank line.

    Args:
        raw_text: The full raw email string.

    Returns:
        The body text if found, or None if the email has no body.
    """
    # Split on the first occurrence of a blank line
    parts = re.split(r"\n\s*\n", raw_text, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


def _clean_body(raw_body: str) -> str:
    """Removes all noise from an email body string.

    Applies a sequence of regex substitutions to strip forwarded
    content, reply chains, signatures, and inline headers.

    Args:
        raw_body: The raw extracted email body string.

    Returns:
        The cleaned body string with noise removed.
    """
    text = raw_body

    # Remove forwarded message blocks first (they contain more headers)
    text = _FORWARDED_PATTERN.sub("", text)
    text = _ORIGINAL_MESSAGE_PATTERN.sub("", text)

    # Remove reply quote lines
    text = _REPLY_QUOTE_PATTERN.sub("", text)

    # Remove inline header remnants from forwarded content
    text = _INLINE_HEADER_PATTERN.sub("", text)

    # Remove signature blocks
    text = _SIGNATURE_PATTERN.sub("", text)

    # Collapse excessive blank lines into a single blank line
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _parse_date(date_string: Optional[str]) -> Optional[datetime]:
    """Attempts to parse a raw email date string into a datetime object.

    Tries multiple common email date formats before giving up.

    Args:
        date_string: The raw date string from the email header.

    Returns:
        A datetime object if parsing succeeds, or None otherwise.
    """
    if not date_string:
        return None

    # Strip timezone abbreviation in parentheses e.g. "-0700 (PDT)"
    cleaned = re.sub(r"\s*\([^)]+\)\s*$", "", date_string).strip()

    date_formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
    ]

    for fmt in date_formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    logger.warning("Could not parse date string: '{}'", date_string)
    return None


def _is_auto_reply(subject: Optional[str]) -> bool:
    """Checks whether an email subject indicates an auto-reply or calendar invite.

    Args:
        subject: The email subject string to check.

    Returns:
        True if the subject matches auto-reply patterns, False otherwise.
    """
    if not subject:
        return False
    return bool(_AUTO_REPLY_SUBJECTS.search(subject))


def _parse_raw_email(file_path: str, raw_message: str) -> Optional[RawEmail]:
    """Constructs a RawEmail object from a raw email string.

    Args:
        file_path: The original CSV file path identifier for this email.
        raw_message: The full raw email string from the CSV.

    Returns:
        A RawEmail instance if parsing succeeds, or None if the input
        is empty or unparseable.
    """
    if not raw_message or not isinstance(raw_message, str):
        return None

    return RawEmail(
        file_path=file_path,
        message_id=_extract_field(raw_message, "Message-ID"),
        date=_extract_field(raw_message, "Date"),
        sender=_extract_field(raw_message, "From"),
        receiver=_extract_field(raw_message, "To"),
        subject=_extract_field(raw_message, "Subject"),
        body=_extract_body(raw_message),
    )


def _infer_department(file_path: str) -> Optional[str]:
    """Infers the sender's department from the email folder path structure.

    Enron email paths follow the pattern: 'name/folder/subfolder/N.'
    The folder name often indicates the functional area.

    Args:
        file_path: The original CSV file path for this email.

    Returns:
        A department string if inferable, or None.
    """
    parts = file_path.split("/")
    if len(parts) >= 2:
        # Second segment is typically the mailbox folder (e.g. sent_mail, inbox)
        return parts[1].replace("_", " ").title()
    return None


def _to_clean_email(raw: RawEmail) -> Optional[CleanEmail]:
    """Converts a RawEmail into a validated CleanEmail object.

    Applies all cleaning and validation logic. Returns None if the
    email fails validation (e.g. missing body, unparseable date,
    auto-reply subject).

    Args:
        raw: The RawEmail object to clean and validate.

    Returns:
        A CleanEmail instance if validation passes, or None otherwise.
    """
    # Skip emails with no body
    if not raw.body:
        return None

    # Skip auto-replies and calendar invites
    if _is_auto_reply(raw.subject):
        return None

    cleaned_body = _clean_body(raw.body)

    # Skip emails where the body is too short after cleaning
    if len(cleaned_body.split()) < 10:
        return None

    parsed_date = _parse_date(raw.date)
    if not parsed_date:
        return None

    # Generate a fallback message ID if missing
    message_id = raw.message_id or f"generated-{uuid.uuid4()}"

    try:
        return CleanEmail(
            message_id=message_id,
            date=parsed_date,
            sender=raw.sender or "unknown@enron.com",
            receiver=raw.receiver or "unknown@enron.com",
            subject=raw.subject or "",
            body=cleaned_body,
            word_count=len(cleaned_body.split()),
            department=_infer_department(raw.file_path),
        )
    except Exception as exc:
        logger.debug("Validation failed for message_id='{}': {}", message_id, exc)
        return None


def load_and_parse_emails(
    csv_path: Optional[str] = None,
    max_emails: Optional[int] = None,
) -> list[CleanEmail]:
    """Loads the Enron CSV, parses, cleans, and validates all emails.

    This is the primary public function of this module. It orchestrates
    all parsing phases and returns a list of CleanEmail objects ready
    for the chunking pipeline.

    Args:
        csv_path: Path to the raw emails CSV file. Defaults to the
            value in settings if not provided.
        max_emails: Maximum number of emails to process. Defaults to
            settings.data.max_emails_to_ingest.

    Returns:
        A list of validated CleanEmail objects.

    Raises:
        FileNotFoundError: If the CSV file does not exist at the given path.
        ValueError: If the CSV does not contain the expected columns.
    """
    path = csv_path or settings.data.raw_data_path
    limit = max_emails or settings.data.max_emails_to_ingest

    logger.info("Loading raw emails from '{}' (limit={})", path, limit)

    try:
        # CSV has no header — assign column names explicitly
        df = pd.read_csv(
            path,
            names=["file", "message"],
            encoding="utf-8",
            on_bad_lines="skip",
            nrows=limit,
        )
    except FileNotFoundError:
        logger.error("CSV file not found at path: '{}'", path)
        raise

    if "file" not in df.columns or "message" not in df.columns:
        raise ValueError(
            f"Expected columns ['file', 'message'] in CSV, got {df.columns.tolist()}"
        )

    logger.info("Loaded {} raw rows from CSV.", len(df))

    clean_emails: list[CleanEmail] = []
    skipped = 0

    for _, row in df.iterrows():
        raw = _parse_raw_email(
            file_path=str(row["file"]),
            raw_message=str(row["message"]),
        )

        if raw is None:
            skipped += 1
            continue

        clean = _to_clean_email(raw)

        if clean is None:
            skipped += 1
            continue

        clean_emails.append(clean)

    logger.info(
        "Parsing complete | accepted={} | skipped={} | total={}",
        len(clean_emails),
        skipped,
        len(df),
    )

    return clean_emails