"""Metrics Dashboard - Time-series metrics and anomaly detection."""

from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth


st.set_page_config(
    page_title="Metrics Dashboard - Portainer Dashboard",
    page_icon="📊",
    layout="wide",
)


def render_sidebar() -> None:
    """Render sidebar with session info."""
    client = get_api_client()

    with st.sidebar:
        st.markdown(f"**Logged in as:** {st.session_state.get('username', 'User')}")

        session_info = client.get_session_status()
        if session_info:
            minutes_remaining = session_info.get("minutes_remaining", 0)
            seconds_remaining = session_info.get("seconds_remaining", 0)
            if minutes_remaining > 5:
                st.caption(f"Session expires in {minutes_remaining} min")
            elif minutes_remaining > 0:
                secs = seconds_remaining % 60
                st.warning(f"Session expires in {minutes_remaining}:{secs:02d}")
            else:
                st.error(f"Session expires in {seconds_remaining}s")

        if st.button("Logout", use_container_width=True):
            client.logout()
            st.rerun()

        st.markdown("---")

        # Metrics status
        status = client.get_metrics_status()
        if status:
            if status.get("enabled"):
                st.success("Metrics Collection Active")
                st.caption(f"Retention: {status.get('retention_hours', 168)}h")
                if status.get("anomaly_detection_enabled"):
                    st.caption(f"Anomaly threshold: {status.get('zscore_threshold', 3.0)} sigma")
            else:
                st.warning("Metrics Collection Disabled")
        else:
            st.error("Service Unavailable")


