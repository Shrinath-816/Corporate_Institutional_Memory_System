"""
Module: ui/pages/01_query.py

Purpose:
    Primary query interface page where users ask natural language
    questions and receive grounded answers from the institutional
    memory system's specialist agents.

Responsibilities:
    - Render the chat interface via the shared chat component.
    - Wire user queries to the MasterOrchestrator's query() method.
    - Display source evidence for the most recent answer.
    - Provide category and top_k controls in the sidebar.
    - Offer quick-start example queries for first-time users.

Workflow:
    Phase 1 — Configure page and inject shared styling.
    Phase 2 — Render sidebar controls (category filter, top_k, clear chat).
    Phase 3 — Render chat history and input via ui/components/chat.py.
    Phase 4 — On query submission, call master_orchestrator.query().
    Phase 5 — Render source evidence panel for the latest answer.
"""

import streamlit as st

from orchestrators.master_orchestrator import master_orchestrator
from schemas.agent_schema import AgentOutput, QueryCategory
from ui.app import inject_global_styles, render_sidebar_brand
from ui.components.chat import (
    render_chat,
    get_chat_history,
    clear_chat_history,
    render_follow_up_chips,
)
from ui.components.source_viewer import (
    render_sources_panel,
    render_source_stats,
)


# ── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Ask · Institutional Memory",
    page_icon="💬",
    layout="wide",
)

inject_global_styles()
render_sidebar_brand()


# ── Example Queries ───────────────────────────────────────────────────────────

_EXAMPLE_QUERIES = [
    "Why did we change our vendor selection process?",
    "Who was responsible for the Q3 budget decisions?",
    "What is our current travel approval policy?",
    "What happened to the Sagewood project?",
]


# ── Sidebar Controls ──────────────────────────────────────────────────────────

def render_sidebar_controls() -> tuple[int, str]:
    """Renders sidebar controls for query configuration.

    Returns:
        A tuple of (top_k, category_filter_value) selected by the user.
    """
    with st.sidebar:
        st.markdown("##### Query settings")

        top_k = st.slider(
            "Sources to retrieve",
            min_value=3,
            max_value=15,
            value=5,
            help="Number of email chunks retrieved per query.",
        )

        category_options = ["Auto-detect", "Decision", "People", "Policy", "Project"]
        category_filter = st.selectbox(
            "Category override",
            options=category_options,
            help="Skip automatic classification and force a category.",
        )

        st.write("")

        if st.button("🗑️ Clear conversation", use_container_width=True):
            clear_chat_history()
            st.rerun()

        st.write("")
        st.markdown("---")
        st.markdown("##### Try asking")

        for example in _EXAMPLE_QUERIES:
            if st.button(
                example,
                key=f"example_{hash(example)}",
                use_container_width=True,
            ):
                st.session_state["_pending_query"] = example
                st.rerun()

        return top_k, category_filter


def _resolve_category_hint(label: str) -> QueryCategory | None:
    """Converts the sidebar category label into a QueryCategory enum.

    Args:
        label: The human-readable category label from the selectbox.

    Returns:
        A QueryCategory enum value, or None for auto-detect.
    """
    mapping = {
        "Decision": QueryCategory.DECISION,
        "People": QueryCategory.PEOPLE,
        "Policy": QueryCategory.POLICY,
        "Project": QueryCategory.PROJECT,
    }
    return mapping.get(label)


# ── Query Handler ─────────────────────────────────────────────────────────────

def handle_query(query_text: str, top_k: int, category_hint) -> AgentOutput:
    """Executes a user query against the Master Orchestrator.

    Args:
        query_text: The user's natural language question.
        top_k: Number of source documents to retrieve.
        category_hint: Optional QueryCategory to bypass router classification.

    Returns:
        The AgentOutput returned by the retrieval pipeline.

    Raises:
        RuntimeError: If the orchestrator fails to process the query.
    """
    return master_orchestrator.query(
        query_text=query_text,
        top_k=top_k,
        category_hint=category_hint,
    )


def handle_follow_up_click(question: str) -> None:
    """Stores a clicked follow-up question for submission on rerun.

    Args:
        question: The follow-up question text that was clicked.
    """
    st.session_state["_pending_query"] = question


# ── Page Header ───────────────────────────────────────────────────────────────

def render_page_header() -> None:
    """Renders the page title and description above the chat interface."""
    st.markdown(
        """
        <div class="hero-eyebrow">Ask</div>
        <div class="hero-title" style="font-size:28px;">
            Query institutional memory
        </div>
        <div class="hero-subtitle" style="font-size:14.5px;">
            Ask about decisions, people, policies, or projects. Every answer
            is grounded in retrieved evidence — check the sources below
            each response to verify.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


# ── Main Render ───────────────────────────────────────────────────────────────

def main() -> None:
    """Renders the complete query page: header, chat, and source evidence."""
    top_k, category_label = render_sidebar_controls()
    category_hint = _resolve_category_hint(category_label)

    render_page_header()

    left_col, right_col = st.columns([2.3, 1], gap="large")

    with left_col:
        st.markdown('<div class="glass-card" style="padding:20px 24px;">', unsafe_allow_html=True)

        # Handle a pending query triggered by example/follow-up buttons
        pending_query = st.session_state.pop("_pending_query", None)
        if pending_query:
            from ui.components.chat import _append_message

            _append_message("user", pending_query)
            with st.spinner("Searching institutional memory..."):
                try:
                    output = handle_query(pending_query, top_k, category_hint)
                    _append_message("assistant", output.answer, agent_output=output)
                except Exception as exc:
                    _append_message(
                        "assistant",
                        f"Something went wrong while processing your query: {exc}",
                    )

        render_chat(
            on_submit=lambda q: handle_query(q, top_k, category_hint),
            placeholder="Ask about a decision, person, policy, or project...",
        )

        render_follow_up_chips(on_click=handle_follow_up_click)

        st.markdown("</div>", unsafe_allow_html=True)

    with right_col:
        st.markdown("##### Evidence")
        st.write("")

        history = get_chat_history()
        last_assistant_msg = next(
            (m for m in reversed(history) if m["role"] == "assistant"),
            None,
        )

        if last_assistant_msg and last_assistant_msg.get("agent_output"):
            output: AgentOutput = last_assistant_msg["agent_output"]

            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            render_source_stats(output.sources)
            st.markdown("</div>", unsafe_allow_html=True)

            st.write("")
            render_sources_panel(output.sources)
        else:
            st.markdown(
                """
                <div class="glass-card" style="text-align:center; padding:40px 20px; color:#6F6796;">
                    <div style="font-size:24px; margin-bottom:8px;">📎</div>
                    <div style="font-size:13px;">
                        Source evidence for your latest answer will appear here.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


if __name__ == "__main__":
    main()