"""
Module: ingestion/metadata_extractor.py

Purpose:
    Extracts rich semantic metadata from CleanEmail objects to enhance
    ChromaDB metadata and Neo4j graph node construction.

Responsibilities:
    - Extract named entities: people, organisations, locations.
    - Infer topic/category tags from email subject and body.
    - Detect whether an email contains a decision, action item,
      or project reference.
    - Extract mentioned people and their relationship to the sender.
    - Produce an ExtractedMetadata object consumed by pipeline.py
      and graph_store.py.

Workflow:
    Phase 1 — Receive a CleanEmail object.
    Phase 2 — Run keyword and pattern-based entity extraction.
    Phase 3 — Classify the email intent (decision/action/info).
    Phase 4 — Extract people mentions and action item phrases.
    Phase 5 — Return a structured ExtractedMetadata object.
"""

import re
from enum import Enum
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from schemas.email_schema import CleanEmail


# ── Email Intent Enumeration ─────────────────────────────────────────────────

class EmailIntent(str, Enum):
    """Classifies the primary intent of an email.

    Used by retrieval agents to filter emails by their functional purpose.
    """

    DECISION = "decision"
    ACTION_ITEM = "action_item"
    INFORMATION = "information"
    QUESTION = "question"
    MEETING = "meeting"
    UNKNOWN = "unknown"


# ── Extracted Metadata Model ─────────────────────────────────────────────────

class ExtractedMetadata(BaseModel):
    """Structured metadata extracted from a single CleanEmail.

    Consumed by pipeline.py to enrich ChromaDB metadata and by
    graph_store.py to build Neo4j node relationships.
    """

    message_id: str = Field(..., description="Parent email message ID")
    intent: EmailIntent = Field(
        default=EmailIntent.UNKNOWN,
        description="Classified primary intent of the email",
    )
    mentioned_people: list[str] = Field(
        default_factory=list,
        description="Email addresses or names mentioned in the body",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Extracted action item phrases from the body",
    )
    topic_tags: list[str] = Field(
        default_factory=list,
        description="Inferred topic tags based on keywords",
    )
    contains_decision: bool = Field(
        default=False,
        description="True if the email body contains a decision statement",
    )
    contains_question: bool = Field(
        default=False,
        description="True if the email body contains a direct question",
    )
    project_references: list[str] = Field(
        default_factory=list,
        description="Project names or codes detected in the email",
    )
    sentiment: Optional[str] = Field(
        default=None,
        description="Coarse sentiment: positive, negative, or neutral",
    )


# ── Compiled Regex Patterns ──────────────────────────────────────────────────

# Detects decision-making language
_DECISION_PATTERNS = re.compile(
    r"\b(decided|decision|agreed|approved|confirmed|concluded|"
    r"we will|we have decided|it was agreed|going forward|"
    r"final decision|resolution|resolved)\b",
    flags=re.IGNORECASE,
)

# Detects action item language
_ACTION_PATTERNS = re.compile(
    r"\b(please|could you|can you|need to|must|should|"
    r"action required|follow up|follow-up|send me|"
    r"let me know|get back to|review|complete|submit|"
    r"ensure|make sure|take care of)\b",
    flags=re.IGNORECASE,
)

# Detects meeting-related language
_MEETING_PATTERNS = re.compile(
    r"\b(meeting|call|conference|schedule|agenda|"
    r"discuss|presentation|briefing|sync|catch up|"
    r"dial.in|teleconference|zoom|teams)\b",
    flags=re.IGNORECASE,
)

# Detects question presence
_QUESTION_PATTERN = re.compile(r"\?")

# Detects project name references — "Project X" or "the X project"
_PROJECT_PATTERN = re.compile(
    r"\b(?:project|initiative|program|programme)\s+([A-Z][A-Za-z0-9\s\-]{1,30})",
    flags=re.IGNORECASE,
)

