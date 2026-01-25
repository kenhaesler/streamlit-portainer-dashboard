"""Edge Agent Logs - Query logs via Kibana/Elasticsearch."""

from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Edge Agent Logs - Portainer Dashboard",
    page_icon="📋",
    layout="wide",
)


def fetch_logs(client, endpoint_name: str, container_filter: str, search_text: str, time_window: str) -> list[dict]:
    """Fetch logs from Kibana via the backend API."""
    # Calculate time range
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

    # Build query parameters
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

    # Call the logs API
    result = client.get("/api/v1/logs/", params=params)
    return result if isinstance(result, list) else []


def main():
    """Edge Agent Logs page."""
    require_auth()
    render_sidebar()

    st.title("📋 Edge Agent Logs")
    st.markdown("Query container logs from your edge agents via Kibana")

    client = get_api_client()

    # Check if Kibana is configured
    # We'll try to fetch endpoints to get hostnames for filtering
    with st.spinner("Loading..."):
        endpoints = client.get_endpoints()

    if not endpoints:
        st.warning("No endpoints found. Cannot query logs.")
        st.stop()

    # Get endpoint names for filtering
    endpoint_names = ["All"] + [e.get("endpoint_name", "Unknown") for e in endpoints]

    # Filters
    st.markdown("### 🔍 Log Filters")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        selected_endpoint = st.selectbox(
            "Edge Agent",
            endpoint_names,
            help="Filter logs by edge agent hostname"
        )

    with col2:
        container_filter = st.text_input(
            "Container",
            placeholder="Container name...",
            help="Filter by container name (partial match)"
        )

    with col3:
        search_text = st.text_input(
            "Search",
            placeholder="Search in logs...",
            help="Free text search in log messages"
        )

    with col4:
        time_window = st.selectbox(
            "Time Range",
            ["Last 15 minutes", "Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days"],
            index=1,
            help="How far back to search"
        )

    # Search button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        search_clicked = st.button("🔍 Search Logs", use_container_width=True, type="primary")
    with col2:
        clear_clicked = st.button("🗑️ Clear", use_container_width=True)

    st.markdown("---")

    # Check if Kibana endpoint is configured
    # Show a note about configuration
    st.info(
        "💡 **Note:** Log querying requires Kibana/Elasticsearch integration. "
        "Ensure `KIBANA_LOGS_ENDPOINT` and `KIBANA_API_KEY` are configured in your environment."
    )

    # Results area
    if search_clicked:
        st.markdown("### 📄 Log Results")

        with st.spinner("Querying logs..."):
            try:
                logs = fetch_logs(
                    client,
                    selected_endpoint if selected_endpoint != "All" else "",
                    container_filter,
                    search_text,
                    time_window
                )

                if logs:
                    # Convert to DataFrame
                    df_logs = pd.DataFrame(logs)

                    # Show summary
                    st.success(f"Found {len(logs)} log entries")

                    # Display columns if available
                    display_cols = ["timestamp", "hostname", "container_name", "message", "level"]
                    available_cols = [c for c in display_cols if c in df_logs.columns]

                    if available_cols:
                        display_df = df_logs[available_cols].copy()

                        # Format timestamp if present
                        if "timestamp" in display_df.columns:
                            display_df["timestamp"] = pd.to_datetime(
                                display_df["timestamp"], errors="coerce"
                            ).dt.strftime("%Y-%m-%d %H:%M:%S")

                        display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]
                        st.dataframe(display_df, use_container_width=True, hide_index=True, height=500)
                    else:
                        st.dataframe(df_logs, use_container_width=True, hide_index=True, height=500)

                    # Export
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
                        "To enable log querying:\n\n"
                        "1. Set `KIBANA_LOGS_ENDPOINT` to your Elasticsearch/Kibana URL\n"
                        "2. Set `KIBANA_API_KEY` for authentication\n"
                        "3. Restart the backend service"
                    )
                else:
                    st.error(f"Error querying logs: {e}")

    elif clear_clicked:
        st.rerun()

    else:
        # Show placeholder when no search performed
        st.markdown("### 📄 Log Results")
        st.caption("Click 'Search Logs' to query log entries from your edge agents")

        # Show example queries
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
