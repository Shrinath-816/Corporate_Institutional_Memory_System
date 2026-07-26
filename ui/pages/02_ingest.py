"""
Module: ui/pages/02_ingest.py

Purpose:
    Knowledge capture interface page where users submit meeting
    transcripts, project post-mortems, tribal knowledge interviews,
    or trigger bulk email ingestion into the institutional memory.

Responsibilities:
    - Provide tabbed forms for each capture content type.
    - Validate required fields before submission (e.g. expert profile
      for tribal knowledge).
    - Call the MasterOrchestrator's capture pipeline and display results.
    - Trigger the bulk email ingestion pipeline as a background operation.
    - Show storage confirmation (Neo4j / ChromaDB) after each capture.

Workflow:
    Phase 1 — Configure page and inject shared styling.
    Phase 2 — Render tabbed capture forms: Meeting, Post-Mortem, Tribal, Bulk.
    Phase 3 — On submit, build a CaptureRequest and call the orchestrator.
    Phase 4 — Render a result card summarising what was captured and stored.
"""

import streamlit as st

from orchestrators.master_orchestrator import (
    master_orchestrator,
    MasterRequest,
    RequestType,
)
from orchestrators.capture_orchestrator import CaptureRequest, ContentType, CaptureResult
from agents.capture.tribal_knowledge_agent import ExpertProfile
from ui.app import inject_global_styles, render_sidebar_brand


# ── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Capture · Institutional Memory",
    page_icon="📥",
    layout="wide",
)

inject_global_styles()
render_sidebar_brand()


# ── Page Header ───────────────────────────────────────────────────────────────

