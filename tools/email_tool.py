"""
Module: tools/email_tool.py

Purpose:
    Provides an email tool that agents can use to draft and send
    follow-up notifications — e.g. notifying a vendor of a delay,
    alerting a manager to a captured decision, or confirming an
    action item assignment extracted from a meeting.

Responsibilities:
    - Persist sent emails to a local JSON store (no external SMTP/
      Gmail/Outlook credentials are configured for this project).
    - Expose LangChain-compatible @tool functions: send_email,
      list_sent_emails, get_emails_for_recipient.
    - Validate email data via a SentEmail Pydantic model.
    - Provide an EmailStore class usable directly by agents without
      going through the LangChain tool-calling interface.

Workflow:
    Phase 1 — Agent extracts an action item requiring notification
              (e.g. "notify vendor of pipeline delay").
    Phase 2 — Agent calls send_email() to draft and record the message.
    Phase 3 — The UI or another agent can later call list_sent_emails()
              or get_emails_for_recipient() to audit what was sent.

Design Notes (why this is a local store, not a real SMTP integration):
    This project's config/settings.py does not define any SMTP host,
    port, or credentials, nor a Gmail/Outlook OAuth integration — email
    sending is out of scope for the institutional memory system's core
    purpose (capturing and retrieving knowledge, not acting as a mail
    client). Rather than skip the tool-use pattern entirely, this
    module implements a "dry-run" email tool: it validates and records
    what *would* be sent, exactly as a real SMTP tool would, so:
      - Agents (e.g. MeetingAgent, PostMortemAgent) can be extended
        later to trigger real notifications for action items with
        minimal code change — only EmailStore.send() needs to be
        swapped for a real smtplib/Gmail API call.
      - The sent-email log itself becomes part of institutional memory
        (a record of "who was told what, and when") without requiring
        the user to configure real credentials to use or test the system.
    If real sending is needed later, add SMTP_HOST/SMTP_PORT/SMTP_USER/
    SMTP_PASSWORD (or GMAIL_* OAuth fields) to config/settings.py's
    APISettings-style pattern, and replace the body of EmailStore.send()
    with an smtplib.SMTP(...).send_message(...) call — the public
    send_email() tool signature and CaptureOrchestrator/agent call sites
    do not need to change.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field, EmailStr, field_validator


# ── Storage Configuration ─────────────────────────────────────────────────────

_EMAIL_STORE_PATH = Path("./data/outbox/sent_emails.json")


# ── Sent Email Model ──────────────────────────────────────────────────────────

class SentEmail(BaseModel):
    """Represents a single email drafted/sent through the email tool.

    Attributes:
        email_id: Unique identifier for this sent email.
        to: Recipient email address.
        cc: Optional list of CC'd email addresses.
        subject: Email subject line.
        body: Email body content.
        related_message_id: Optional link back to the source email,
            meeting, or decision that triggered this notification.
        sent_at: ISO timestamp when the email was recorded as sent.
        status: Delivery status — always 'logged' in this dry-run
            implementation; would become 'sent'/'failed' with a real
            SMTP backend.
    """

    email_id: str = Field(
        default_factory=lambda: f"email_{uuid.uuid4().hex[:12]}",
        description="Unique sent-email identifier",
    )
    to: EmailStr = Field(..., description="Recipient email address")
    cc: list[EmailStr] = Field(default_factory=list, description="CC recipients")
    subject: str = Field(..., min_length=1, description="Email subject line")
    body: str = Field(..., min_length=1, description="Email body content")
    related_message_id: Optional[str] = Field(
        None, description="Source email/meeting/decision ID"
    )
    sent_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of send",
    )
    status: str = Field(default="logged", description="Delivery status")

    @field_validator("subject", "body")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        """Strips leading/trailing whitespace from text fields.

        Args:
            value: The field value to clean.

        Returns:
            The stripped string.

        Raises:
            ValueError: If the field is empty after stripping.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace-only.")
        return stripped


# ── Email Store ────────────────────────────────────────────────────────────────

