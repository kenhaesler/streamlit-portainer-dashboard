"""Logs - Unified logging interface for live and searchable logs."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Logs - Portainer Dashboard",
    page_icon="📋",
    layout="wide",
)


def fetch_kibana_logs(client, endpoint_name: str, container_filter: str, search_text: str, time_window: str) -> list[dict]:
    """Fetch logs from Kibana via the backend API."""
    now = datetime.utcnow()
    time_deltas = {
        "Last 15 minutes": timedelta(minutes=15),
        "Last 1 hour": timedelta(hours=1),
        "Last 6 hours": timedelta(hours=6),
        "Last 24 hours": timedelta(hours=24),
        "Last 7 days": timedelta(days=7),
    }
    delta = time_deltas.get(time_window, timedelta(hours=1))
    start_time = now - delta

    params = {
        "start_time": start_time.isoformat() + "Z",
        "end_time": now.isoformat() + "Z",
    }
    if endpoint_name and endpoint_name != "All":
        params["hostname"] = endpoint_name
    if container_filter:
        params["container"] = container_filter
    if search_text:
        params["query"] = search_text

    result = client.get("/api/v1/logs/", params=params)
    return result if isinstance(result, list) else []


def main():
    """Logs page - unified logging interface."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("📋 Logs")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_logs"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("View live container logs or search historical logs via Kibana")

    client = get_api_client()

    # Fetch endpoints and containers
    with st.spinner("Loading endpoints..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)

    if not endpoints:
        st.warning("No endpoints found")
        st.stop()

    # Tabs
    tab1, tab2 = st.tabs(["📜 Live Logs", "🔍 Search Logs (Kibana)"])

    with tab1:
        render_live_logs_tab(client, endpoints, containers)

    with tab2:
        render_search_logs_tab(client, endpoints)


def render_live_logs_tab(client, endpoints: list, containers: list):
    """Render the Live Logs tab - direct Docker logs via Portainer."""
    st.markdown("### Live Container Logs")
    st.caption("View logs directly from Docker daemon via Portainer API")

    if not containers:
        st.warning("No containers found")
        return

    # Build endpoint options
    endpoint_options = {
        f"{ep.get('endpoint_name', 'Unknown')} (ID: {ep.get('endpoint_id')})": ep.get('endpoint_id')
        for ep in endpoints
    }

    # Controls
    col1, col2 = st.columns(2)

    with col1:
        selected_endpoint_label = st.selectbox(
            "Select Endpoint",
            options=list(endpoint_options.keys()),
            key="live_log_endpoint",
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
                key="live_log_container",
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
            key="live_log_tail",
        )

    with col2:
        time_range = st.selectbox(
            "Time range",
            options=["All time", "Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours"],
            key="live_log_time_range",
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
            key="live_log_timestamps",
        )

    st.markdown("---")

    # Fetch and display logs
    if selected_container_id:
        if st.button("Fetch Logs", type="primary", use_container_width=True, key="fetch_live_logs"):
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


def render_search_logs_tab(client, endpoints: list):
    """Render the Search Logs tab - Kibana/Elasticsearch integration."""
    st.markdown("### Search Logs")
    st.caption("Query historical logs from Kibana/Elasticsearch")

    # Configuration notice
    st.info(
        "💡 **Note:** Log searching requires Kibana/Elasticsearch integration. "
        "Ensure `KIBANA_LOGS_ENDPOINT` and `KIBANA_API_KEY` are configured."
    )

    # Get endpoint names for filtering
    endpoint_names = ["All"] + [e.get("endpoint_name", "Unknown") for e in endpoints]

    # Filters
    st.markdown("### Filters")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        selected_endpoint = st.selectbox(
            "Edge Agent",
            endpoint_names,
            help="Filter logs by edge agent hostname",
            key="search_endpoint"
        )

    with col2:
        container_filter = st.text_input(
            "Container",
            placeholder="Container name...",
            help="Filter by container name (partial match)",
            key="search_container"
        )

    with col3:
        search_text = st.text_input(
            "Search",
            placeholder="Search in logs...",
            help="Free text search in log messages",
            key="search_text"
        )

    with col4:
        time_window = st.selectbox(
            "Time Range",
            ["Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days"],
            index=1,
            help="How far back to search",
            key="search_time_range"
        )

    # Search button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        search_clicked = st.button("🔍 Search Logs", use_container_width=True, type="primary", key="do_search")
    with col2:
        clear_clicked = st.button("🗑️ Clear", use_container_width=True, key="clear_search")

    st.markdown("---")

    # Results area
    if search_clicked:
        st.markdown("### Log Results")

        with st.spinner("Querying logs..."):
            try:
                logs = fetch_kibana_logs(
                    client,
                    selected_endpoint if selected_endpoint != "All" else "",
                    container_filter,
                    search_text,
                    time_window
                )

                if logs:
                    df_logs = pd.DataFrame(logs)

                    st.success(f"Found {len(logs)} log entries")

                    display_cols = ["timestamp", "hostname", "container_name", "message", "level"]
                    available_cols = [c for c in display_cols if c in df_logs.columns]

                    if available_cols:
                        display_df = df_logs[available_cols].copy()

                        if "timestamp" in display_df.columns:
                            display_df["timestamp"] = pd.to_datetime(
                                display_df["timestamp"], errors="coerce"
                            ).dt.strftime("%Y-%m-%d %H:%M:%S")

                        display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]
                        st.dataframe(display_df, use_container_width=True, hide_index=True, height=500)
                    else:
                        st.dataframe(df_logs, use_container_width=True, hide_index=True, height=500)

                    csv = df_logs.to_csv(index=False)
                    st.download_button(
                        "📥 Download Logs CSV",
                        csv,
                        f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        "text/csv"
                    )
                else:
                    st.info("No logs found matching your criteria")

            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg or "not found" in error_msg.lower():
                    st.warning(
                        "📡 **Kibana API not available**\n\n"
                        "The logs endpoint is not configured or Kibana integration is not enabled. "
                        "To enable log searching:\n\n"
                        "1. Set `KIBANA_LOGS_ENDPOINT` to your Elasticsearch/Kibana URL\n"
                        "2. Set `KIBANA_API_KEY` for authentication\n"
                        "3. Restart the backend service"
                    )
                else:
                    st.error(f"Error querying logs: {e}")

    elif clear_clicked:
        st.rerun()

    else:
        st.markdown("### Log Results")
        st.caption("Click 'Search Logs' to query log entries from your edge agents")

        with st.expander("💡 Example Queries"):
            st.markdown("""
            **Find errors in the last hour:**
            - Time Range: Last 1 hour
            - Search: `error` or `ERROR`

            **Check specific container logs:**
            - Container: `nginx` or `postgres`
            - Time Range: Last 15 minutes

            **Monitor specific edge agent:**
            - Edge Agent: Select from dropdown
            - Time Range: Last 6 hours

            **Search for specific events:**
            - Search: `connection refused` or `timeout`
            """)


if __name__ == "__main__":
    main()
