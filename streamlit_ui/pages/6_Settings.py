"""Settings - Configuration, backups, and developer tools."""

from __future__ import annotations

from datetime import datetime
import pandas as pd
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Settings - Portainer Dashboard",
    page_icon="⚙️",
    layout="wide",
)


def main():
    """Settings page."""
    require_auth()
    render_sidebar()

    st.title("⚙️ Settings")
    st.markdown("Configuration, backups, and developer tools")

    client = get_api_client()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔌 Connection Status",
        "💾 Backups",
        "🔍 Tracing",
        "ℹ️ About"
    ])

    with tab1:
        render_connection_tab(client)

    with tab2:
        render_backup_tab(client)

    with tab3:
        render_tracing_tab(client)

    with tab4:
        render_about_tab()


def render_connection_tab(client):
    """Render connection status tab."""
    st.markdown("### Portainer Connection")

    # Test connection
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Test Connection", use_container_width=True):
            with st.spinner("Testing connection..."):
                try:
                    endpoints = client.get_endpoints()
                    if endpoints is not None:
                        st.success(f"Connected! Found {len(endpoints)} endpoint(s)")
                    else:
                        st.error("Connection failed - no response")
                except Exception as e:
                    st.error(f"Connection failed: {e}")

    # Show current status
    st.markdown("#### Current Status")

    try:
        endpoints = client.get_endpoints()
        containers = client.get_containers()
        stacks = client.get_stacks()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Endpoints", len(endpoints) if endpoints else 0)
        with col2:
            st.metric("Containers", len(containers) if containers else 0)
        with col3:
            running = len([c for c in containers if c.get("state") == "running"]) if containers else 0
            st.metric("Running", running)
        with col4:
            unique_stacks = len(set(s.get("stack_name") for s in stacks if s.get("stack_name"))) if stacks else 0
            st.metric("Stacks", unique_stacks)

    except Exception as e:
        st.error(f"Could not fetch status: {e}")

    st.markdown("---")

    st.markdown("#### Environment Variables")
    st.caption("Configured via environment variables in the deployment")

    env_vars = [
        ("PORTAINER_API_URL", "Portainer API endpoint URL"),
        ("PORTAINER_API_KEY", "Portainer API authentication key"),
        ("PORTAINER_VERIFY_SSL", "SSL certificate verification"),
        ("LLM_API_ENDPOINT", "LLM API endpoint for assistant"),
        ("LLM_MODEL", "LLM model name"),
        ("KIBANA_LOGS_ENDPOINT", "Kibana logs endpoint"),
        ("MONITORING_ENABLED", "Enable AI monitoring"),
        ("REMEDIATION_ENABLED", "Enable self-healing actions"),
    ]

    env_df = pd.DataFrame(env_vars, columns=["Variable", "Description"])
    st.dataframe(env_df, use_container_width=True, hide_index=True)


def render_backup_tab(client):
    """Render backup management tab."""
    st.markdown("### Backup Management")
    st.caption("Create and manage backups of your Portainer stacks")

    # Create backup
    st.markdown("#### Create Backup")

    col1, col2 = st.columns([3, 1])
    with col1:
        backup_password = st.text_input(
            "Backup Password (optional)",
            type="password",
            help="Encrypt the backup with a password"
        )
    with col2:
        st.markdown("")
        st.markdown("")
        if st.button("📦 Create Backup", use_container_width=True):
            with st.spinner("Creating backup..."):
                try:
                    result = client.trigger_backup()
                    if result and result.get("status") == "success":
                        st.success(f"Backup created: {result.get('filename', 'backup.tar.gz')}")
                    elif result:
                        st.warning(f"Backup result: {result}")
                    else:
                        st.error("Backup creation failed - no response")
                except Exception as e:
                    st.error(f"Backup failed: {e}")

    st.markdown("---")

    # Restore Instructions
    st.markdown("#### Restore Instructions")
    st.info("""
**To restore a Portainer backup:**

1. **Download the backup file** from your backup storage location
2. **Deploy a fresh Portainer instance** with an empty data volume
3. During **initial setup**, select "Restore Portainer from backup"
4. **Upload the downloaded** `.tar.gz` backup file
5. **Enter the backup password** if one was set during creation

**Important Notes:**
- Restores can **only be performed on fresh Portainer installations**
- The restore feature is only available during the initial setup wizard
- Existing Portainer instances cannot import backups directly
- For more details, see [Portainer Documentation](https://docs.portainer.io/admin/settings#backup-portainer)
    """)