def render_page_header() -> None:
    """Renders the page title and description above the capture forms."""
    st.markdown(
        """
        <div class="hero-eyebrow">Capture</div>
        <div class="hero-title" style="font-size:28px;">
            Add knowledge to memory
        </div>
        <div class="hero-subtitle" style="font-size:14.5px;">
            Every meeting outcome, retrospective, and expert insight you
            log here becomes permanently searchable — and never leaves
            with the person who knew it.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


# ── Result Card ───────────────────────────────────────────────────────────────

def render_capture_result(result: CaptureResult) -> None:
    """Renders a result card summarising a completed capture operation.

    Args:
        result: The CaptureResult returned by the capture orchestrator.
    """
    if result.success:
        status_color = "#34D399"
        status_icon = "✓"
        status_label = "Captured successfully"
    else:
        status_color = "#F87171"
        status_icon = "✕"
        status_label = "Capture failed"

    st.markdown(
        f"""
        <div class="glass-card" style="border-color:{status_color}33;">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
                <div style="
                    width:32px; height:32px; border-radius:50%;
                    background:{status_color}22; border:1px solid {status_color}44;
                    display:flex; align-items:center; justify-content:center;
                    color:{status_color}; font-weight:700; font-size:15px;
                ">{status_icon}</div>
                <div style="font-weight:700; color:#F3F1FA; font-size:15px;">
                    {status_label}
                </div>
            </div>
            <div style="font-size:13.5px; color:#D8D4EE; line-height:1.6; margin-bottom:16px;">
                {result.summary}
            </div>
            <div style="display:flex; gap:24px; flex-wrap:wrap;">
                <div>
                    <div style="font-size:19px; font-weight:700; color:#F3F1FA;">{result.items_captured}</div>
                    <div style="font-size:11px; color:#6F6796; text-transform:uppercase; letter-spacing:0.04em;">Items captured</div>
                </div>
                <div>
                    <div style="font-size:19px; font-weight:700; color:{'#34D399' if result.stored_in_graph else '#6F6796'};">
                        {'✓' if result.stored_in_graph else '—'}
                    </div>
                    <div style="font-size:11px; color:#6F6796; text-transform:uppercase; letter-spacing:0.04em;">Graph memory</div>
                </div>
                <div>
                    <div style="font-size:19px; font-weight:700; color:{'#34D399' if result.stored_in_vector else '#6F6796'};">
                        {'✓' if result.stored_in_vector else '—'}
                    </div>
                    <div style="font-size:11px; color:#6F6796; text-transform:uppercase; letter-spacing:0.04em;">Vector memory</div>
                </div>
                <div>
                    <div style="font-size:13px; font-weight:600; color:#A79FCB; padding-top:4px;">{result.agent_used}</div>
                    <div style="font-size:11px; color:#6F6796; text-transform:uppercase; letter-spacing:0.04em;">Agent</div>
                </div>
            </div>
            {f'''
            <div style="margin-top:14px; padding:10px 14px; background:rgba(248,113,113,0.08);
                        border-left:2px solid #F87171; border-radius:0 8px 8px 0;
                        font-size:12.5px; color:#F87171;">
                {result.error}
            </div>
            ''' if result.error else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Meeting Tab ───────────────────────────────────────────────────────────────

def render_meeting_tab() -> None:
    """Renders the meeting transcript capture form."""
    st.markdown("###### Paste a meeting transcript or summary email")
    st.caption(
        "The agent will extract decisions, action items, owners, and "
        "deadlines automatically."
    )

    content = st.text_area(
        "Meeting content",
        height=220,
        placeholder=(
            "e.g. 'Q3 Budget Review — Attendees: Phillip Allen, Tim Belden...\n"
            "Decision: Cut marketing spend by 15% due to revenue shortfall...'"
        ),
        label_visibility="collapsed",
        key="meeting_content_input",
    )

    if st.button("📥 Capture meeting", type="primary", key="submit_meeting"):
        if not content or len(content.strip()) < 20:
            st.warning("Please paste at least a few sentences of meeting content.")
            return

        with st.spinner("Extracting decisions and action items..."):
            request = MasterRequest(
                request_type=RequestType.CAPTURE,
                capture_request=CaptureRequest(
                    content=content.strip(),
                    content_type=ContentType.MEETING_TRANSCRIPT,
                ),
            )
            response = master_orchestrator.process(request)

        if response.capture_result:
            render_capture_result(response.capture_result)
        else:
            st.error(response.error or "Capture failed with no error detail.")


# ── Post-Mortem Tab ───────────────────────────────────────────────────────────

def render_postmortem_tab() -> None:
    """Renders the project post-mortem capture form."""
    st.markdown("###### Paste a project retrospective or closure report")
    st.caption(
        "The agent will extract what worked, what failed, root causes, "
        "and lessons learned."
    )

    content = st.text_area(
        "Post-mortem content",
        height=220,
        placeholder=(
            "e.g. 'Project: Sagewood Migration — Outcome: Partial Success\n"
            "What worked: Early stakeholder buy-in accelerated approvals...\n"
            "What failed: Underestimated vendor onboarding time...'"
        ),
        label_visibility="collapsed",
        key="postmortem_content_input",
    )

    if st.button("📥 Capture post-mortem", type="primary", key="submit_postmortem"):
        if not content or len(content.strip()) < 20:
            st.warning("Please paste at least a few sentences of retrospective content.")
            return

        with st.spinner("Extracting lessons learned..."):
            request = MasterRequest(
                request_type=RequestType.CAPTURE,
                capture_request=CaptureRequest(
                    content=content.strip(),
                    content_type=ContentType.POST_MORTEM,
                ),
            )
            response = master_orchestrator.process(request)

        if response.capture_result:
            render_capture_result(response.capture_result)
        else:
            st.error(response.error or "Capture failed with no error detail.")


# ── Tribal Knowledge Tab ──────────────────────────────────────────────────────

def render_tribal_tab() -> None:
    """Renders the tribal knowledge interview capture form."""
    st.markdown("###### Capture an expert's undocumented knowledge")
    st.caption(
        "Fill in the expert's profile, then paste their interview "
        "responses. Critical insights are permanently stored in the "
        "knowledge graph."
    )

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Expert name", placeholder="Jane Doe", key="tribal_name")
        role = st.text_input("Role", placeholder="Senior Trading Manager", key="tribal_role")
    with col2:
        email = st.text_input("Email", placeholder="jane.doe@company.com", key="tribal_email")
        department = st.text_input("Department", placeholder="Trading Operations", key="tribal_dept")

    domain = st.selectbox(
        "Knowledge domain",
        options=["finance", "technology", "operations", "legal", "hr", "default"],
        format_func=lambda x: x.capitalize() if x != "default" else "General",
        key="tribal_domain",
    )

    responses = st.text_area(
        "Interview responses",
        height=180,
        placeholder=(
            "Paste the expert's answers to knowledge extraction questions here..."
        ),
        key="tribal_responses",
    )

    if st.button("📥 Capture tribal knowledge", type="primary", key="submit_tribal"):
        if not name or not email:
            st.warning("Expert name and email are required.")
            return

        if not responses or len(responses.strip()) < 20:
            st.warning("Please provide interview response content.")
            return

        profile = ExpertProfile(
            name=name,
            email=email,
            role=role,
            department=department,
            domain=domain,
        )

        with st.spinner(f"Extracting insights from {name}'s interview..."):
            request = MasterRequest(
                request_type=RequestType.CAPTURE,
                capture_request=CaptureRequest(
                    content=responses.strip(),
                    content_type=ContentType.TRIBAL_KNOWLEDGE,
                    expert_profile=profile,
                ),
            )
            response = master_orchestrator.process(request)

        if response.capture_result:
            render_capture_result(response.capture_result)
        else:
            st.error(response.error or "Capture failed with no error detail.")


# ── Bulk Ingestion Tab ────────────────────────────────────────────────────────

def render_bulk_tab() -> None:
    """Renders the bulk email ingestion trigger form."""
    st.markdown("###### Re-run the full email ingestion pipeline")
    st.caption(
        "Parses, chunks, embeds, and stores emails from the configured "
        "CSV source. This can take a minute for large datasets."
    )

    col1, col2 = st.columns(2)
    with col1:
        max_emails = st.number_input(
            "Max emails to ingest",
            min_value=10,
            max_value=50000,
            value=1000,
            step=100,
        )
    with col2:
        st.write("")
        st.write("")
        confirm = st.checkbox("I understand this may take several minutes")

    if st.button(
        "🔄 Run ingestion pipeline",
        type="primary",
        disabled=not confirm,
        key="submit_bulk",
    ):
        with st.spinner("Running full ingestion pipeline — parse → chunk → embed → store..."):
            from ingestion.pipeline import run_ingestion_pipeline

            try:
                result = run_ingestion_pipeline(max_emails=int(max_emails))

                if result.success:
                    st.success(
                        f"✓ Ingested {result.emails_clean} emails into "
                        f"{result.chunks_stored} chunks in {result.duration_seconds}s."
                    )
                else:
                    st.warning(
                        f"Pipeline completed with {len(result.errors)} error(s). "
                        f"Stored {result.chunks_stored} chunks regardless."
                    )
                    for err in result.errors:
                        st.caption(f"⚠️ {err}")

            except Exception as exc:
                st.error(f"Pipeline failed: {exc}")


# ── Main Render ───────────────────────────────────────────────────────────────

def main() -> None:
    """Renders the complete ingest page with tabbed capture forms."""
    render_page_header()

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📝 Meeting", "🔍 Post-Mortem", "🧠 Tribal Knowledge", "📦 Bulk Ingest"]
    )

    with tab1:
        st.write("")
        render_meeting_tab()

    with tab2:
        st.write("")
        render_postmortem_tab()

    with tab3:
        st.write("")
        render_tribal_tab()

    with tab4:
        st.write("")
        render_bulk_tab()


if __name__ == "__main__":
    main()