# Extracts email addresses mentioned inside the body text
_EMAIL_MENTION_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Detects positive sentiment keywords
_POSITIVE_SENTIMENT = re.compile(
    r"\b(great|excellent|good|thanks|thank you|appreciate|"
    r"well done|congratulations|happy|pleased|successful)\b",
    flags=re.IGNORECASE,
)

# Detects negative sentiment keywords
_NEGATIVE_SENTIMENT = re.compile(
    r"\b(problem|issue|concern|failure|failed|error|"
    r"disappointed|unfortunately|delay|overdue|risk|"
    r"escalate|urgent|critical|missed)\b",
    flags=re.IGNORECASE,
)

# Topic keyword mapping: tag → keywords to match
_TOPIC_KEYWORD_MAP: dict[str, list[str]] = {
    "finance": [
        "budget", "revenue", "cost", "expense", "payment",
        "invoice", "profit", "loss", "financial", "capital",
    ],
    "legal": [
        "contract", "agreement", "legal", "compliance", "regulation",
        "lawsuit", "liability", "clause", "terms", "attorney",
    ],
    "operations": [
        "schedule", "logistics", "operation", "process", "workflow",
        "procedure", "system", "capacity", "production", "delivery",
    ],
    "hr": [
        "salary", "employee", "hire", "resign", "performance",
        "review", "promotion", "training", "benefits", "vacation",
    ],
    "trading": [
        "trade", "market", "position", "deal", "price",
        "energy", "gas", "power", "commodity", "forward",
    ],
    "technology": [
        "system", "software", "database", "server", "network",
        "it", "infrastructure", "application", "code", "data",
    ],
    "strategy": [
        "strategy", "plan", "vision", "goal", "objective",
        "initiative", "roadmap", "growth", "expansion", "priority",
    ],
}


# ── Private Extraction Functions ─────────────────────────────────────────────

def _classify_intent(subject: str, body: str) -> EmailIntent:
    """Classifies the primary intent of an email using pattern matching.

    Checks patterns in priority order: decision → meeting → action → question.
    Falls back to INFORMATION if no strong signal is found.

    Args:
        subject: The cleaned email subject line.
        body: The cleaned email body text.

    Returns:
        An EmailIntent enum value representing the primary intent.
    """
    combined = f"{subject} {body}"

    if _DECISION_PATTERNS.search(combined):
        return EmailIntent.DECISION

    if _MEETING_PATTERNS.search(combined):
        return EmailIntent.MEETING

    if _ACTION_PATTERNS.search(combined):
        return EmailIntent.ACTION_ITEM

    if _QUESTION_PATTERN.search(combined):
        return EmailIntent.QUESTION

    return EmailIntent.INFORMATION


def _extract_action_items(body: str) -> list[str]:
    """Extracts sentences containing action item language from the body.

    Splits the body into sentences and returns those that contain
    recognised action-item keywords.

    Args:
        body: The cleaned email body text.

    Returns:
        A list of sentences identified as action items.
        Returns an empty list if none are found.
    """
    sentences = re.split(r"(?<=[.!?])\s+", body)
    action_sentences: list[str] = []

    for sentence in sentences:
        if _ACTION_PATTERNS.search(sentence):
            cleaned = sentence.strip()
            # Only include sentences of reasonable length
            if 5 < len(cleaned.split()) < 50:
                action_sentences.append(cleaned)

    return action_sentences[:5]  # Cap at 5 to avoid noise


def _extract_mentioned_people(body: str, sender: str, receiver: str) -> list[str]:
    """Extracts email addresses mentioned within the body text.

    Excludes the sender and receiver since they are already captured
    as primary metadata fields.

    Args:
        body: The cleaned email body text.
        sender: The sender's email address to exclude.
        receiver: The receiver's email address(es) to exclude.

    Returns:
        A deduplicated list of email addresses mentioned in the body.
    """
    mentioned = _EMAIL_MENTION_PATTERN.findall(body)

    # Build exclusion set from sender and receiver fields
    exclude = {
        addr.strip().lower()
        for addr in (sender + "," + receiver).split(",")
    }

    unique_mentions = list({
        addr.lower()
        for addr in mentioned
        if addr.lower() not in exclude
    })

    return unique_mentions[:10]  # Cap to avoid noise from distribution lists


