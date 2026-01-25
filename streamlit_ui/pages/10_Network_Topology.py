"""Network Topology - Visualize container network connections."""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Network Topology - Portainer Dashboard",
    page_icon="🌐",
    layout="wide",
)


def get_network_data(client, endpoint_id: int | None = None) -> list[dict]:
    """Fetch containers with their network information."""
    containers = client.get_containers(
        endpoint_id=endpoint_id,
        include_stopped=False,  # Only show running containers
    )

    containers_with_networks = []
    for c in containers:
        container_id = c.get("container_id")
        ep_id = c.get("endpoint_id")
        if not container_id or not ep_id:
            continue

        # Fetch detailed info for each container
        details = client.get_container_details(ep_id, container_id)
        if details:
            networks = details.get("networks") or {}
            containers_with_networks.append({
                "endpoint_id": ep_id,
                "endpoint_name": c.get("endpoint_name"),
                "container_id": container_id,
                "container_name": c.get("container_name"),
                "state": c.get("state"),
                "image": c.get("image"),
                "networks": networks,
            })

    return containers_with_networks


def build_network_graph(containers_with_networks: list[dict], selected_network: str | None = None) -> go.Figure:
    """Build a network graph visualization using Plotly."""
    # Collect all networks and containers
    networks = set()
    for c in containers_with_networks:
        for net_name in c.get("networks", {}).keys():
            networks.add(net_name)

    # Filter by selected network if specified
    if selected_network and selected_network != "All Networks":
        networks = {selected_network}
        containers_with_networks = [
            c for c in containers_with_networks
            if selected_network in c.get("networks", {})
        ]

    if not networks or not containers_with_networks:
        return None

    # Position calculation using a simple circular layout
    # Networks in inner circle, containers in outer circle
    network_list = sorted(list(networks))
    num_networks = len(network_list)
    num_containers = len(containers_with_networks)

    # Calculate positions for networks (inner circle)
    network_positions = {}
    inner_radius = 1.0
    for i, net in enumerate(network_list):
        angle = (2 * math.pi * i) / max(num_networks, 1)
        network_positions[net] = (inner_radius * math.cos(angle), inner_radius * math.sin(angle))

    # Calculate positions for containers (outer circle)
    container_positions = {}
    outer_radius = 2.5
    for i, c in enumerate(containers_with_networks):
        angle = (2 * math.pi * i) / max(num_containers, 1)
        container_positions[c["container_id"]] = (
            outer_radius * math.cos(angle),
            outer_radius * math.sin(angle)
        )

    # Create edge traces
    edge_x = []
    edge_y = []
    edge_info = []

    for c in containers_with_networks:
        container_id = c["container_id"]
        cx, cy = container_positions[container_id]
        for net_name, net_info in c.get("networks", {}).items():
            if selected_network and selected_network != "All Networks" and net_name != selected_network:
                continue
            if net_name in network_positions:
                nx, ny = network_positions[net_name]
                edge_x.extend([cx, nx, None])
                edge_y.extend([cy, ny, None])
                ip = net_info.get("IPAddress", "N/A") if isinstance(net_info, dict) else "N/A"
                edge_info.append(f"{c['container_name']} -> {net_name} ({ip})")

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=1, color="#888"),
        hoverinfo="none",
    )

    # Create network node trace
    network_x = [pos[0] for pos in network_positions.values()]
    network_y = [pos[1] for pos in network_positions.values()]
    network_text = list(network_positions.keys())

    network_trace = go.Scatter(
        x=network_x,
        y=network_y,
        mode="markers+text",
        marker=dict(
            size=30,
            color="#3B82F6",
            symbol="diamond",
            line=dict(width=2, color="#1E40AF"),
        ),
        text=network_text,
        textposition="bottom center",
        hoverinfo="text",
        hovertext=[f"Network: {n}" for n in network_text],
        name="Networks",
    )

    # Create container node traces (colored by state)
    container_x = []
    container_y = []
    container_text = []
    container_hover = []
    container_colors = []

    state_colors = {
        "running": "#10B981",
        "exited": "#6B7280",
        "paused": "#F59E0B",
        "restarting": "#3B82F6",
    }

    for c in containers_with_networks:
        container_id = c["container_id"]
        x, y = container_positions[container_id]
        container_x.append(x)
        container_y.append(y)
        container_text.append(c["container_name"][:15])  # Truncate long names

        # Build hover info
        networks_info = []
        for net_name, net_info in c.get("networks", {}).items():
            ip = net_info.get("IPAddress", "N/A") if isinstance(net_info, dict) else "N/A"
            networks_info.append(f"{net_name}: {ip}")

        hover = f"<b>{c['container_name']}</b><br>"
        hover += f"Endpoint: {c.get('endpoint_name', 'N/A')}<br>"
        hover += f"State: {c.get('state', 'N/A')}<br>"
        hover += f"Image: {c.get('image', 'N/A')}<br>"
        hover += "<b>Networks:</b><br>" + "<br>".join(networks_info) if networks_info else "No networks"
        container_hover.append(hover)

        state = c.get("state", "unknown")
        container_colors.append(state_colors.get(state, "#9CA3AF"))

    container_trace = go.Scatter(
        x=container_x,
        y=container_y,
        mode="markers+text",
        marker=dict(
            size=20,
            color=container_colors,
            line=dict(width=1, color="#374151"),
        ),
        text=container_text,
        textposition="top center",
        textfont=dict(size=10),
        hoverinfo="text",
        hovertext=container_hover,
        name="Containers",
    )

    # Create figure
    fig = go.Figure(
        data=[edge_trace, network_trace, container_trace],
        layout=go.Layout(
            showlegend=True,
            hovermode="closest",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            margin=dict(t=20, b=20, l=20, r=20),
            height=600,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5,
            ),
        ),
    )

    return fig


