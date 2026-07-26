"""
Module: ui/components/source_viewer.py

Purpose:
    Reusable component for displaying source citation cards backing
    an agent's answer — the emails, decisions, or documents that
    grounded the response.

Responsibilities:
    - Render a list of Source objects as expandable evidence cards.
    - Display sender, date, subject, excerpt, and relevance score per source.
    - Provide a compact inline variant for embedding in chat messages.
    - Provide a full detail variant for dedicated source review panels.

Workflow:
    Consumed by ui/pages/01_query.py after an AgentOutput is returned,
    to let the user verify and drill into the evidence behind an answer.
"""

from datetime import datetime
from typing import Optional

import streamlit as st

from schemas.agent_schema import Source


# ── Relevance Color Mapping ──────────────────────────────────────────────────

def _relevance_color(score: Optional[float]) -> str:
    """Maps a relevance score to a semantic color hex value.

    Args:
        score: Relevance score between 0.0 and 1.0, or None.

    Returns:
        A hex color string reflecting relevance strength.
    """
    if score is None:
        return "#6F6796"
    if score >= 0.75:
        return "#34D399"
    if score >= 0.5:
        return "#FBBF24"
    return "#F87171"


def _format_date(date_str: str) -> str:
    """Formats an ISO date string into a human-readable display date.

    Args:
        date_str: ISO 8601 date string, possibly empty.

    Returns:
        A formatted date string like 'Mar 14, 2001', or the original
        string if parsing fails.
    """
    if not date_str:
        return "Unknown date"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return date_str[:10] if len(date_str) >= 10 else date_str


def _initials_from_email(email: str) -> str:
    """Extracts display initials from an email address for an avatar badge.

    Args:
        email: The sender's email address.

    Returns:
        A 1-2 character uppercase initials string.
    """
    if not email or "@" not in email:
        return "?"
    local_part = email.split("@")[0]
    parts = local_part.replace("_", ".").split(".")
    initials = "".join(p[0] for p in parts[:2] if p)
    return initials.upper() or "?"


# ── Single Source Card ────────────────────────────────────────────────────────