def _extract_topic_tags(subject: str, body: str) -> list[str]:
    """Infers topic tags by matching keywords against the topic map.

    Args:
        subject: The cleaned email subject line.
        body: The cleaned email body text.

    Returns:
        A list of matched topic tag strings.
    """
    combined = f"{subject} {body}".lower()
    matched_tags: list[str] = []

    for tag, keywords in _TOPIC_KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword in combined:
                matched_tags.append(tag)
                break  # One match per tag is sufficient

    return matched_tags


def _extract_project_references(body: str) -> list[str]:
    """Extracts project name references from the email body.

    Looks for patterns like "Project Alpha" or "the Sagewood initiative".

    Args:
        body: The cleaned email body text.

    Returns:
        A deduplicated list of project name strings found in the body.
    """
    matches = _PROJECT_PATTERN.findall(body)
    return list({match.strip().title() for match in matches})


def _infer_sentiment(body: str) -> str:
    """Infers a coarse sentiment label from the email body.

    Uses keyword matching rather than an ML model for speed and
    simplicity. Sufficient for metadata tagging purposes.

    Args:
        body: The cleaned email body text.

    Returns:
        One of: 'positive', 'negative', or 'neutral'.
    """
    positive_hits = len(_POSITIVE_SENTIMENT.findall(body))
    negative_hits = len(_NEGATIVE_SENTIMENT.findall(body))

    if positive_hits > negative_hits:
        return "positive"
    if negative_hits > positive_hits:
        return "negative"
    return "neutral"


# ── Public API ───────────────────────────────────────────────────────────────

def extract_metadata(email: CleanEmail) -> ExtractedMetadata:
    """Extracts all semantic metadata from a single CleanEmail object.

    This is the primary public function of this module. Orchestrates
    all extraction functions and returns a populated ExtractedMetadata
    object for downstream use by pipeline.py and graph_store.py.

    Args:
        email: A validated CleanEmail object to extract metadata from.

    Returns:
        A fully populated ExtractedMetadata instance.
    """
    logger.debug(
        "Extracting metadata for message_id='{}'", email.message_id
    )

    intent = _classify_intent(email.subject, email.body)
    action_items = _extract_action_items(email.body)
    mentioned_people = _extract_mentioned_people(
        email.body, email.sender, email.receiver
    )
    topic_tags = _extract_topic_tags(email.subject, email.body)
    project_references = _extract_project_references(email.body)
    sentiment = _infer_sentiment(email.body)

    return ExtractedMetadata(
        message_id=email.message_id,
        intent=intent,
        mentioned_people=mentioned_people,
        action_items=action_items,
        topic_tags=topic_tags,
        contains_decision=intent == EmailIntent.DECISION,
        contains_question=bool(_QUESTION_PATTERN.search(email.body)),
        project_references=project_references,
        sentiment=sentiment,
    )


def extract_metadata_batch(emails: list[CleanEmail]) -> list[ExtractedMetadata]:
    """Extracts metadata for a list of CleanEmail objects.

    Args:
        emails: List of validated CleanEmail objects.

    Returns:
        A list of ExtractedMetadata objects in the same order
        as the input emails list.

    Raises:
        ValueError: If the emails list is empty.
    """
    if not emails:
        raise ValueError("No emails provided for metadata extraction.")

    logger.info(
        "Starting metadata extraction | emails={}", len(emails)
    )

    results: list[ExtractedMetadata] = []

    for email in emails:
        try:
            metadata = extract_metadata(email)
            results.append(metadata)
        except Exception as exc:
            logger.warning(
                "Metadata extraction failed for message_id='{}': {}",
                email.message_id,
                exc,
            )
            # Append a minimal fallback rather than dropping the email
            results.append(
                ExtractedMetadata(message_id=email.message_id)
            )

    logger.info(
        "Metadata extraction complete | processed={}", len(results)
    )

    return results
