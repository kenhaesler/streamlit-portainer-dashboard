"""Containers - Unified container management, health monitoring, and networking."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar, render_refresh_controls


st.set_page_config(
    page_title="Containers - Portainer Dashboard",
    page_icon="🐳",
    layout="wide",
)


def get_health_status(status: str) -> str:
    """Extract health status from container status string."""
    status_lower = status.lower() if status else ""
    if "(healthy)" in status_lower:
        return "healthy"
    elif "(unhealthy)" in status_lower:
        return "unhealthy"
    elif "(health:" in status_lower:
        return "starting"
    return "no_healthcheck"


def mask_sensitive_value(key: str, value: str) -> str:
    """Mask sensitive environment variable values."""
    sensitive_keywords = ["PASSWORD", "SECRET", "KEY", "TOKEN", "CREDENTIAL", "API_KEY", "AUTH"]
    if any(kw in key.upper() for kw in sensitive_keywords):
        return "********"
    return value


def main():
    """Containers page - unified container management."""
    require_auth()
    render_sidebar()

    # Title with refresh controls
    st.title("🐳 Containers")
    st.markdown("Container management, health monitoring, and resource analysis")

    # Auto-refresh controls
    render_refresh_controls("containers")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading container data..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)

    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()
    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()

    if df_containers.empty:
        st.info("No containers found")
        st.stop()

    # Add health status column
    if "status" in df_containers.columns:
        df_containers["health_status"] = df_containers["status"].apply(get_health_status)
    else:
        df_containers["health_status"] = "no_healthcheck"

    # KPI Row
    running_containers = df_containers[df_containers["state"] == "running"] if "state" in df_containers.columns else df_containers

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Total Containers", len(df_containers))

    with col2:
        running = len(running_containers)
        st.metric("Running", running)

    with col3:
        healthy = len(running_containers[running_containers["health_status"] == "healthy"])
        st.metric("Healthy", healthy)

    with col4:
        unhealthy = len(running_containers[running_containers["health_status"] == "unhealthy"])
        st.metric("Unhealthy", unhealthy, delta=-unhealthy if unhealthy > 0 else None, delta_color="inverse")

    with col5:
        unique_images = df_containers["image"].nunique() if "image" in df_containers.columns else 0
        st.metric("Unique Images", unique_images)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 All Containers",
        "💚 Health & Alerts",
        "📦 Images",
        "🌐 Networks",
        "🔍 Container Details"
    ])

    with tab1:
        render_containers_tab(df_containers, df_endpoints)

    with tab2:
        render_health_tab(df_containers, df_endpoints, running_containers, client)

    with tab3:
        render_images_tab(df_containers)

    with tab4:
        render_networks_tab(df_containers, client)

    with tab5:
        render_details_tab(running_containers, client)


def render_containers_tab(df_containers: pd.DataFrame, df_endpoints: pd.DataFrame):
    """Render the All Containers tab."""
    st.markdown("### Container Distribution by Endpoint")

    if "endpoint_name" in df_containers.columns and "state" in df_containers.columns:
        # Aggregate by endpoint and state
        agg_df = df_containers.groupby(["endpoint_name", "endpoint_id", "state"]).size().reset_index(name="count")

        # Pivot for stacked bar chart
        pivot_df = agg_df.pivot_table(
            index=["endpoint_name", "endpoint_id"],
            columns="state",
            values="count",
            fill_value=0
        ).reset_index()

        # Create stacked bar chart
        fig = go.Figure()

        state_colors = {
            "running": "#10B981",
            "exited": "#6B7280",
            "paused": "#F59E0B",
            "restarting": "#3B82F6",
            "created": "#8B5CF6",
            "dead": "#EF4444",
        }

        states_in_data = [col for col in pivot_df.columns if col not in ["endpoint_name", "endpoint_id"]]

        for state in states_in_data:
            fig.add_trace(go.Bar(
                name=state.capitalize(),
                x=pivot_df["endpoint_name"],
                y=pivot_df[state],
                marker_color=state_colors.get(state, "#9CA3AF"),
                customdata=pivot_df["endpoint_id"],
                hovertemplate="<b>%{x}</b><br>" + state.capitalize() + ": %{y}<extra></extra>",
            ))

        fig.update_layout(
            barmode='stack',
            xaxis_title="Endpoint",
            yaxis_title="Containers",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            margin=dict(t=50, b=50, l=50, r=50),
            height=350,
            hovermode="x unified",
        )

        selected_points = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="container_chart")

        # Handle click selection
        selected_endpoint_name = None
        if selected_points and selected_points.selection and selected_points.selection.points:
            point = selected_points.selection.points[0]
            if "x" in point:
                selected_endpoint_name = point["x"]

    st.markdown("---")

    # Filters
    st.markdown("### Filters")

    col1, col2, col3 = st.columns(3)

    with col1:
        search_term = st.text_input("Search containers", placeholder="Container name or image...", key="container_search")

    with col2:
        states = ["All"] + list(df_containers["state"].unique()) if "state" in df_containers.columns else ["All"]
        selected_state = st.selectbox("State", states, key="container_state_filter")

    with col3:
        endpoint_options = ["All"] + list(df_containers["endpoint_name"].dropna().unique()) if "endpoint_name" in df_containers.columns else ["All"]
        default_idx = 0
        if selected_endpoint_name and selected_endpoint_name in endpoint_options:
            default_idx = endpoint_options.index(selected_endpoint_name)
        selected_endpoint_filter = st.selectbox("Endpoint", endpoint_options, index=default_idx, key="container_endpoint_filter")

    # Apply filters
    filtered_df = df_containers.copy()

    if search_term:
        mask = (
            filtered_df["container_name"].str.contains(search_term, case=False, na=False) |
            filtered_df["image"].str.contains(search_term, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    if selected_state != "All":
        filtered_df = filtered_df[filtered_df["state"] == selected_state]

    if selected_endpoint_filter != "All":
        filtered_df = filtered_df[filtered_df["endpoint_name"] == selected_endpoint_filter]

    # Container Table
    st.markdown(f"### Containers ({len(filtered_df)})")

    if not filtered_df.empty:
        display_cols = [
            "endpoint_name", "container_name", "image", "state", "status",
            "restart_count", "created_at", "ports",
        ]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        display_df = filtered_df[available_cols].copy()

        if "created_at" in display_df.columns:
            display_df["created_at"] = pd.to_datetime(display_df["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

        column_names = {
            "endpoint_name": "Endpoint",
            "container_name": "Container",
            "image": "Image",
            "state": "State",
            "status": "Status",
            "restart_count": "Restarts",
            "created_at": "Created",
            "ports": "Ports",
        }
        display_df = display_df.rename(columns=column_names)

        st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

        csv = filtered_df.to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "containers.csv", "text/csv")
    else:
        st.info("No containers match the current filters")


def render_health_tab(df_containers: pd.DataFrame, df_endpoints: pd.DataFrame, running_containers: pd.DataFrame, client):
    """Render the Health & Alerts tab."""
    # Alerts Section
    st.markdown("### Health Alerts")

    alerts = []

    # Offline endpoints
    if not df_endpoints.empty and "endpoint_status" in df_endpoints.columns:
        offline_endpoints = df_endpoints[df_endpoints["endpoint_status"] != 1]
        for _, ep in offline_endpoints.iterrows():
            alerts.append({
                "type": "error",
                "icon": "🔴",
                "title": "Endpoint Offline",
                "message": f"Endpoint '{ep.get('endpoint_name', 'Unknown')}' is offline",
            })

    # Unhealthy containers
    unhealthy_containers = running_containers[running_containers["health_status"] == "unhealthy"]
    for _, container in unhealthy_containers.iterrows():
        alerts.append({
            "type": "warning",
            "icon": "⚠️",
            "title": "Unhealthy Container",
            "message": f"Container '{container.get('container_name', 'Unknown')}' on {container.get('endpoint_name', 'Unknown')} is unhealthy",
        })

    # Stopped containers
    stopped_containers = df_containers[df_containers["state"] != "running"] if "state" in df_containers.columns else pd.DataFrame()
    for _, container in stopped_containers.head(5).iterrows():
        alerts.append({
            "type": "info",
            "icon": "ℹ️",
            "title": "Stopped Container",
            "message": f"Container '{container.get('container_name', 'Unknown')}' is {container.get('state', 'stopped')}",
        })

    if alerts:
        for alert in alerts[:10]:
            if alert["type"] == "error":
                st.error(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
            elif alert["type"] == "warning":
                st.warning(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
            else:
                st.info(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
    else:
        st.success("✅ All systems healthy - no alerts")

    st.markdown("---")

    # Health Overview Charts
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Health Distribution")
        if not running_containers.empty:
            health_counts = running_containers["health_status"].value_counts()

            fig = px.pie(
                values=health_counts.values,
                names=health_counts.index.map({
                    "healthy": "Healthy",
                    "unhealthy": "Unhealthy",
                    "starting": "Starting",
                    "no_healthcheck": "No Health Check",
                }),
                color=health_counts.index,
                color_discrete_map={
                    "healthy": "#10B981",
                    "unhealthy": "#EF4444",
                    "starting": "#F59E0B",
                    "no_healthcheck": "#6B7280",
                },
                hole=0.4,
            )
            fig.update_layout(
                showlegend=True,
                legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center"),
                margin=dict(t=20, b=50, l=20, r=20),
                height=300,
            )
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### State Overview")
        if not df_containers.empty and "state" in df_containers.columns:
            state_counts = df_containers["state"].value_counts()

            fig = px.bar(
                x=state_counts.index,
                y=state_counts.values,
                color=state_counts.index,
                color_discrete_map={
                    "running": "#10B981",
                    "exited": "#6B7280",
                    "paused": "#F59E0B",
                    "restarting": "#3B82F6",
                },
            )
            fig.update_layout(
                showlegend=False,
                xaxis_title="State",
                yaxis_title="Count",
                margin=dict(t=20, b=50, l=50, r=20),
                height=300,
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Health Status Table
    st.markdown("### Container Health Status")

    col1, col2 = st.columns(2)
    with col1:
        health_filter = st.selectbox(
            "Filter by health",
            ["All", "Healthy", "Unhealthy", "No Health Check"],
            key="health_filter"
        )
    with col2:
        search = st.text_input("Search", placeholder="Container name...", key="health_search")

    filtered_df = running_containers.copy()

    if health_filter != "All":
        filter_map = {
            "Healthy": "healthy",
            "Unhealthy": "unhealthy",
            "No Health Check": "no_healthcheck",
        }
        filtered_df = filtered_df[filtered_df["health_status"] == filter_map.get(health_filter, "")]

    if search:
        filtered_df = filtered_df[
            filtered_df["container_name"].str.contains(search, case=False, na=False)
        ]

    if not filtered_df.empty:
        display_cols = ["endpoint_name", "container_name", "image", "state", "status", "health_status"]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        display_df = filtered_df[available_cols].copy()

        if "health_status" in display_df.columns:
            display_df["health_status"] = display_df["health_status"].map({
                "healthy": "✅ Healthy",
                "unhealthy": "❌ Unhealthy",
                "starting": "🔄 Starting",
                "no_healthcheck": "⚪ No Check",
            })

        display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]

        st.dataframe(display_df, use_container_width=True, hide_index=True, height=300)

        csv = filtered_df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button("📥 Download CSV", csv, f"container_health_{timestamp_str}.csv", "text/csv")
    else:
        st.info("No containers match the current filters")


def render_images_tab(df_containers: pd.DataFrame):
    """Render the Images tab."""
    st.markdown("### Image Distribution")

    if df_containers.empty or "image" not in df_containers.columns:
        st.info("No image data available")
        return

    running_df = df_containers[df_containers["state"] == "running"] if "state" in df_containers.columns else df_containers

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Top Images by Container Count")
        image_counts = running_df["image"].value_counts().head(15)
        display_names = [img.split("/")[-1][:40] for img in image_counts.index]

        fig = px.bar(
            y=display_names,
            x=image_counts.values,
            orientation='h',
            color=image_counts.values,
            color_continuous_scale="Blues",
        )
        fig.update_layout(
            showlegend=False,
            xaxis_title="Containers",
            yaxis_title="",
            margin=dict(t=20, b=50, l=20, r=20),
            height=400,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### Image Distribution Across Agents")
        if "endpoint_name" in running_df.columns:
            image_endpoint_counts = running_df.groupby("image")["endpoint_name"].nunique().sort_values(ascending=False).head(15)
            display_names = [img.split("/")[-1][:40] for img in image_endpoint_counts.index]

            fig = px.bar(
                y=display_names,
                x=image_endpoint_counts.values,
                orientation='h',
                color=image_endpoint_counts.values,
                color_continuous_scale="Greens",
            )
            fig.update_layout(
                showlegend=False,
                xaxis_title="Endpoints Using Image",
                yaxis_title="",
                margin=dict(t=20, b=50, l=20, r=20),
                height=400,
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)

    # Image Summary Table
    st.markdown("#### Image Summary")

    image_summary = df_containers.groupby("image").agg({
        "container_id": "count",
        "endpoint_name": "nunique",
        "state": lambda x: (x == "running").sum()
    }).reset_index()
    image_summary.columns = ["Image", "Total Containers", "Endpoints", "Running"]
    image_summary = image_summary.sort_values("Total Containers", ascending=False)

    # Shorten image names for display
    image_summary["Image"] = image_summary["Image"].apply(lambda x: x.split("/")[-1][:50] if x else "unknown")

    st.dataframe(image_summary, use_container_width=True, hide_index=True, height=300)

    csv = image_summary.to_csv(index=False)
    st.download_button("📥 Download Image Summary CSV", csv, "image_summary.csv", "text/csv")


def render_networks_tab(df_containers: pd.DataFrame, client):
    """Render the Networks tab."""
    st.markdown("### Network Topology")

    if df_containers.empty:
        st.info("No containers found")
        return

    running_df = df_containers[df_containers["state"] == "running"] if "state" in df_containers.columns else df_containers

    # Filters
    col1, col2 = st.columns(2)

    with col1:
        endpoint_options = ["All"] + list(running_df["endpoint_name"].dropna().unique()) if "endpoint_name" in running_df.columns else ["All"]
        selected_endpoint = st.selectbox("Filter by Endpoint", endpoint_options, key="network_endpoint_filter")

    if selected_endpoint != "All":
        running_df = running_df[running_df["endpoint_name"] == selected_endpoint]

    # Fetch container details for network info
    st.markdown("#### Network Connections")

    if running_df.empty:
        st.info("No containers to show")
        return

    # Build network data from container details
    network_data = []

    # Use a subset of containers to avoid too many API calls
    sample_containers = running_df.head(50)

    with st.spinner("Loading network information..."):
        for _, row in sample_containers.iterrows():
            endpoint_id = row.get("endpoint_id")
            container_id = row.get("container_id")
            container_name = row.get("container_name", "Unknown")
            endpoint_name = row.get("endpoint_name", "Unknown")
            state = row.get("state", "unknown")

            if endpoint_id and container_id:
                try:
                    details = client.get_container_details(endpoint_id, container_id)
                    if details and details.get("networks"):
                        for net_name, net_info in details.get("networks", {}).items():
                            if isinstance(net_info, dict):
                                network_data.append({
                                    "endpoint_name": endpoint_name,
                                    "container_name": container_name,
                                    "network": net_name,
                                    "ip_address": net_info.get("IPAddress", "N/A"),
                                    "gateway": net_info.get("Gateway", "N/A"),
                                    "mac_address": net_info.get("MacAddress", "N/A"),
                                    "state": state,
                                })
                except Exception:
                    logger.debug("Failed to parse network info for container", exc_info=True)

    if network_data:
        df_networks = pd.DataFrame(network_data)

        # Network filter
        with col2:
            network_options = ["All"] + list(df_networks["network"].unique())
            selected_network = st.selectbox("Filter by Network", network_options, key="network_filter")

        if selected_network != "All":
            df_networks = df_networks[df_networks["network"] == selected_network]

        # Display table
        display_df = df_networks.copy()
        display_df.columns = ["Endpoint", "Container", "Network", "IP Address", "Gateway", "MAC Address", "State"]

        st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

        csv = df_networks.to_csv(index=False)
        st.download_button("📥 Download Network Data CSV", csv, "network_data.csv", "text/csv")
    else:
        st.info("No network data available. Select fewer containers or check container details.")


def render_details_tab(running_containers: pd.DataFrame, client):
    """Render the Container Details tab."""
    st.markdown("### Container Details")
    st.caption("Select a container to view environment variables, networks, and mounts")

    if running_containers.empty:
        st.info("No running containers")
        return

    # Build container selection options
    container_options = {}
    for _, row in running_containers.iterrows():
        endpoint_name = row.get("endpoint_name", "Unknown")
        container_name = row.get("container_name", "Unknown")
        endpoint_id = row.get("endpoint_id")
        container_id = row.get("container_id")
        if endpoint_id and container_id:
            label = f"{container_name} @ {endpoint_name}"
            container_options[label] = (endpoint_id, container_id, container_name)

    if not container_options:
        st.info("No containers available for inspection")
        return

    selected_label = st.selectbox(
        "Select container",
        options=[""] + list(container_options.keys()),
        key="container_details_select",
    )

    if not selected_label or selected_label not in container_options:
        st.info("Select a container above to view details")
        return

    endpoint_id, container_id, container_name = container_options[selected_label]

    with st.spinner("Loading container details..."):
        details = client.get_container_details(endpoint_id, container_id)

    if not details:
        st.error("Failed to load container details")
        return

    col1, col2 = st.columns(2)

    with col1:
        # Environment Variables
        with st.expander("🔐 Environment Variables", expanded=False):
            env_vars = details.get("environment") or []
            if env_vars:
                for env in env_vars:
                    if "=" in env:
                        key, val = env.split("=", 1)
                        masked_val = mask_sensitive_value(key, val)
                        st.code(f"{key}={masked_val}", language=None)
                    else:
                        st.code(env, language=None)
            else:
                st.info("No environment variables")

        # Labels
        with st.expander("🏷️ Labels", expanded=False):
            labels = details.get("labels") or {}
            if labels:
                for key, val in labels.items():
                    st.text(f"{key}: {val}")
            else:
                st.info("No labels")

    with col2:
        # Networks
        with st.expander("🌐 Networks", expanded=False):
            networks = details.get("networks") or {}
            if networks:
                for net_name, net_info in networks.items():
                    st.markdown(f"**{net_name}**")
                    if isinstance(net_info, dict):
                        ip = net_info.get("IPAddress", "N/A")
                        gateway = net_info.get("Gateway", "N/A")
                        mac = net_info.get("MacAddress", "N/A")
                        st.text(f"  IP: {ip}")
                        st.text(f"  Gateway: {gateway}")
                        st.text(f"  MAC: {mac}")
            else:
                st.info("No network configuration")

        # Mounts
        with st.expander("💾 Mounts", expanded=False):
            mounts = details.get("mounts") or []
            if mounts:
                for mount in mounts:
                    if isinstance(mount, dict):
                        source = mount.get("Source", "N/A")
                        dest = mount.get("Destination", "N/A")
                        mode = mount.get("Mode", "rw")
                        st.text(f"{source} -> {dest} ({mode})")
            else:
                st.info("No volume mounts")

    # Additional info
    st.markdown("**Additional Info:**")
    info_cols = st.columns(4)
    with info_cols[0]:
        st.metric("Restart Policy", details.get("restart_policy") or "N/A")
    with info_cols[1]:
        privileged = details.get("privileged")
        st.metric("Privileged", "Yes" if privileged else "No")
    with info_cols[2]:
        cpu = details.get("cpu_percent")
        st.metric("CPU %", f"{cpu:.1f}%" if cpu is not None else "N/A")
    with info_cols[3]:
        mem = details.get("memory_percent")
        st.metric("Memory %", f"{mem:.1f}%" if mem is not None else "N/A")


if __name__ == "__main__":
    main()
