"""
Module: ui/pages/03_audit.py

Purpose:
    Audit dashboard page providing a visual health overview of the
    institutional memory system — knowledge gaps, stale content, and
    single points of failure.

Responsibilities:
    - Trigger full or scoped audit scans via the MasterOrchestrator.
    - Render overall health status with a prominent indicator.
    - Display findings grouped by severity in a scannable card layout.
    - Render the LLM-generated executive summary.
    - Provide filtering by finding category (gaps/staleness/SPF).

Workflow:
    Phase 1 — Configure page and inject shared styling.
    Phase 2 — Render sidebar scan controls (scope selector, run button).
    Phase 3 — On run, call master_orchestrator.run_audit() and cache result.
    Phase 4 — Render health banner, executive summary, and finding cards.
"""

from typing import Optional

import streamlit as st

from orchestrators.master_orchestrator import master_orchestrator
from orchestrators.audit_orchestrator import AuditReport, AuditScope, AuditFinding
from ui.app import inject_global_styles, render_sidebar_brand


# ── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Audit · Institutional Memory",
    page_icon="🛡️",
    layout="wide",
)

inject_global_styles()
render_sidebar_brand()


# ── Session State Keys ───────────────────────────────────────────────────────

_REPORT_KEY = "audit_report"


# ── Health Status Meta ────────────────────────────────────────────────────────

_HEALTH_META = {
    "HEALTHY": {"color": "#34D399", "icon": "✓", "label": "Healthy"},
    "DEGRADED": {"color": "#FBBF24", "icon": "⚠", "label": "Degraded"},
    "CRITICAL": {"color": "#F87171", "icon": "✕", "label": "Critical"},
    "UNKNOWN": {"color": "#6F6796", "icon": "?", "label": "Unknown"},
}

_SEVERITY_META = {
    "CRITICAL": {"color": "#F87171", "icon": "🔴"},
    "HIGH": {"color": "#FB923C", "icon": "🟠"},
    "MEDIUM": {"color": "#FBBF24", "icon": "🟡"},
    "LOW": {"color": "#6F6796", "icon": "⚪"},
}

_CATEGORY_META = {
    "GAP": {"icon": "🕳️", "label": "Knowledge Gap"},
    "STALENESS": {"icon": "⏳", "label": "Stale Content"},
    "SINGLE_POINT_OF_FAILURE": {"icon": "⚡", "label": "Single Point of Failure"},
}


# ── Sidebar Controls ──────────────────────────────────────────────────────────

def render_sidebar_controls() -> tuple[AuditScope, bool]:
    """Renders sidebar controls for configuring and triggering an audit scan.

    Returns:
        A tuple of (selected AuditScope, whether run was clicked).
    """
    with st.sidebar:
        st.markdown("##### Scan configuration")

        scope_options = {
            "Full audit": AuditScope.FULL,
            "Knowledge gaps only": AuditScope.GAPS_ONLY,
            "Staleness only": AuditScope.STALENESS_ONLY,
            "Single points of failure only": AuditScope.SPF_ONLY,
            "Quick scan": AuditScope.QUICK,
        }

        scope_label = st.selectbox("Scope", options=list(scope_options.keys()))
        scope = scope_options[scope_label]

        generate_summary = st.checkbox(
            "Generate executive summary", value=True,
            help="Uses the LLM to summarise findings. Adds a few seconds.",
        )
        st.session_state["_audit_generate_summary"] = generate_summary

        st.write("")
        run_clicked = st.button(
            "🛡️ Run audit scan", type="primary", use_container_width=True
        )

        if _REPORT_KEY in st.session_state:
            st.write("")
            st.markdown("---")
            report: AuditReport = st.session_state[_REPORT_KEY]
            st.caption(f"Last scan: {report.scanned_at.strftime('%b %d, %Y %H:%M UTC')}")

        return scope, run_clicked


# ── Page Header ───────────────────────────────────────────────────────────────