class EmailStore:
    """File-backed store for SentEmail persistence and dry-run sending.

    Uses a single JSON file as the backing store, mirroring the pattern
    used by tools/calendar_tool.py's CalendarStore for consistency.

    Attributes:
        _path: Filesystem path to the JSON sent-email store.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        """Initialises the EmailStore, creating the storage file if absent.

        Args:
            path: Optional override path for the JSON store file.
                Defaults to the module-level _EMAIL_STORE_PATH.
        """
        self._path = path or _EMAIL_STORE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if not self._path.exists():
            self._write_all([])
            logger.info("Initialised new email outbox store at '{}'", self._path)

    def _read_all(self) -> list[dict]:
        """Reads all raw sent-email dictionaries from the JSON store.

        Returns:
            List of raw email dictionaries. Returns an empty list if
            the file is missing, empty, or contains invalid JSON.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning(
                "Email outbox store unreadable, treating as empty: {}", exc
            )
            return []

    def _write_all(self, emails: list[dict]) -> None:
        """Writes the complete list of email dictionaries to the JSON store.

        Args:
            emails: List of raw email dictionaries to persist.
        """
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(emails, f, indent=2, ensure_ascii=False)

    def send(self, email: SentEmail) -> SentEmail:
        """Records an email as sent (dry-run — see module docstring).

        This is the single method to replace with a real smtplib/Gmail
        API call if live email sending is added in the future; the rest
        of this class and the public @tool functions can remain unchanged.

        Args:
            email: The SentEmail to record.

        Returns:
            The same SentEmail, confirming successful logging.
        """
        emails = self._read_all()
        emails.append(email.model_dump())
        self._write_all(emails)

        logger.info(
            "Email logged (dry-run) | id='{}' | to='{}' | subject='{}'",
            email.email_id, email.to, email.subject,
        )
        return email

    def list_all(self) -> list[SentEmail]:
        """Returns all logged sent emails.

        Returns:
            List of all SentEmail objects in the store, most recent last.
        """
        return [SentEmail(**e) for e in self._read_all()]

    def get_for_recipient(self, email_address: str) -> list[SentEmail]:
        """Returns all emails sent to a specific recipient (to or cc).

        Args:
            email_address: The recipient email address to filter by.

        Returns:
            List of SentEmail objects addressed to that recipient,
            sorted by sent_at ascending.
        """
        normalised = email_address.strip().lower()
        matches = [
            e for e in self.list_all()
            if e.to.lower() == normalised
            or normalised in {c.lower() for c in e.cc}
        ]
        return sorted(matches, key=lambda e: e.sent_at)

    def get_by_related_message(self, message_id: str) -> list[SentEmail]:
        """Returns all emails triggered by a specific source message.

        Args:
            message_id: The source email/meeting/decision ID to filter by.

        Returns:
            List of SentEmail objects linked to that source message.
        """
        return [
            e for e in self.list_all()
            if e.related_message_id == message_id
        ]


# ── Module-level singleton ────────────────────────────────────────────────────

_email_store = EmailStore()


# ── LangChain Tool Wrappers ───────────────────────────────────────────────────

@tool
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    related_message_id: Optional[str] = None,
) -> str:
    """Drafts and sends a follow-up email notification.

    Use this when a captured decision, action item, or post-mortem
    recommendation requires notifying a specific person — e.g. telling
    a vendor about a delay, or confirming an action item with its owner.

    Note: in the current configuration this logs the email to the
    institutional record rather than delivering it via real SMTP, since
    no mail server credentials are configured for this system.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body content.
        cc: Optional list of CC'd email addresses.
        related_message_id: Optional ID of the source email/meeting/
            decision that triggered this notification.

    Returns:
        A confirmation string including the logged email ID.
    """
    try:
        email = SentEmail(
            to=to,
            subject=subject,
            body=body,
            cc=cc or [],
            related_message_id=related_message_id,
        )
        _email_store.send(email)
        return f"Email logged successfully with ID '{email.email_id}'."
    except Exception as exc:
        logger.error("send_email tool failed: {}", exc)
        return f"Failed to send email: {exc}"


@tool
def list_sent_emails(limit: int = 20) -> str:
    """Lists the most recently sent/logged emails.

    Args:
        limit: Maximum number of recent emails to return. Defaults to 20.

    Returns:
        A formatted string listing recent emails, or a message
        indicating none were found.
    """
    emails = _email_store.list_all()

    if not emails:
        return "No emails have been sent yet."

    recent = emails[-limit:]
    lines = [
        f"- [{e.sent_at[:10]}] To: {e.to} — '{e.subject}'"
        for e in reversed(recent)
    ]
    return f"{len(recent)} most recent email(s):\n" + "\n".join(lines)


@tool
def get_recipient_emails(email_address: str) -> str:
    """Lists all emails sent to a specific recipient.

    Args:
        email_address: The recipient's email address to look up.

    Returns:
        A formatted string listing that recipient's emails, or a
        message indicating none were found.
    """
    emails = _email_store.get_for_recipient(email_address)

    if not emails:
        return f"No emails found for recipient '{email_address}'."

    lines = [
        f"- [{e.sent_at[:10]}] '{e.subject}'"
        for e in emails
    ]
    return f"{len(emails)} email(s) for {email_address}:\n" + "\n".join(lines)


# ── Direct-access helper for non-agent callers ────────────────────────────────

def get_email_store() -> EmailStore:
    """Returns the module-level EmailStore singleton for direct use.

    Intended for use by non-LangChain callers (e.g. capture agents that
    want to send notifications without going through tool-calling).

    Returns:
        The shared EmailStore instance.
    """
    return _email_store