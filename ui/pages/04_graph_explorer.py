"""
Module: ui/pages/04_graph_explorer.py

Purpose:
    Interactive knowledge graph explorer page allowing users to visualise
    how people, decisions, and projects connect within the institutional
    memory's Neo4j graph store.

Responsibilities:
    - Accept a search term (email or name) to centre the graph on.
    - Query Neo4j for the person node, their decisions, projects, and
      communication network.
    - Render an interactive force-directed graph using vis-network.
    - Display a fallback table view when Neo4j is unavailable.
    - Provide a node detail panel when a search resolves to a person.

Workflow:
    Phase 1 — Configure page and inject shared styling.
    Phase 2 — Render sidebar search controls.
    Phase 3 — Query GraphStore for the person's relationship subgraph.
    Phase 4 — Transform results into vis-network nodes/edges JSON.
    Phase 5 — Render the interactive graph via an HTML component.
"""

import json
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components

from memory.memory_manager import memory_manager
from ui.app import inject_global_styles, render_sidebar_brand


# ── Page Configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title="Explore · Institutional Memory",
    page_icon="🕸️",
    layout="wide",
)

inject_global_styles()
render_sidebar_brand()


# ── Node Color Scheme ─────────────────────────────────────────────────────────

_NODE_COLORS = {
    "center": {"background": "#8B7FFF", "border": "#A29BFF"},
    "person": {"background": "#3A2F69", "border": "#8B7FFF"},
    "decision": {"background": "#221C4D", "border": "#34D399"},
    "project": {"background": "#221C4D", "border": "#60A5FA"},
}


# ── Page Header ───────────────────────────────────────────────────────────────