def render_page_header() -> None:
    """Renders the page title and description above the audit dashboard."""
    st.markdown(
        """
        <div class="hero-eyebrow">Audit</div>
        <div class="hero-title" style="font-size:28px;">
            Institutional memory health
        </div>
        <div class="hero-subtitle" style="font-size:14.5px;">
            Surface what's missing, what's outdated, and who your
            organisation can't afford to lose — before it's too late.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


# ── Health Banner ─────────────────────────────────────────────────────────────

def render_health_banner(report: AuditReport) -> None:
    """Renders the prominent overall health status banner.

    Args:
        report: The AuditReport containing overall_health and counts.
    """
    meta = _HEALTH_META.get(report.overall_health, _HEALTH_META["UNKNOWN"])

    st.markdown(
        f"""
        <div class="glass-card" style="
            display:flex; align-items:center; justify-content:space-between;
            border-color:{meta['color']}33; flex-wrap:wrap; gap:20px;
        ">
            <div style="display:flex; align-items:center; gap:16px;">
                <div style="
                    width:52px; height:52px; border-radius:14px;
                    background:{meta['color']}1A; border:1px solid {meta['color']}44;
                    display:flex; align-items:center; justify-content:center;
                    font-size:24px; color:{meta['color']};
                ">{meta['icon']}</div>
                <div>
                    <div style="font-size:20px; font-weight:800; color:#F3F1FA;">
                        {meta['label']}
                    </div>
                    <div style="font-size:13px; color:#A79FCB;">
                        {report.total_findings} findings across {report.scope.value.replace('_', ' ')} scan
                    </div>
                </div>
            </div>
            <div style="display:flex; gap:28px;">
                <div style="text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#F87171;">{report.critical_findings}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">Critical</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#FB923C;">{report.high_findings}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">High</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:22px; font-weight:800; color:#F3F1FA;">{report.total_findings}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">Total</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Executive Summary ─────────────────────────────────────────────────────────

def render_executive_summary(report: AuditReport) -> None:
    """Renders the LLM-generated executive summary block.

    Args:
        report: The AuditReport containing the executive_summary text.
    """
    if not report.executive_summary:
        return

    st.write("")
    st.markdown(
        f"""
        <div class="glass-card">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
                <span style="font-size:16px;">📋</span>
                <span style="font-size:13px; font-weight:700; color:#F3F1FA; text-transform:uppercase; letter-spacing:0.04em;">
                    Executive Summary
                </span>
            </div>
            <div style="font-size:14px; line-height:1.75; color:#D8D4EE; white-space:pre-wrap;">
                {report.executive_summary}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Top Actions ───────────────────────────────────────────────────────────────

def render_top_actions(report: AuditReport) -> None:
    """Renders the top recommended actions as a numbered checklist.

    Args:
        report: The AuditReport containing top_actions list.
    """
    if not report.top_actions:
        return

    st.write("")
    st.markdown("##### Recommended actions")
    st.write("")

    for i, action in enumerate(report.top_actions, start=1):
        st.markdown(
            f"""
            <div style="
                display:flex; gap:12px; align-items:flex-start;
                padding:12px 16px; background:rgba(255,255,255,0.02);
                border:1px solid rgba(255,255,255,0.06); border-radius:10px;
                margin-bottom:8px;
            ">
                <div style="
                    min-width:22px; height:22px; border-radius:6px;
                    background:rgba(139,127,255,0.15); color:#8B7FFF;
                    display:flex; align-items:center; justify-content:center;
                    font-size:11.5px; font-weight:700;
                ">{i}</div>
                <div style="font-size:13.5px; color:#D8D4EE; line-height:1.5;">{action}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Findings List ──────────────────────────────────────────────────────────────

def render_finding_card(finding: AuditFinding) -> None:
    """Renders a single audit finding as an expandable card.

    Args:
        finding: The AuditFinding to render.
    """
    sev_meta = _SEVERITY_META.get(finding.severity, _SEVERITY_META["LOW"])
    cat_meta = _CATEGORY_META.get(
        finding.category, {"icon": "•", "label": finding.category}
    )

    with st.expander(
        f"{sev_meta['icon']} {finding.affected_area} — {finding.severity}",
        expanded=False,
    ):
        st.markdown(
            f"""
            <div style="display:flex; gap:8px; margin-bottom:10px;">
                <span style="
                    font-size:11px; font-weight:600; padding:3px 10px;
                    border-radius:999px; background:{sev_meta['color']}22;
                    color:{sev_meta['color']}; border:1px solid {sev_meta['color']}44;
                ">{finding.severity}</span>
                <span style="
                    font-size:11px; font-weight:500; padding:3px 10px;
                    border-radius:999px; background:rgba(255,255,255,0.05);
                    color:#A79FCB;
                ">{cat_meta['icon']} {cat_meta['label']}</span>
                <span style="
                    font-size:11px; font-weight:500; padding:3px 10px;
                    border-radius:999px; background:rgba(255,255,255,0.03);
                    color:#6F6796;
                ">{finding.source_agent}</span>
            </div>
            <div style="font-size:13.5px; color:#D8D4EE; line-height:1.6; margin-bottom:12px;">
                {finding.description}
            </div>
            <div style="
                padding:10px 14px; background:rgba(139,127,255,0.06);
                border-left:2px solid #8B7FFF; border-radius:0 8px 8px 0;
                font-size:12.5px; color:#C4BEEF;
            ">
                <strong style="color:#8B7FFF;">Recommended:</strong> {finding.recommended_action}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_findings_section(report: AuditReport) -> None:
    """Renders the full findings list with a category filter control.

    Args:
        report: The AuditReport containing all findings.
    """
    if not report.findings:
        st.markdown(
            """
            <div class="glass-card" style="text-align:center; padding:40px; color:#6F6796;">
                <div style="font-size:28px; margin-bottom:8px;">✨</div>
                No findings detected. Institutional memory is in good shape.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.write("")
    st.markdown("##### All findings")

    filter_cols = st.columns([2, 2, 4])
    with filter_cols[0]:
        severity_filter = st.selectbox(
            "Severity",
            options=["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
            label_visibility="collapsed",
        )
    with filter_cols[1]:
        category_filter = st.selectbox(
            "Category",
            options=["All", "GAP", "STALENESS", "SINGLE_POINT_OF_FAILURE"],
            format_func=lambda x: x if x == "All" else _CATEGORY_META.get(
                x, {"label": x}
            )["label"],
            label_visibility="collapsed",
        )

    filtered = report.findings
    if severity_filter != "All":
        filtered = [f for f in filtered if f.severity == severity_filter]
    if category_filter != "All":
        filtered = [f for f in filtered if f.category == category_filter]

    st.caption(f"Showing {len(filtered)} of {len(report.findings)} findings")
    st.write("")

    for finding in filtered:
        render_finding_card(finding)


# ── Empty State ───────────────────────────────────────────────────────────────

def render_empty_state() -> None:
    """Renders the placeholder shown before any audit scan has been run."""
    st.markdown(
        """
        <div class="glass-card" style="text-align:center; padding:60px 30px; color:#6F6796;">
            <div style="font-size:36px; margin-bottom:14px;">🛡️</div>
            <div style="font-size:15px; font-weight:600; color:#A79FCB; margin-bottom:6px;">
                No audit scan run yet
            </div>
            <div style="font-size:13px;">
                Configure a scan scope in the sidebar and click
                <strong>Run audit scan</strong> to check institutional memory health.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main Render ───────────────────────────────────────────────────────────────

def main() -> None:
    """Renders the complete audit dashboard page."""
    scope, run_clicked = render_sidebar_controls()

    render_page_header()

    if run_clicked:
        generate_summary = st.session_state.get("_audit_generate_summary", True)
        with st.spinner(f"Running {scope.value.replace('_', ' ')} scan across institutional memory..."):
            try:
                from orchestrators.audit_orchestrator import AuditRequest

                request = AuditRequest(
                    scope=scope,
                    generate_summary=generate_summary,
                )
                report = master_orchestrator._audit.audit(request)
                st.session_state[_REPORT_KEY] = report
            except Exception as exc:
                st.error(f"Audit scan failed: {exc}")

    report: Optional[AuditReport] = st.session_state.get(_REPORT_KEY)

    if not report:
        render_empty_state()
        return

    render_health_banner(report)
    render_executive_summary(report)
    render_top_actions(report)
    render_findings_section(report)


if __name__ == "__main__":
    main()