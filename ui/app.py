"""
Module: ui/app.py

Purpose:
    Main entry point for the Institutional Memory System's Streamlit
    interface. Establishes the global visual identity (navy enterprise
    theme), page configuration, and the home dashboard.

Responsibilities:
    - Configure Streamlit page settings (title, icon, layout).
    - Inject the global design system as CSS (colors, type, components).
    - Render the home dashboard: hero, system health snapshot, and
      quick-navigation cards to each functional area.
    - Provide a single source of truth for theme tokens reused by
      every page under ui/pages/.

Design System:
    Primary navy   : #3A2F69 (brand)
    Deep background: #120E28
    Surface        : #1C1740 / #221C4D (glass cards)
    Border         : rgba(255,255,255,0.08)
    Text primary   : #F3F1FA
    Text muted     : #A79FCB
    Accent         : #8B7FFF (actions, links, focus)
    Success        : #34D399   Warning: #FBBF24   Danger: #F87171
    Type           : "Inter" (UI), "JetBrains Mono" (data/code)
    Radius         : 12px cards, 10px controls
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from memory.memory_manager import memory_manager
from orchestrators.master_orchestrator import master_orchestrator


# ── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Institutional Memory System",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Global Design System (CSS) ───────────────────────────────────────────────

def inject_global_styles() -> None:
    """Injects the shared navy enterprise design system as global CSS.

    Defines CSS custom properties (design tokens) once, then applies
    them across Streamlit's native components — sidebar, buttons,
    inputs, tabs, metrics — so every page inherits a consistent look
    without repeating styles per page.
    """
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

        :root {
            --brand-navy: #3A2F69;
            --bg-deep: #120E28;
            --bg-surface: #1C1740;
            --bg-surface-2: #221C4D;
            --border-subtle: rgba(255,255,255,0.08);
            --border-hover: rgba(255,255,255,0.16);
            --text-primary: #F3F1FA;
            --text-muted: #A79FCB;
            --text-faint: #6F6796;
            --accent: #8B7FFF;
            --accent-hover: #A29BFF;
            --success: #34D399;
            --warning: #FBBF24;
            --danger: #F87171;
            --radius-lg: 14px;
            --radius-md: 12px;
            --radius-sm: 10px;
            --shadow-soft: 0 8px 30px rgba(8, 6, 20, 0.35);
            --shadow-lift: 0 14px 40px rgba(8, 6, 20, 0.45);
        }

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        code, pre, .mono {
            font-family: 'JetBrains Mono', monospace !important;
        }

        /* ── App background ─────────────────────────────────────────── */
        .stApp {
            background:
                radial-gradient(circle at 15% 0%, rgba(139,127,255,0.10), transparent 45%),
                radial-gradient(circle at 85% 15%, rgba(58,47,105,0.35), transparent 50%),
                var(--bg-deep);
            color: var(--text-primary);
        }

        /* ── Sidebar ─────────────────────────────────────────────────── */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #171233 0%, #120E28 100%);
            border-right: 1px solid var(--border-subtle);
        }
        section[data-testid="stSidebar"] * {
            color: var(--text-primary) !important;
        }
        section[data-testid="stSidebar"] .stMarkdown p {
            color: var(--text-muted) !important;
        }

        /* ── Headings ────────────────────────────────────────────────── */
        h1, h2, h3, h4 {
            color: var(--text-primary) !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
        }
        p, span, label, li {
            color: var(--text-muted);
        }

        /* ── Glass cards ─────────────────────────────────────────────── */
        .glass-card {
            background: linear-gradient(180deg, var(--bg-surface-2) 0%, var(--bg-surface) 100%);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-lg);
            padding: 28px 26px;
            box-shadow: var(--shadow-soft);
            backdrop-filter: blur(20px);
            transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
        }
        .glass-card:hover {
            transform: translateY(-3px);
            box-shadow: var(--shadow-lift);
            border-color: var(--border-hover);
        }

        /* ── Hero ────────────────────────────────────────────────────── */
        .hero-eyebrow {
            display: inline-block;
            font-size: 12.5px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--accent);
            background: rgba(139,127,255,0.12);
            border: 1px solid rgba(139,127,255,0.25);
            padding: 5px 12px;
            border-radius: 999px;
            margin-bottom: 18px;
        }
        .hero-title {
            font-size: 40px;
            font-weight: 800;
            line-height: 1.15;
            letter-spacing: -0.03em;
            color: var(--text-primary);
            margin-bottom: 12px;
        }
        .hero-subtitle {
            font-size: 16px;
            color: var(--text-muted);
            max-width: 640px;
            line-height: 1.6;
        }

        /* ── Status pill ─────────────────────────────────────────────── */
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            font-size: 13px;
            font-weight: 500;
            padding: 6px 12px;
            border-radius: 999px;
            border: 1px solid var(--border-subtle);
            background: rgba(255,255,255,0.03);
        }
        .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
        .dot-healthy { background: var(--success); box-shadow: 0 0 8px var(--success); }
        .dot-degraded { background: var(--warning); box-shadow: 0 0 8px var(--warning); }
        .dot-down { background: var(--danger); box-shadow: 0 0 8px var(--danger); }

        /* ── Nav cards ───────────────────────────────────────────────── */
        .nav-card-icon {
            font-size: 26px;
            margin-bottom: 14px;
            opacity: 0.9;
        }
        .nav-card-title {
            font-size: 17px;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 6px;
        }
        .nav-card-desc {
            font-size: 13.5px;
            color: var(--text-muted);
            line-height: 1.5;
        }

        /* ── Metric-style stat ───────────────────────────────────────── */
        .stat-value {
            font-size: 30px;
            font-weight: 800;
            color: var(--text-primary);
            letter-spacing: -0.02em;
        }
        .stat-label {
            font-size: 12.5px;
            color: var(--text-faint);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 600;
            margin-top: 4px;
        }

        /* ── Buttons ─────────────────────────────────────────────────── */
        .stButton > button {
            background: linear-gradient(180deg, var(--accent) 0%, #7367F0 100%);
            color: #FFFFFF;
            border: none;
            border-radius: var(--radius-sm);
            padding: 0.55rem 1.2rem;
            font-weight: 600;
            font-size: 14px;
            box-shadow: 0 4px 16px rgba(139,127,255,0.30);
            transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 22px rgba(139,127,255,0.42);
            filter: brightness(1.06);
        }
        .stButton > button:active { transform: translateY(0px); }

        /* ── Inputs ──────────────────────────────────────────────────── */
        .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
            background: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: var(--radius-sm) !important;
            color: var(--text-primary) !important;
        }
        .stTextInput input:focus, .stTextArea textarea:focus {
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px rgba(139,127,255,0.18) !important;
        }

        /* ── Tabs ────────────────────────────────────────────────────── */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            border-bottom: 1px solid var(--border-subtle);
        }
        .stTabs [data-baseweb="tab"] {
            color: var(--text-muted);
            font-weight: 500;
            border-radius: var(--radius-sm) var(--radius-sm) 0 0;
        }
        .stTabs [aria-selected="true"] {
            color: var(--text-primary) !important;
            border-bottom: 2px solid var(--accent) !important;
        }

        /* ── Divider ─────────────────────────────────────────────────── */
        hr { border-color: var(--border-subtle) !important; }

        /* ── Scrollbar ───────────────────────────────────────────────── */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb {
            background: var(--bg-surface-2);
            border-radius: 8px;
        }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent); }

        /* ── Accessibility: visible focus ring ──────────────────────── */
        *:focus-visible {
            outline: 2px solid var(--accent) !important;
            outline-offset: 2px;
        }

        /* ── Reduced motion respect ─────────────────────────────────── */
        @media (prefers-reduced-motion: reduce) {
            * { transition: none !important; animation: none !important; }
        }

        #MainMenu, footer, header { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Sidebar Brand Header ──────────────────────────────────────────────────────

def render_sidebar_brand() -> None:
    """Renders the sidebar brand header shown above the page navigation."""
    with st.sidebar:
        st.markdown(
            """
            <div style="display:flex; align-items:center; gap:10px; padding:6px 0 18px 0;">
                <div style="
                    width:36px; height:36px; border-radius:10px;
                    background: linear-gradient(135deg, #8B7FFF, #3A2F69);
                    display:flex; align-items:center; justify-content:center;
                    font-size:18px; box-shadow: 0 4px 14px rgba(139,127,255,0.35);
                ">🧠</div>
                <div>
                    <div style="font-weight:700; font-size:15px; color:#F3F1FA; line-height:1.2;">
                        Institutional Memory
                    </div>
                    <div style="font-size:11.5px; color:#6F6796; letter-spacing:0.03em;">
                        ENTERPRISE · BETA
                    </div>
                </div>
            </div>
            <div style="border-bottom:1px solid rgba(255,255,255,0.08); margin-bottom:16px;"></div>
            """,
            unsafe_allow_html=True,
        )


# ── Health Snapshot ───────────────────────────────────────────────────────────

def get_health_snapshot() -> dict:
    """Fetches a lightweight health snapshot for the hero status pill.

    Returns:
        Dictionary with overall status and subsystem document counts.
        Falls back to a 'down' status dict if the health check errors.
    """
    try:
        health = memory_manager.health_check()
        vector_stats = health.get("subsystems", {}).get("vector_store", {})
        graph_stats = health.get("subsystems", {}).get("graph_store", {})

        return {
            "status": health.get("status", "unknown"),
            "documents": vector_stats.get("total_documents", 0),
            "graph_status": graph_stats.get("status", "disabled"),
        }
    except Exception:
        return {"status": "down", "documents": 0, "graph_status": "disabled"}


def render_status_dot(status: str) -> str:
    """Maps a health status string to a colored dot CSS class.

    Args:
        status: The health status string ('healthy', 'degraded', etc).

    Returns:
        A CSS class name for the status dot.
    """
    if status == "healthy":
        return "dot-healthy"
    if status == "degraded":
        return "dot-degraded"
    return "dot-down"


# ── Hero Section ──────────────────────────────────────────────────────────────

def render_hero(health: dict) -> None:
    """Renders the home page hero section with live system status.

    Args:
        health: Health snapshot dictionary from get_health_snapshot().
    """
    dot_class = render_status_dot(health["status"])
    status_label = health["status"].capitalize()

    st.markdown(
        f"""
        <div class="hero-eyebrow">Corporate Institutional Memory System</div>
        <div class="hero-title">Your organisation's second brain.</div>
        <div class="hero-subtitle">
            Every decision, every relationship, every lesson learned —
            captured, connected, and instantly retrievable. Ask a question
            the way you'd ask a colleague who's been here for twenty years.
        </div>
        <div style="margin-top:22px;">
            <span class="status-pill">
                <span class="dot {dot_class}"></span>
                System {status_label} · {health['documents']:,} documents indexed
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    st.write("")


# ── Quick Navigation Cards ───────────────────────────────────────────────────

_NAV_CARDS = [
    {
        "icon": "💬",
        "title": "Ask a Question",
        "desc": "Query decisions, people, policies, and projects using natural language.",
        "page": "pages/01_query.py",
    },
    {
        "icon": "📥",
        "title": "Capture Knowledge",
        "desc": "Log meeting outcomes, project post-mortems, and expert interviews.",
        "page": "pages/02_ingest.py",
    },
    {
        "icon": "🛡️",
        "title": "Audit Memory Health",
        "desc": "Surface knowledge gaps, stale content, and single points of failure.",
        "page": "pages/03_audit.py",
    },
    {
        "icon": "🕸️",
        "title": "Explore the Graph",
        "desc": "Visualise how people, decisions, and projects connect.",
        "page": "pages/04_graph_explorer.py",
    },
]


def render_nav_cards() -> None:
    """Renders the four primary navigation cards in a responsive grid."""
    st.markdown("#### Get started")
    st.write("")

    cols = st.columns(4, gap="medium")

    for col, card in zip(cols, _NAV_CARDS):
        with col:
            st.markdown(
                f"""
                <div class="glass-card" style="min-height:180px;">
                    <div class="nav-card-icon">{card['icon']}</div>
                    <div class="nav-card-title">{card['title']}</div>
                    <div class="nav-card-desc">{card['desc']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.write("")
            if st.button("Open →", key=f"nav_{card['title']}", use_container_width=True):
                st.switch_page(card["page"])


# ── Quick Stats Row ───────────────────────────────────────────────────────────

def render_stats_row(health: dict) -> None:
    """Renders a row of key system statistics.

    Args:
        health: Health snapshot dictionary from get_health_snapshot().
    """
    st.write("")
    st.markdown("#### System snapshot")
    st.write("")

    cols = st.columns(4, gap="medium")
    stats = [
        ("Documents Indexed", f"{health['documents']:,}"),
        ("Graph Store", health["graph_status"].capitalize()),
        ("Active Agents", "9"),
        ("Audit Categories", "3"),
    ]

    for col, (label, value) in zip(cols, stats):
        with col:
            st.markdown(
                f"""
                <div class="glass-card" style="text-align:left; padding:22px 24px;">
                    <div class="stat-value">{value}</div>
                    <div class="stat-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── Main Render ───────────────────────────────────────────────────────────────

def main() -> None:
    """Renders the complete home page: styles, hero, nav cards, and stats."""
    inject_global_styles()
    render_sidebar_brand()

    health = get_health_snapshot()

    render_hero(health)
    render_nav_cards()
    render_stats_row(health)


if __name__ == "__main__":
    main()