def main():
    """Network topology page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("🌐 Network Topology")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_network"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("Visualize container network connections across your infrastructure")

    client = get_api_client()

    # Fetch endpoints for filter
    endpoints = client.get_endpoints()

    if not endpoints:
        st.warning("No endpoints found")
        st.stop()

    # Filters
    col1, col2 = st.columns(2)

    with col1:
        endpoint_options = {"All Endpoints": None}
        for ep in endpoints:
            label = f"{ep.get('endpoint_name', 'Unknown')} (ID: {ep.get('endpoint_id')})"
            endpoint_options[label] = ep.get("endpoint_id")

        selected_endpoint_label = st.selectbox(
            "Filter by Endpoint",
            options=list(endpoint_options.keys()),
            key="network_endpoint_filter",
        )
        selected_endpoint_id = endpoint_options.get(selected_endpoint_label)

    # Fetch container network data
    with st.spinner("Loading network data..."):
        containers_with_networks = get_network_data(client, selected_endpoint_id)

    if not containers_with_networks:
        st.info("No running containers with network information found")
        st.stop()

    # Get available networks for filter
    all_networks = set()
    for c in containers_with_networks:
        for net_name in c.get("networks", {}).keys():
            all_networks.add(net_name)

    with col2:
        network_options = ["All Networks"] + sorted(list(all_networks))
        selected_network = st.selectbox(
            "Filter by Network",
            options=network_options,
            key="network_filter",
        )

    st.markdown("---")

    # Build and display graph
    fig = build_network_graph(containers_with_networks, selected_network)

    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No network connections to display")

    st.markdown("---")

    # Network connections table
    st.markdown("### 📋 Network Connections")

    # Build table data
    table_data = []
    for c in containers_with_networks:
        for net_name, net_info in c.get("networks", {}).items():
            if selected_network != "All Networks" and net_name != selected_network:
                continue
            ip = net_info.get("IPAddress", "N/A") if isinstance(net_info, dict) else "N/A"
            gateway = net_info.get("Gateway", "N/A") if isinstance(net_info, dict) else "N/A"
            mac = net_info.get("MacAddress", "N/A") if isinstance(net_info, dict) else "N/A"
            table_data.append({
                "Endpoint": c.get("endpoint_name", "N/A"),
                "Container": c.get("container_name", "N/A"),
                "Network": net_name,
                "IP Address": ip,
                "Gateway": gateway,
                "MAC Address": mac,
                "State": c.get("state", "N/A"),
            })

    if table_data:
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True, height=300)

        # CSV Export
        csv = df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "📥 Download CSV",
            csv,
            f"network_topology_{timestamp_str}.csv",
            "text/csv",
            use_container_width=False,
        )
    else:
        st.info("No network connections to display")

    st.markdown("---")

    # Legend
    st.markdown("### Legend")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("🔷 **Diamond** = Network")
    with col2:
        st.markdown("🟢 **Green** = Running Container")
    with col3:
        st.markdown("⚫ **Gray** = Stopped/Other State")


if __name__ == "__main__":
    main()