def render_page_header() -> None:
    """Renders the page title and description above the graph explorer."""
    st.markdown(
        """
        <div class="hero-eyebrow">Explore</div>
        <div class="hero-title" style="font-size:28px;">
            Knowledge graph explorer
        </div>
        <div class="hero-subtitle" style="font-size:14.5px;">
            See how people, decisions, and projects connect. Search for
            a colleague by email to reveal their institutional footprint.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


# ── Sidebar Search Controls ───────────────────────────────────────────────────

def render_sidebar_controls() -> tuple[str, bool]:
    """Renders sidebar controls for searching the knowledge graph.

    Returns:
        A tuple of (search_email, search_clicked).
    """
    with st.sidebar:
        st.markdown("##### Search")

        email = st.text_input(
            "Person email",
            placeholder="phillip.allen@enron.com",
            help="Enter the exact email address to centre the graph on.",
        )

        st.write("")
        search_clicked = st.button(
            "🔍 Explore connections", type="primary", use_container_width=True
        )

        st.write("")
        st.markdown("---")
        st.markdown("##### Legend")
        st.markdown(
            """
            <div style="font-size:12.5px; color:#A79FCB; line-height:2.1;">
                <span style="color:#8B7FFF;">●</span> Searched person<br>
                <span style="color:#3A2F69; text-shadow:0 0 0 #8B7FFF;">●</span> Connected person<br>
                <span style="color:#34D399;">●</span> Decision<br>
                <span style="color:#60A5FA;">●</span> Project
            </div>
            """,
            unsafe_allow_html=True,
        )

        return email.strip().lower(), search_clicked


# ── Graph Data Fetching ────────────────────────────────────────────────────────

def fetch_graph_data(email: str) -> Optional[dict[str, Any]]:
    """Fetches a person's relationship subgraph from Neo4j.

    Args:
        email: The email address to centre the subgraph on.

    Returns:
        Dictionary with 'person', 'decisions', 'network', and 'projects'
        keys, or None if the graph store is unavailable or the person
        was not found.
    """
    if not memory_manager._graph_store:
        return None

    person = memory_manager.get_person(email)
    if not person:
        return None

    decisions = memory_manager.get_decisions_by_person(email)
    network = memory_manager.get_communication_network(email)

    projects: list[dict] = []
    try:
        with memory_manager._graph_store._session() as session:
            cypher = """
                MATCH (p:Person {email: $email})-[:INVOLVED_IN]->(pr:Project)
                RETURN pr
            """
            result = session.run(cypher, email=email)
            projects = [dict(record["pr"]) for record in result]
    except Exception:
        projects = []

    return {
        "person": person,
        "decisions": decisions,
        "network": network,
        "projects": projects,
    }


# ── vis-network Data Builder ──────────────────────────────────────────────────

def build_vis_network_data(graph_data: dict[str, Any], center_email: str) -> tuple[list, list]:
    """Transforms Neo4j query results into vis-network nodes and edges.

    Args:
        graph_data: Dictionary from fetch_graph_data().
        center_email: The email address of the centre node.

    Returns:
        A tuple of (nodes list, edges list) formatted for vis-network.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_node_ids: set[str] = set()

    person = graph_data["person"]
    center_id = f"person_{center_email}"

    nodes.append({
        "id": center_id,
        "label": person.get("name") or center_email.split("@")[0],
        "shape": "dot",
        "size": 26,
        "color": _NODE_COLORS["center"],
        "font": {"color": "#F3F1FA", "size": 14, "face": "Inter"},
        "title": f"{person.get('name', 'Unknown')}\n{center_email}\n{person.get('department', '')}",
    })
    seen_node_ids.add(center_id)

    # ── Decision nodes ────────────────────────────────────────────────────────
    for i, decision in enumerate(graph_data["decisions"][:12]):
        node_id = f"decision_{decision.get('node_id', i)}"
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)

        summary = decision.get("summary", "Decision")
        short_label = summary[:35] + "..." if len(summary) > 35 else summary

        nodes.append({
            "id": node_id,
            "label": short_label,
            "shape": "dot",
            "size": 16,
            "color": _NODE_COLORS["decision"],
            "font": {"color": "#D8D4EE", "size": 11, "face": "Inter"},
            "title": summary,
        })
        edges.append({
            "from": center_id,
            "to": node_id,
            "color": {"color": "#34D39955", "highlight": "#34D399"},
            "width": 1.5,
        })

    # ── Project nodes ────────────────────────────────────────────────────────
    for i, project in enumerate(graph_data["projects"][:8]):
        node_id = f"project_{project.get('node_id', i)}"
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)

        name = project.get("name", "Project")

        nodes.append({
            "id": node_id,
            "label": name,
            "shape": "dot",
            "size": 18,
            "color": _NODE_COLORS["project"],
            "font": {"color": "#D8D4EE", "size": 11, "face": "Inter"},
            "title": f"{name}\nStatus: {project.get('status', 'unknown')}",
        })
        edges.append({
            "from": center_id,
            "to": node_id,
            "color": {"color": "#60A5FA55", "highlight": "#60A5FA"},
            "width": 1.5,
        })

    # ── Connected person nodes ───────────────────────────────────────────────
    for i, contact in enumerate(graph_data["network"][:15]):
        contact_email = contact.get("email", f"unknown_{i}")
        node_id = f"person_{contact_email}"
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)

        nodes.append({
            "id": node_id,
            "label": contact.get("name") or contact_email.split("@")[0],
            "shape": "dot",
            "size": 16,
            "color": _NODE_COLORS["person"],
            "font": {"color": "#A79FCB", "size": 11, "face": "Inter"},
            "title": contact_email,
        })
        edges.append({
            "from": center_id,
            "to": node_id,
            "color": {"color": "#8B7FFF33", "highlight": "#8B7FFF"},
            "width": 1,
            "dashes": True,
        })

    return nodes, edges


# ── vis-network HTML Renderer ─────────────────────────────────────────────────

def render_network_graph(nodes: list, edges: list, height: int = 560) -> None:
    """Renders an interactive vis-network graph via an embedded HTML component.

    Args:
        nodes: List of vis-network node dictionaries.
        edges: List of vis-network edge dictionaries.
        height: Height of the graph canvas in pixels.
    """
    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)

    html = f"""
    <div id="network-container" style="
        width:100%; height:{height}px; border-radius:14px;
        background: linear-gradient(180deg, #221C4D 0%, #1C1740 100%);
        border:1px solid rgba(255,255,255,0.08);
    "></div>

    <script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
    <script>
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});

        const container = document.getElementById('network-container');
        const data = {{ nodes: nodes, edges: edges }};

        const options = {{
            physics: {{
                barnesHut: {{
                    gravitationalConstant: -3200,
                    springLength: 130,
                    springConstant: 0.04,
                }},
                stabilization: {{ iterations: 120 }},
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 120,
                zoomView: true,
                dragView: true,
            }},
            nodes: {{
                borderWidth: 2,
                shadow: {{ enabled: true, color: 'rgba(0,0,0,0.4)', size: 8 }},
            }},
            edges: {{
                smooth: {{ type: 'continuous' }},
            }},
        }};

        new vis.Network(container, data, options);
    </script>
    """

    components.html(html, height=height + 10, scrolling=False)


