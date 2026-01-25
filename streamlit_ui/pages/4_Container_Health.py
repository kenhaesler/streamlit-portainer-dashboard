"""Container Health - Health monitoring and alerts."""

from __future__ import annotations

from datetime import datetime

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


def mask_sensitive_value(key: str, value: str) -> str:
    """Mask sensitive environment variable values."""
    sensitive_keywords = ["PASSWORD", "SECRET", "KEY", "TOKEN", "CREDENTIAL", "API_KEY", "AUTH"]
    if any(kw in key.upper() for kw in sensitive_keywords):
        return "********"
    return value


def main():
    """Container health page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("💚 Container Health")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_health"):
            st.cache_data.clear()
            st.rerun()

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

        # CSV Export
        csv = filtered_df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "📥 Download CSV",
            csv,
            f"container_health_{timestamp_str}.csv",
            "text/csv",
            use_container_width=False,
        )
    else:
        st.info("No containers match the current filters")

    # Container Details Section
    st.markdown("---")
    st.markdown("### 🔍 Container Details")
    st.caption("Select a container to view environment variables, networks, and mounts")

    if not running_containers.empty:
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

        if container_options:
            selected_label = st.selectbox(
                "Select container",
                options=[""] + list(container_options.keys()),
                key="container_details_select",
            )

            if selected_label and selected_label in container_options:
                endpoint_id, container_id, container_name = container_options[selected_label]

                with st.spinner("Loading container details..."):
                    details = client.get_container_details(endpoint_id, container_id)

                if details:
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
                else:
                    st.error("Failed to load container details")


if __name__ == "__main__":
    main()
