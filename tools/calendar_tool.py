"""
Module: tools/calendar_tool.py

Purpose:
    Provides a lightweight calendar tool that agents can use to schedule
    and query follow-up reminders — primarily deadlines extracted from
    meeting action items and post-mortem recommendations.

Responsibilities:
    - Persist calendar events to a local JSON store (no external
      calendar API credentials are configured for this project).
    - Expose LangChain-compatible @tool functions: create_event,
      list_upcoming_events, get_events_for_person, delete_event.
    - Validate event data via a CalendarEvent Pydantic model.
    - Provide a CalendarStore class usable directly by agents without
      going through the LangChain tool-calling interface.

Workflow:
    Phase 1 — Agent extracts an action item with an owner and deadline.
    Phase 2 — Agent calls create_event() to schedule a follow-up reminder.
    Phase 3 — Any agent or the UI can later call list_upcoming_events()
              or get_events_for_person() to surface pending follow-ups.

Notes:
    This is a local, file-backed calendar — not integrated with Google
    Calendar or Outlook. It exists to demonstrate the tool-use pattern
    for agent-triggered scheduling and to make action items surfaceable
    without requiring external calendar credentials.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, Field, field_validator


# ── Storage Configuration ─────────────────────────────────────────────────────

_CALENDAR_STORE_PATH = Path("./data/calendar/events.json")


# ── Calendar Event Model ──────────────────────────────────────────────────────

class CalendarEvent(BaseModel):
    """Represents a single scheduled follow-up reminder or event.

    Attributes:
        event_id: Unique identifier for this event.
        title: Short title describing the event or action item.
        description: Additional context for the event.
        due_date: ISO date string for when this event/deadline occurs.
        owner_email: Email address of the person responsible.
        related_message_id: Optional link back to the source email,
            meeting, or post-mortem that generated this event.
        created_at: ISO timestamp when the event was created.
        completed: Whether this action item/event has been marked done.
    """

    event_id: str = Field(
        default_factory=lambda: f"event_{uuid.uuid4().hex[:12]}",
        description="Unique event identifier",
    )
    title: str = Field(..., min_length=1, description="Short event title")
    description: str = Field(default="", description="Additional event context")
    due_date: str = Field(..., description="ISO date string for the deadline")
    owner_email: str = Field(..., description="Email of the responsible person")
    related_message_id: Optional[str] = Field(
        None, description="Source email/meeting/post-mortem ID"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of event creation",
    )
    completed: bool = Field(default=False, description="Completion status")

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str) -> str:
        """Ensures due_date is a parseable ISO date string.

        Args:
            value: The due date string to validate.

        Returns:
            The validated due date string.

        Raises:
            ValueError: If the string cannot be parsed as an ISO date.
        """
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"due_date must be a valid ISO date string, got '{value}'"
            ) from exc
        return value


# ── Calendar Store ─────────────────────────────────────────────────────────────

class CalendarStore:
    """File-backed store for CalendarEvent persistence.

    Uses a single JSON file as the backing store. Suitable for the
    scale of this system (hundreds of action items, not thousands of
    events per second) and requires no external dependencies.

    Attributes:
        _path: Filesystem path to the JSON event store.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        """Initialises the CalendarStore, creating the storage file if absent.

        Args:
            path: Optional override path for the JSON store file.
                Defaults to the module-level _CALENDAR_STORE_PATH.
        """
        self._path = path or _CALENDAR_STORE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if not self._path.exists():
            self._write_all([])
            logger.info("Initialised new calendar store at '{}'", self._path)

    def _read_all(self) -> list[dict]:
        """Reads all raw event dictionaries from the JSON store.

        Returns:
            List of raw event dictionaries. Returns an empty list if
            the file is missing, empty, or contains invalid JSON.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning(
                "Calendar store unreadable, treating as empty: {}", exc
            )
            return []

    def _write_all(self, events: list[dict]) -> None:
        """Writes the complete list of event dictionaries to the JSON store.

        Args:
            events: List of raw event dictionaries to persist.
        """
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, ensure_ascii=False)

    def add(self, event: CalendarEvent) -> CalendarEvent:
        """Persists a new CalendarEvent to the store.

        Args:
            event: The CalendarEvent to add.

        Returns:
            The same CalendarEvent, confirming successful storage.
        """
        events = self._read_all()
        events.append(event.model_dump())
        self._write_all(events)

        logger.info(
            "Calendar event created | id='{}' | title='{}' | due='{}'",
            event.event_id, event.title, event.due_date,
        )
        return event

    def list_all(self) -> list[CalendarEvent]:
        """Returns all stored calendar events.

        Returns:
            List of all CalendarEvent objects in the store.
        """
        return [CalendarEvent(**e) for e in self._read_all()]

    def list_upcoming(self, days_ahead: int = 30) -> list[CalendarEvent]:
        """Returns incomplete events due within the given number of days.

        Args:
            days_ahead: Only include events due within this many days
                from now. Defaults to 30.

        Returns:
            List of upcoming, incomplete CalendarEvent objects sorted
            by due date ascending.
        """
        now = datetime.now(timezone.utc)
        upcoming: list[CalendarEvent] = []

        for event in self.list_all():
            if event.completed:
                continue
            try:
                due = datetime.fromisoformat(event.due_date)
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            days_until = (due - now).days
            if -1 <= days_until <= days_ahead:
                upcoming.append(event)

        return sorted(upcoming, key=lambda e: e.due_date)

    def get_for_person(self, email: str) -> list[CalendarEvent]:
        """Returns all events owned by a specific person.

        Args:
            email: The owner's email address to filter by.

        Returns:
            List of CalendarEvent objects owned by that person,
            sorted by due date ascending.
        """
        normalised = email.strip().lower()
        matches = [
            e for e in self.list_all()
            if e.owner_email.strip().lower() == normalised
        ]
        return sorted(matches, key=lambda e: e.due_date)

    def mark_completed(self, event_id: str) -> bool:
        """Marks a specific event as completed.

        Args:
            event_id: The unique ID of the event to mark complete.

        Returns:
            True if the event was found and updated, False otherwise.
        """
        events = self._read_all()
        found = False

        for event_dict in events:
            if event_dict.get("event_id") == event_id:
                event_dict["completed"] = True
                found = True
                break

        if found:
            self._write_all(events)
            logger.info("Calendar event marked completed | id='{}'", event_id)

        return found

    def delete(self, event_id: str) -> bool:
        """Deletes a specific event from the store.

        Args:
            event_id: The unique ID of the event to delete.

        Returns:
            True if the event was found and removed, False otherwise.
        """
        events = self._read_all()
        filtered = [e for e in events if e.get("event_id") != event_id]

        if len(filtered) == len(events):
            return False

        self._write_all(filtered)
        logger.info("Calendar event deleted | id='{}'", event_id)
        return True


# ── Module-level singleton ────────────────────────────────────────────────────

_calendar_store = CalendarStore()


# ── LangChain Tool Wrappers ───────────────────────────────────────────────────

@tool
def create_calendar_event(
    title: str,
    due_date: str,
    owner_email: str,
    description: str = "",
    related_message_id: Optional[str] = None,
) -> str:
    """Creates a calendar reminder for a follow-up action item or deadline.

    Use this when a meeting, decision, or post-mortem produces an action
    item with a clear owner and deadline that should be tracked.

    Args:
        title: Short title describing the action item.
        due_date: ISO date string (YYYY-MM-DD) for the deadline.
        owner_email: Email address of the person responsible.
        description: Optional additional context for the reminder.
        related_message_id: Optional ID of the source email/meeting.

    Returns:
        A confirmation string including the created event ID.
    """
    try:
        event = CalendarEvent(
            title=title,
            due_date=due_date,
            owner_email=owner_email,
            description=description,
            related_message_id=related_message_id,
        )
        _calendar_store.add(event)
        return f"Event created successfully with ID '{event.event_id}'."
    except Exception as exc:
        logger.error("create_calendar_event tool failed: {}", exc)
        return f"Failed to create event: {exc}"


@tool
def list_upcoming_events(days_ahead: int = 30) -> str:
    """Lists all incomplete calendar events due within the given time window.

    Use this to check what action items and deadlines are coming up
    across the organisation.

    Args:
        days_ahead: Number of days ahead to look for upcoming events.
            Defaults to 30.

    Returns:
        A formatted string listing upcoming events, or a message
        indicating none were found.
    """
    events = _calendar_store.list_upcoming(days_ahead=days_ahead)

    if not events:
        return f"No upcoming events found in the next {days_ahead} days."

    lines = [
        f"- [{e.due_date[:10]}] {e.title} (owner: {e.owner_email})"
        for e in events
    ]
    return f"{len(events)} upcoming event(s):\n" + "\n".join(lines)


@tool
def get_person_events(owner_email: str) -> str:
    """Lists all calendar events owned by a specific person.

    Args:
        owner_email: The email address of the person to look up.

    Returns:
        A formatted string listing that person's events, or a message
        indicating none were found.
    """
    events = _calendar_store.get_for_person(owner_email)

    if not events:
        return f"No calendar events found for '{owner_email}'."

    lines = [
        f"- [{e.due_date[:10]}] {e.title} "
        f"{'(completed)' if e.completed else '(pending)'}"
        for e in events
    ]
    return f"{len(events)} event(s) for {owner_email}:\n" + "\n".join(lines)


@tool
def mark_event_completed(event_id: str) -> str:
    """Marks a calendar event as completed.

    Args:
        event_id: The unique ID of the event to mark complete.

    Returns:
        A confirmation string, or an error message if not found.
    """
    success = _calendar_store.mark_completed(event_id)
    if success:
        return f"Event '{event_id}' marked as completed."
    return f"Event '{event_id}' not found."


# ── Direct-access helper for non-agent callers ────────────────────────────────

def get_calendar_store() -> CalendarStore:
    """Returns the module-level CalendarStore singleton for direct use.

    Intended for use by non-LangChain callers (e.g. capture agents that
    want to schedule reminders without going through tool-calling).

    Returns:
        The shared CalendarStore instance.
    """
    return _calendar_store