# ── Detail Panel ───────────────────────────────────────────────────────────────

def render_detail_panel(graph_data: dict[str, Any], email: str) -> None:
    """Renders a summary panel of the searched person's institutional footprint.

    Args:
        graph_data: Dictionary from fetch_graph_data().
        email: The searched email address.
    """
    person = graph_data["person"]

    st.markdown(
        f"""
        <div class="glass-card">
            <div style="display:flex; align-items:center; gap:14px; margin-bottom:18px;">
                <div style="
                    width:44px; height:44px; border-radius:12px;
                    background: linear-gradient(135deg, #8B7FFF, #3A2F69);
                    display:flex; align-items:center; justify-content:center;
                    font-size:16px; font-weight:700; color:#FFFFFF;
                ">{(person.get('name') or email)[:1].upper()}</div>
                <div>
                    <div style="font-size:16px; font-weight:700; color:#F3F1FA;">
                        {person.get('name') or email.split('@')[0]}
                    </div>
                    <div style="font-size:12.5px; color:#A79FCB;">
                        {person.get('role') or 'Role unknown'} · {person.get('department') or 'Unknown dept'}
                    </div>
                </div>
            </div>
            <div style="display:flex; gap:28px;">
                <div>
                    <div style="font-size:20px; font-weight:800; color:#34D399;">{len(graph_data['decisions'])}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">Decisions</div>
                </div>
                <div>
                    <div style="font-size:20px; font-weight:800; color:#60A5FA;">{len(graph_data['projects'])}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">Projects</div>
                </div>
                <div>
                    <div style="font-size:20px; font-weight:800; color:#8B7FFF;">{len(graph_data['network'])}</div>
                    <div style="font-size:10.5px; color:#6F6796; text-transform:uppercase; letter-spacing:0.05em;">Connections</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Empty / Error States ──────────────────────────────────────────────────────

def render_graph_unavailable() -> None:
    """Renders a message when Neo4j is not connected."""
    st.markdown(
        """
        <div class="glass-card" style="text-align:center; padding:60px 30px; color:#6F6796;">
            <div style="font-size:36px; margin-bottom:14px;">🔌</div>
            <div style="font-size:15px; font-weight:600; color:#A79FCB; margin-bottom:6px;">
                Graph store unavailable
            </div>
            <div style="font-size:13px;">
                Neo4j is not connected. Graph relationships cannot be
                explored until the graph database is reachable.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_person_not_found(email: str) -> None:
    """Renders a message when the searched person has no graph node.

    Args:
        email: The email address that was searched.
    """
    st.markdown(
        f"""
        <div class="glass-card" style="text-align:center; padding:60px 30px; color:#6F6796;">
            <div style="font-size:36px; margin-bottom:14px;">🔍</div>
            <div style="font-size:15px; font-weight:600; color:#A79FCB; margin-bottom:6px;">
                No graph record for '{email}'
            </div>
            <div style="font-size:13px;">
                This person may not have any captured decisions, meetings,
                or projects in the knowledge graph yet.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state() -> None:
    """Renders the placeholder shown before any search has been performed."""
    st.markdown(
        """
        <div class="glass-card" style="text-align:center; padding:60px 30px; color:#6F6796;">
            <div style="font-size:36px; margin-bottom:14px;">🕸️</div>
            <div style="font-size:15px; font-weight:600; color:#A79FCB; margin-bottom:6px;">
                Search to explore the graph
            </div>
            <div style="font-size:13px;">
                Enter a person's email address in the sidebar to visualise
                their decisions, projects, and communication network.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main Render ───────────────────────────────────────────────────────────────

def main() -> None:
    """Renders the complete graph explorer page."""
    email, search_clicked = render_sidebar_controls()

    render_page_header()

    if search_clicked and email:
        st.session_state["_graph_search_email"] = email

    search_email = st.session_state.get("_graph_search_email")

    if not search_email:
        render_empty_state()
        return

    if not memory_manager._graph_store:
        render_graph_unavailable()
        return

    with st.spinner(f"Loading graph for '{search_email}'..."):
        graph_data = fetch_graph_data(search_email)

    if not graph_data:
        render_person_not_found(search_email)
        return

    render_detail_panel(graph_data, search_email)
    st.write("")

    nodes, edges = build_vis_network_data(graph_data, search_email)
    render_network_graph(nodes, edges)

    st.caption(
        "Drag nodes to rearrange · scroll to zoom · hover for details"
    )


if __name__ == "__main__":
    main()