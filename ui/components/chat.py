"""
Module: ui/components/chat.py

Purpose:
    Reusable chat interface component providing a conversational
    question-and-answer experience over the institutional memory system.

Responsibilities:
    - Maintain chat message history in Streamlit session state.
    - Render user and assistant messages with distinct visual treatment.
    - Provide the query input control and submit handling.
    - Display agent metadata (category, confidence, agent name) per message.
    - Expose a clean render_chat() function consumed by ui/pages/01_query.py.

Workflow:
    Phase 1 — Initialise chat history in session state if absent.
    Phase 2 — Render existing message history.
    Phase 3 — Render input control and capture new query.
    Phase 4 — On submit, call the provided query handler and append result.
"""

from typing import Callable, Optional

import streamlit as st

from schemas.agent_schema import AgentOutput, QueryCategory


# ── Session State Keys ───────────────────────────────────────────────────────

_HISTORY_KEY = "chat_history"
_INPUT_KEY = "chat_input_value"


# ── Category Display Metadata ────────────────────────────────────────────────

_CATEGORY_META: dict[str, dict[str, str]] = {
    "DECISION": {"icon": "⚖️", "color": "#8B7FFF", "label": "Decision"},
    "PEOPLE": {"icon": "👤", "color": "#34D399", "label": "People"},
    "POLICY": {"icon": "📋", "color": "#FBBF24", "label": "Policy"},
    "PROJECT": {"icon": "📁", "color": "#60A5FA", "label": "Project"},
    "UNKNOWN": {"icon": "🔍", "color": "#A79FCB", "label": "General"},
}


def _get_category_meta(category: Optional[QueryCategory]) -> dict[str, str]:
    """Resolves display metadata for a query category.

    Args:
        category: The QueryCategory enum value, or None.

    Returns:
        Dictionary with icon, color, and label for display.
    """
    key = category.value if category else "UNKNOWN"
    return _CATEGORY_META.get(key, _CATEGORY_META["UNKNOWN"])


# ── Session State Initialisation ─────────────────────────────────────────────

def init_chat_state() -> None:
    """Initialises chat history in Streamlit session state if not present.

    Must be called once at the top of any page using this component,
    before render_chat_history() or render_chat_input().
    """
    if _HISTORY_KEY not in st.session_state:
        st.session_state[_HISTORY_KEY] = []


def get_chat_history() -> list[dict]:
    """Returns the current chat history from session state.

    Returns:
        List of message dictionaries with 'role', 'content', and
        optional 'agent_output' keys.
    """
    init_chat_state()
    return st.session_state[_HISTORY_KEY]


def clear_chat_history() -> None:
    """Clears all messages from the chat history."""
    st.session_state[_HISTORY_KEY] = []


def _append_message(
    role: str,
    content: str,
    agent_output: Optional[AgentOutput] = None,
) -> None:
    """Appends a single message to the chat history in session state.

    Args:
        role: 'user' or 'assistant'.
        content: The message text content.
        agent_output: Optional AgentOutput for assistant messages,
            used to render metadata badges and sources.
    """
    st.session_state[_HISTORY_KEY].append({
        "role": role,
        "content": content,
        "agent_output": agent_output,
    })


# ── Message Rendering ─────────────────────────────────────────────────────────