def _render_source_card(source: Source, index: int) -> None:
    """Renders a single source as an expandable evidence card.

    Args:
        source: The Source object to render.
        index: The 1-based display index of this source.
    """
    color = _relevance_color(source.relevance_score)
    score_pct = (
        round(source.relevance_score * 100)
        if source.relevance_score is not None
        else None
    )
    initials = _initials_from_email(source.sender)
    formatted_date = _format_date(source.date)

    with st.expander(
        f"Source {index} · {source.sender}",
        expanded=False,
    ):
        st.markdown(
            f"""
            <div style="display:flex; gap:14px; align-items:flex-start;">
                <div style="
                    width:38px; height:38px; min-width:38px; border-radius:10px;
                    background: linear-gradient(135deg, #8B7FFF, #3A2F69);
                    display:flex; align-items:center; justify-content:center;
                    font-size:13px; font-weight:700; color:#FFFFFF;
                ">{initials}</div>

                <div style="flex:1;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                        <div>
                            <div style="font-size:14px; font-weight:600; color:#F3F1FA;">
                                {source.subject or '(No subject)'}
                            </div>
                            <div style="font-size:12.5px; color:#A79FCB; margin-top:2px;">
                                {source.sender} · {formatted_date}
                            </div>
                        </div>
                        {f'''
                        <span style="
                            font-size:11px; font-weight:600; padding:4px 10px;
                            border-radius:999px; white-space:nowrap;
                            background:{color}22; color:{color}; border:1px solid {color}44;
                        ">{score_pct}% match</span>
                        ''' if score_pct is not None else ''}
                    </div>

                    <div style="
                        margin-top:12px; padding:12px 14px;
                        background:rgba(255,255,255,0.03);
                        border-left:2px solid {color};
                        border-radius:0 8px 8px 0;
                        font-size:13.5px; line-height:1.6; color:#D8D4EE;
                        font-style:italic;
                    ">
                        "{source.excerpt}"
                    </div>

                    <div style="margin-top:10px; font-size:11px; color:#6F6796; font-family:'JetBrains Mono', monospace;">
                        ID: {source.message_id}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Full Source List (Detail Panel) ───────────────────────────────────────────

def render_sources_panel(sources: list[Source]) -> None:
    """Renders the full source list as a titled panel of expandable cards.

    Intended for use below or beside an answer, giving the user a
    complete evidence trail they can drill into individually.

    Args:
        sources: List of Source objects backing an agent's answer.
    """
    if not sources:
        st.markdown(
            """
            <div style="
                padding:18px; text-align:center; color:#6F6796;
                background:rgba(255,255,255,0.02); border-radius:12px;
                border:1px dashed rgba(255,255,255,0.08); font-size:13px;
            ">
                No sources were referenced for this answer.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div style="
            font-size:12px; font-weight:600; color:#6F6796;
            text-transform:uppercase; letter-spacing:0.05em; margin-bottom:10px;
        ">
            Evidence · {len(sources)} source{'s' if len(sources) != 1 else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i, source in enumerate(sources, start=1):
        _render_source_card(source, i)


# ── Compact Inline Variant ────────────────────────────────────────────────────

def render_sources_compact(sources: list[Source], max_visible: int = 3) -> None:
    """Renders a compact horizontal row of source chips for inline use.

    Suitable for embedding directly under a chat message without the
    vertical space cost of full expandable cards.

    Args:
        sources: List of Source objects to summarise.
        max_visible: Maximum number of source chips to display before
            collapsing the remainder into a '+N more' chip.
    """
    if not sources:
        return

    visible = sources[:max_visible]
    remaining = len(sources) - max_visible

    chips_html = ""
    for source in visible:
        color = _relevance_color(source.relevance_score)
        label = source.sender.split("@")[0][:18]
        chips_html += f"""
            <span style="
                display:inline-flex; align-items:center; gap:5px;
                font-size:11.5px; color:#D8D4EE;
                background:rgba(255,255,255,0.04);
                border:1px solid rgba(255,255,255,0.08);
                padding:4px 10px; border-radius:999px; margin-right:6px;
            ">
                <span style="width:6px; height:6px; border-radius:50%; background:{color};"></span>
                {label}
            </span>
        """

    if remaining > 0:
        chips_html += f"""
            <span style="
                font-size:11.5px; color:#6F6796;
                padding:4px 10px; border-radius:999px;
            ">+{remaining} more</span>
        """

    st.markdown(
        f'<div style="margin-top:8px; display:flex; flex-wrap:wrap; align-items:center;">{chips_html}</div>',
        unsafe_allow_html=True,
    )


# ── Source Statistics Summary ─────────────────────────────────────────────────

def render_source_stats(sources: list[Source]) -> None:
    """Renders a small summary strip of source statistics.

    Displays total sources, average relevance, and date range covered
    by the evidence — useful context for judging answer reliability.

    Args:
        sources: List of Source objects to summarise.
    """
    if not sources:
        return

    scored = [s.relevance_score for s in sources if s.relevance_score is not None]
    avg_relevance = round(sum(scored) / len(scored) * 100) if scored else None

    dates = [s.date for s in sources if s.date]
    date_range = ""
    if dates:
        sorted_dates = sorted(dates)
        earliest = _format_date(sorted_dates[0])
        latest = _format_date(sorted_dates[-1])
        date_range = f"{earliest} – {latest}" if earliest != latest else earliest

    unique_senders = len({s.sender for s in sources})

    cols = st.columns(3)
    stats = [
        ("Sources", str(len(sources))),
        ("Avg. Relevance", f"{avg_relevance}%" if avg_relevance is not None else "—"),
        ("Contributors", str(unique_senders)),
    ]

    for col, (label, value) in zip(cols, stats):
        with col:
            st.markdown(
                f"""
                <div style="text-align:center; padding:10px 0;">
                    <div style="font-size:18px; font-weight:700; color:#F3F1FA;">{value}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em; margin-top:2px;">
                        {label}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if date_range:
        st.markdown(
            f"""
            <div style="text-align:center; font-size:11.5px; color:#6F6796; margin-top:4px;">
                📅 Evidence spans {date_range}
            </div>
            """,
            unsafe_allow_html=True,
        )