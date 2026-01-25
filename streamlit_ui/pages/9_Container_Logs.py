"""Container Logs - View container logs via Portainer API."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Container Logs - Portainer Dashboard",
    page_icon="📜",
    layout="wide",
)


def main():
    """Container logs page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("📜 Container Logs")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_logs"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("View container logs directly from Docker via Portainer API")

    client = get_api_client()

    # Fetch endpoints and containers
    with st.spinner("Loading endpoints..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)

    if not endpoints:
        st.warning("No endpoints found")
        st.stop()

    if not containers:
        st.warning("No containers found")
        st.stop()

    # Build endpoint options
    endpoint_options = {
        f"{ep.get('endpoint_name', 'Unknown')} (ID: {ep.get('endpoint_id')})": ep.get('endpoint_id')
        for ep in endpoints
    }

    # Controls
    st.markdown("### Log Settings")

    col1, col2 = st.columns(2)

    with col1:
        selected_endpoint_label = st.selectbox(
            "Select Endpoint",
            options=list(endpoint_options.keys()),
            key="log_endpoint",
        )
        selected_endpoint_id = endpoint_options.get(selected_endpoint_label)

    # Filter containers by selected endpoint
    endpoint_containers = [
        c for c in containers
        if c.get("endpoint_id") == selected_endpoint_id
    ]

    with col2:
        if endpoint_containers:
            container_options = {
                f"{c.get('container_name', 'Unknown')} ({c.get('state', 'unknown')})": c.get('container_id')
                for c in endpoint_containers
            }
            selected_container_label = st.selectbox(
                "Select Container",
                options=list(container_options.keys()),
                key="log_container",
            )
            selected_container_id = container_options.get(selected_container_label)
        else:
            st.info("No containers on this endpoint")
            selected_container_id = None

    st.markdown("---")

    # Log options
    col1, col2, col3 = st.columns(3)

    with col1:
        tail_lines = st.slider(
            "Lines to fetch",
            min_value=100,
            max_value=5000,
            value=500,
            step=100,
            key="log_tail",
        )

    with col2:
        time_range = st.selectbox(
            "Time range",
            options=["All time", "Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours"],
            key="log_time_range",
        )
        time_range_map = {
            "All time": None,
            "Last 15 minutes": 15,
            "Last 1 hour": 60,
            "Last 6 hours": 360,
            "Last 24 hours": 1440,
        }
        since_minutes = time_range_map.get(time_range)

    with col3:
        include_timestamps = st.checkbox(
            "Include timestamps",
            value=True,
            key="log_timestamps",
        )

    st.markdown("---")

    # Fetch and display logs
    if selected_container_id:
        if st.button("Fetch Logs", type="primary", use_container_width=True):
            with st.spinner("Fetching logs..."):
                logs_response = client.get_container_logs(
                    selected_endpoint_id,
                    selected_container_id,
                    tail=tail_lines,
                    timestamps=include_timestamps,
                    since_minutes=since_minutes,
                )

            if logs_response:
                logs_text = logs_response.get("logs", "")
                container_name = logs_response.get("container_name", "container")

                st.markdown(f"### Logs for `{container_name}`")

                # Stats
                line_count = len(logs_text.split("\n")) if logs_text else 0
                st.caption(f"Showing {line_count} lines")

                # Download button
                col1, col2 = st.columns([4, 1])
                with col2:
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        "📥 Download",
                        logs_text,
                        f"{container_name}_logs_{timestamp_str}.txt",
                        "text/plain",
                        use_container_width=True,
                    )

                # Display logs in code block with scrolling
                if logs_text.strip():
                    st.code(logs_text, language="log", line_numbers=True)
                else:
                    st.info("No logs available for the selected time range")
            else:
                st.error("Failed to fetch logs. The container may not exist or be inaccessible.")

    else:
        st.info("Select an endpoint and container to view logs")

    st.markdown("---")
    st.caption(
        "Logs are fetched directly from the Docker daemon via Portainer API. "
        "For long-term log storage and analysis, consider using Kibana integration."
    )


if __name__ == "__main__":
    main()