def _render_user_message(content: str) -> None:
    """Renders a single user message bubble, right-aligned.

    Args:
        content: The user's query text.
    """
    st.markdown(
        f"""
        <div style="display:flex; justify-content:flex-end; margin:14px 0;">
            <div style="
                max-width:72%;
                background: linear-gradient(135deg, #8B7FFF 0%, #7367F0 100%);
                color:#FFFFFF;
                padding:12px 16px;
                border-radius:14px 14px 4px 14px;
                font-size:14.5px;
                line-height:1.5;
                box-shadow: 0 4px 14px rgba(139,127,255,0.25);
            ">
                {content}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_confidence_bar(confidence: Optional[float]) -> str:
    """Builds an inline HTML confidence indicator bar.

    Args:
        confidence: Confidence score between 0.0 and 1.0, or None.

    Returns:
        HTML string for a small horizontal confidence bar.
    """
    if confidence is None:
        return ""

    pct = round(confidence * 100)

    if confidence >= 0.7:
        bar_color = "#34D399"
    elif confidence >= 0.4:
        bar_color = "#FBBF24"
    else:
        bar_color = "#F87171"

    return f"""
        <div style="display:flex; align-items:center; gap:8px; margin-top:10px;">
            <div style="flex:1; height:4px; background:rgba(255,255,255,0.08); border-radius:4px; overflow:hidden; max-width:120px;">
                <div style="width:{pct}%; height:100%; background:{bar_color}; border-radius:4px;"></div>
            </div>
            <span style="font-size:11.5px; color:#6F6796; font-weight:500;">{pct}% confidence</span>
        </div>
    """


def _render_assistant_message(
    content: str,
    agent_output: Optional[AgentOutput],
) -> None:
    """Renders a single assistant message bubble with metadata badges.

    Args:
        content: The assistant's answer text.
        agent_output: Optional AgentOutput containing category,
            confidence, agent name, and follow-up questions.
    """
    meta = _get_category_meta(
        agent_output.category if agent_output else None
    )
    confidence_html = _render_confidence_bar(
        agent_output.confidence if agent_output else None
    )
    source_count = len(agent_output.sources) if agent_output else 0
    agent_name = agent_output.agent_name if agent_output else "Assistant"

    st.markdown(
        f"""
        <div style="display:flex; justify-content:flex-start; margin:14px 0;">
            <div style="max-width:78%;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                    <span style="
                        font-size:11px; font-weight:600; padding:3px 9px;
                        border-radius:999px; letter-spacing:0.03em;
                        background:{meta['color']}22; color:{meta['color']};
                        border:1px solid {meta['color']}44;
                    ">{meta['icon']} {meta['label']}</span>
                    <span style="font-size:11.5px; color:#6F6796;">{agent_name}</span>
                </div>
                <div style="
                    background: linear-gradient(180deg, #221C4D 0%, #1C1740 100%);
                    border:1px solid rgba(255,255,255,0.08);
                    color:#F3F1FA;
                    padding:14px 18px;
                    border-radius:4px 14px 14px 14px;
                    font-size:14.5px;
                    line-height:1.65;
                    box-shadow: 0 6px 20px rgba(8,6,20,0.25);
                    white-space: pre-wrap;
                ">{content}</div>
                {confidence_html}
                <div style="font-size:11.5px; color:#6F6796; margin-top:6px;">
                    {source_count} source{'s' if source_count != 1 else ''} referenced
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chat_history() -> None:
    """Renders the complete chat history from session state.

    Iterates through all stored messages and dispatches to the
    appropriate renderer based on message role.
    """
    history = get_chat_history()

    if not history:
        st.markdown(
            """
            <div style="
                text-align:center; padding:60px 20px; color:#6F6796;
            ">
                <div style="font-size:32px; margin-bottom:10px;">💬</div>
                <div style="font-size:14.5px;">
                    Ask about a decision, a person, a policy, or a project
                    to get started.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for message in history:
        if message["role"] == "user":
            _render_user_message(message["content"])
        else:
            _render_assistant_message(
                message["content"], message.get("agent_output")
            )


# ── Input & Submission ────────────────────────────────────────────────────────

def render_chat_input(
    on_submit: Callable[[str], AgentOutput],
    placeholder: str = "Ask about a decision, person, policy, or project...",
) -> None:
    """Renders the chat input control and handles query submission.

    On submit, calls the provided handler function, appends both the
    user query and the resulting assistant message to session state,
    then triggers a rerun to display the updated history.

    Args:
        on_submit: Callback function accepting a query string and
            returning an AgentOutput. Typically wraps a call to
            master_orchestrator.query().
        placeholder: Placeholder text shown in the empty input field.
    """
    init_chat_state()

    with st.form(key="chat_input_form", clear_on_submit=True):
        cols = st.columns([6, 1])

        with cols[0]:
            query_text = st.text_input(
                label="Query",
                placeholder=placeholder,
                label_visibility="collapsed",
                key=_INPUT_KEY,
            )

        with cols[1]:
            submitted = st.form_submit_button(
                "Ask →", use_container_width=True
            )

    if submitted and query_text and query_text.strip():
        _append_message("user", query_text.strip())

        with st.spinner("Searching institutional memory..."):
            try:
                output = on_submit(query_text.strip())
                _append_message(
                    "assistant", output.answer, agent_output=output
                )
            except Exception as exc:
                _append_message(
                    "assistant",
                    f"Something went wrong while processing your query: {exc}",
                )

        st.rerun()


def render_follow_up_chips(
    on_click: Callable[[str], None],
) -> None:
    """Renders clickable follow-up question chips from the last assistant message.

    Args:
        on_click: Callback invoked with the selected follow-up question text.
    """
    history = get_chat_history()

    if not history:
        return

    last_message = history[-1]
    if last_message["role"] != "assistant":
        return

    agent_output: Optional[AgentOutput] = last_message.get("agent_output")
    if not agent_output or not agent_output.follow_up_questions:
        return

    st.markdown(
        '<div style="font-size:12px; color:#6F6796; margin:6px 0 8px 0; '
        'text-transform:uppercase; letter-spacing:0.05em; font-weight:600;">'
        'Follow-up questions</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(len(agent_output.follow_up_questions[:3]))

    for col, question in zip(cols, agent_output.follow_up_questions[:3]):
        with col:
            if st.button(
                question if len(question) <= 60 else question[:57] + "...",
                key=f"followup_{hash(question)}",
                use_container_width=True,
            ):
                on_click(question)


def render_chat(
    on_submit: Callable[[str], AgentOutput],
    placeholder: str = "Ask about a decision, person, policy, or project...",
) -> None:
    """Renders the complete chat component: history, input, and follow-ups.

    This is the primary public function of this module, composing all
    chat sub-components into a single call for use in ui/pages/01_query.py.

    Args:
        on_submit: Callback function accepting a query string and
            returning an AgentOutput.
        placeholder: Placeholder text shown in the empty input field.
    """
    init_chat_state()

    chat_container = st.container()
    with chat_container:
        render_chat_history()

    st.write("")
    render_chat_input(on_submit=on_submit, placeholder=placeholder)