def format_bytes(bytes_value: float) -> str:
    """Format bytes into human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def render_dashboard_overview(client) -> None:
    """Render the dashboard overview section."""
    dashboard = client.get_metrics_dashboard()

    if not dashboard:
        st.info("No metrics data available yet. Metrics will be collected during the next monitoring cycle.")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Metrics", f"{dashboard.get('total_metrics', 0):,}")

    with col2:
        st.metric("Containers Tracked", dashboard.get("containers_tracked", 0))

    with col3:
        st.metric("Endpoints Tracked", dashboard.get("endpoints_tracked", 0))

    with col4:
        anomalies = dashboard.get("anomalies_detected_24h", 0)
        st.metric(
            "Anomalies (24h)",
            anomalies,
            delta="detected" if anomalies > 0 else None,
            delta_color="inverse" if anomalies > 0 else "off",
        )

    # Storage info
    storage_bytes = dashboard.get("storage_size_bytes", 0)
    oldest = dashboard.get("oldest_metric")
    newest = dashboard.get("newest_metric")

    info_parts = [f"Storage: {format_bytes(storage_bytes)}"]
    if oldest:
        try:
            oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            info_parts.append(f"Oldest: {oldest_dt.strftime('%Y-%m-%d %H:%M')}")
        except ValueError:
            pass
    if newest:
        try:
            newest_dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
            info_parts.append(f"Latest: {newest_dt.strftime('%Y-%m-%d %H:%M')}")
        except ValueError:
            pass

    st.caption(" | ".join(info_parts))


def render_anomalies_section(client) -> None:
    """Render the anomalies section."""
    st.subheader("Recent Anomalies")

    col1, col2 = st.columns([3, 1])
    with col1:
        hours = st.slider("Time range (hours)", 1, 168, 24, key="anomaly_hours")
    with col2:
        limit = st.selectbox("Max results", [25, 50, 100], index=1, key="anomaly_limit")

    anomalies = client.get_anomalies(hours=hours, limit=limit)

    if not anomalies:
        st.success("No anomalies detected in the selected time range.")
        return

    # Convert to dataframe for display
    df_data = []
    for a in anomalies:
        timestamp = a.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp_str = timestamp

        df_data.append({
            "Time": timestamp_str,
            "Container": a.get("container_name", ""),
            "Metric": a.get("metric_type", "").replace("_", " ").title(),
            "Value": f"{a.get('current_value', 0):.2f}",
            "Expected": f"{a.get('expected_value', 0):.2f}",
            "Z-Score": f"{a.get('zscore', 0):.2f}",
            "Direction": a.get("direction", "").upper(),
            "Endpoint": a.get("endpoint_name", ""),
        })

    df = pd.DataFrame(df_data)

    # Color coding for direction
    def highlight_direction(row):
        if row["Direction"] == "HIGH":
            return ["background-color: rgba(255, 75, 75, 0.3)"] * len(row)
        elif row["Direction"] == "LOW":
            return ["background-color: rgba(75, 75, 255, 0.3)"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(highlight_direction, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Export
    if df_data:
        csv = df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "Download Anomalies CSV",
            csv,
            f"anomalies_{timestamp_str}.csv",
            "text/csv",
        )


def render_container_metrics(client) -> None:
    """Render container-specific metrics charts."""
    st.subheader("Container Metrics")

    # Get containers for selection
    containers = client.get_containers(include_stopped=False)

    if not containers:
        st.info("No running containers found.")
        return

    # Build container options
    container_options = {}
    for c in containers:
        name = c.get("container_name", c.get("container_id", "unknown")[:12])
        container_id = c.get("container_id", "")
        endpoint_name = c.get("endpoint_name", "")
        label = f"{name} ({endpoint_name})"
        container_options[label] = container_id

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        selected_label = st.selectbox(
            "Select Container",
            options=list(container_options.keys()),
            key="metrics_container",
        )

    with col2:
        metric_type = st.selectbox(
            "Metric Type",
            ["cpu_percent", "memory_percent", "memory_usage"],
            format_func=lambda x: x.replace("_", " ").title(),
            key="metrics_type",
        )

    with col3:
        hours = st.selectbox(
            "Time Range",
            [1, 6, 12, 24, 48, 168],
            index=3,
            format_func=lambda x: f"{x}h" if x < 24 else f"{x//24}d",
            key="metrics_hours",
        )

    if selected_label and selected_label in container_options:
        container_id = container_options[selected_label]

        # Get metrics
        metrics = client.get_container_metrics(
            container_id,
            metric_type=metric_type,
            hours=hours,
            limit=2000,
        )

        if not metrics:
            st.info(f"No {metric_type.replace('_', ' ')} data available for this container.")
            return

        # Convert to dataframe
        df_data = []
        for m in metrics:
            timestamp = m.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue

            df_data.append({
                "timestamp": dt,
                "value": m.get("value", 0),
            })

        if not df_data:
            st.info("No valid metric data.")
            return

        df = pd.DataFrame(df_data)
        df = df.sort_values("timestamp")

        # Create chart
        fig = px.line(
            df,
            x="timestamp",
            y="value",
            title=f"{metric_type.replace('_', ' ').title()} - {selected_label}",
        )

        # Customize based on metric type
        if metric_type == "memory_usage":
            fig.update_yaxes(title="Memory (bytes)")
        elif "percent" in metric_type:
            fig.update_yaxes(title="Percentage (%)", range=[0, 100])

        fig.update_layout(
            xaxis_title="Time",
            hovermode="x unified",
            height=400,
        )

        st.plotly_chart(fig, use_container_width=True)

        # Show summary
        summary = client.get_container_metrics_summary(container_id, metric_type, hours)
        if summary:
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Current", f"{summary.get('latest_value', 0):.2f}")
            with col2:
                st.metric("Average", f"{summary.get('avg_value', 0):.2f}")
            with col3:
                st.metric("Min", f"{summary.get('min_value', 0):.2f}")
            with col4:
                st.metric("Max", f"{summary.get('max_value', 0):.2f}")

            st.caption(f"Std Dev: {summary.get('std_dev', 0):.2f} | Samples: {summary.get('count', 0)}")


def main() -> None:
    """Metrics Dashboard main page."""
    require_auth()
    render_sidebar()

    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Metrics Dashboard")
    with col2:
        if st.button("Refresh", use_container_width=True, key="refresh_metrics"):
            st.rerun()

    st.markdown("Time-series container metrics with anomaly detection")

    client = get_api_client()

    status = client.get_metrics_status()

    if not status or not status.get("enabled"):
        st.warning(
            "Metrics collection is disabled. "
            "Set `MONITORING_METRICS_ENABLED=true` to enable."
        )
        return

    # Overview section
    render_dashboard_overview(client)

    st.markdown("---")

    # Tabs
    tab1, tab2 = st.tabs(["Container Metrics", "Anomaly Detection"])

    with tab1:
        render_container_metrics(client)

    with tab2:
        render_anomalies_section(client)


if __name__ == "__main__":
    main()