def render_tracing_tab(client):
    """Render distributed tracing tab."""
    st.markdown("### Distributed Tracing")
    st.caption("View request traces and service dependencies")

    # Check tracing status
    try:
        status = client.get("/api/v1/traces/status")
    except Exception:
        status = None

    if not status or not status.get("enabled"):
        st.warning(
            "Distributed tracing is disabled. "
            "Set `TRACING_ENABLED=true` to enable."
        )
        return

    # Tracing Summary
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Traces", status.get("total_traces", 0))
    with col2:
        st.metric("Traces (Last Hour)", status.get("traces_last_hour", 0))
    with col3:
        error_rate = status.get("error_rate", 0)
        st.metric("Error Rate", f"{error_rate:.1f}%")
    with col4:
        avg_duration = status.get("avg_duration_ms", 0)
        st.metric("Avg Duration", f"{avg_duration:.0f}ms")

    st.markdown("---")

    # Trace List
    st.markdown("#### Recent Traces")

    col1, col2, col3 = st.columns(3)

    with col1:
        hours = st.selectbox("Time Range", [1, 6, 12, 24], index=0, format_func=lambda x: f"Last {x}h", key="trace_hours")

    with col2:
        method_filter = st.selectbox("HTTP Method", [None, "GET", "POST", "PUT", "DELETE"], format_func=lambda x: "All" if x is None else x, key="trace_method")

    with col3:
        error_only = st.checkbox("Errors Only", key="trace_errors")

    try:
        params = {"hours": hours, "limit": 50}
        if method_filter:
            params["method"] = method_filter
        if error_only:
            params["error_only"] = "true"

        traces = client.get("/api/v1/traces/", params=params)

        if traces:
            df_data = []
            for t in traces:
                timestamp = t.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    timestamp_str = dt.strftime("%H:%M:%S")
                except ValueError:
                    timestamp_str = timestamp

                df_data.append({
                    "Time": timestamp_str,
                    "Method": t.get("method", ""),
                    "Path": t.get("path", "")[:50],
                    "Status": t.get("status_code", ""),
                    "Duration": f"{t.get('duration_ms', 0):.0f}ms",
                    "Spans": t.get("span_count", 0),
                })

            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True, height=300)

            csv = df.to_csv(index=False)
            st.download_button("📥 Download Traces CSV", csv, "traces.csv", "text/csv")
        else:
            st.info("No traces found for the selected criteria")

    except Exception as e:
        st.error(f"Failed to load traces: {e}")


def render_about_tab():
    """Render about tab."""
    st.markdown("### About Portainer Dashboard")

    st.markdown("""
    **Portainer Dashboard** is a hybrid FastAPI + Streamlit application for managing
    and monitoring your Portainer infrastructure.

    #### Features
    - **Fleet & Stacks** - Monitor edge agents and deployed stacks
    - **Containers** - Health monitoring, image analysis, and network topology
    - **Logs** - Live container logs and searchable log history
    - **AI Operations** - AI-powered insights, metrics, and self-healing
    - **LLM Assistant** - Natural language infrastructure queries

    #### Architecture
    - **Backend**: FastAPI with async Portainer client
    - **Frontend**: Streamlit with Plotly visualizations
    - **LLM**: WebSocket streaming to Ollama/OpenAI-compatible endpoints
    - **Monitoring**: Background AI analysis with actionable insights

    #### Version
    - Dashboard: 2.1.0 (Consolidated UI)
    """)

    st.markdown("---")

    st.markdown("#### Links")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("[📚 Portainer Documentation](https://docs.portainer.io/)")
    with col2:
        st.markdown("[🐙 GitHub Repository](https://github.com/)")


if __name__ == "__main__":
    main()
