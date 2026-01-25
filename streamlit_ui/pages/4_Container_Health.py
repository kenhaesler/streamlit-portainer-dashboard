"""Container Health - Health monitoring and alerts."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Container Health - Portainer Dashboard",
    page_icon="💚",
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


def main():
    """Container health page."""
    require_auth()
    render_sidebar()

    st.title("💚 Container Health")
    st.markdown("Monitor container health status and alerts")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading health data..."):
        containers = client.get_containers(include_stopped=True)
        endpoints = client.get_endpoints()

    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()
    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()

    if df_containers.empty:
        st.info("No containers found")
        st.stop()

    # Add health status column
    if "status" in df_containers.columns:
        df_containers["health_status"] = df_containers["status"].apply(get_health_status)
    else:
        df_containers["health_status"] = "no_healthcheck"

    # Filter to running containers for health metrics
    running_containers = df_containers[df_containers["state"] == "running"] if "state" in df_containers.columns else df_containers

    # KPIs
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_running = len(running_containers)
        st.metric("Running Containers", total_running)

    with col2:
        healthy = len(running_containers[running_containers["health_status"] == "healthy"])
        st.metric("Healthy", healthy, delta=f"{healthy}/{total_running}" if total_running > 0 else None)

    with col3:
        unhealthy = len(running_containers[running_containers["health_status"] == "unhealthy"])
        delta_color = "inverse" if unhealthy > 0 else "normal"
        st.metric("Unhealthy", unhealthy, delta=-unhealthy if unhealthy > 0 else None, delta_color=delta_color)

    with col4:
        no_check = len(running_containers[running_containers["health_status"] == "no_healthcheck"])
        st.metric("No Health Check", no_check)

    st.markdown("---")

    # Alerts Section
    st.markdown("### 🚨 Health Alerts")

    # Collect alerts
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

    # Stopped containers (not exited normally)
    stopped_containers = df_containers[df_containers["state"] != "running"] if "state" in df_containers.columns else pd.DataFrame()
    for _, container in stopped_containers.head(5).iterrows():  # Limit to 5
        alerts.append({
            "type": "info",
            "icon": "ℹ️",
            "title": "Stopped Container",
            "message": f"Container '{container.get('container_name', 'Unknown')}' is {container.get('state', 'stopped')}",
        })

    if alerts:
        for alert in alerts[:10]:  # Limit to 10 alerts
            if alert["type"] == "error":
                st.error(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
            elif alert["type"] == "warning":
                st.warning(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
            else:
                st.info(f"{alert['icon']} **{alert['title']}**: {alert['message']}")
    else:
        st.success("✅ All systems healthy - no alerts")

    st.markdown("---")

    # Health Overview Chart
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📊 Health Distribution")
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
        st.markdown("### 📈 State Overview")
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

    # Container Health Table
    st.markdown("### 📋 Container Health Status")

    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        health_filter = st.selectbox(
            "Filter by health",
            ["All", "Healthy", "Unhealthy", "No Health Check"],
        )
    with col2:
        search = st.text_input("Search", placeholder="Container name...")

    # Apply filters
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

    # Display table
    if not filtered_df.empty:
        display_cols = ["endpoint_name", "container_name", "image", "state", "status", "health_status"]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        display_df = filtered_df[available_cols].copy()

        # Format health status with icons
        if "health_status" in display_df.columns:
            display_df["health_status"] = display_df["health_status"].map({
                "healthy": "✅ Healthy",
                "unhealthy": "❌ Unhealthy",
                "starting": "🔄 Starting",
                "no_healthcheck": "⚪ No Check",
            })

        display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]

        st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)
    else:
        st.info("No containers match the current filters")


if __name__ == "__main__":
    main()
