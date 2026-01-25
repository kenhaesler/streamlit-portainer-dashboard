"""Settings - Configuration and backup management."""

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
    st.markdown("Manage your dashboard configuration and backups")

    client = get_api_client()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["🔌 Connection Status", "💾 Backups", "ℹ️ About"])

    with tab1:
        st.markdown("### Portainer Connection")

        # Test connection
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🔄 Test Connection", use_container_width=True):
                with st.spinner("Testing connection..."):
                    try:
                        endpoints = client.get_endpoints()
                        if endpoints is not None:
                            st.success(f"✅ Connected! Found {len(endpoints)} endpoint(s)")
                        else:
                            st.error("❌ Connection failed - no response")
                    except Exception as e:
                        st.error(f"❌ Connection failed: {e}")

        # Show current status
        st.markdown("#### Current Status")

        try:
            endpoints = client.get_endpoints()
            containers = client.get_containers()

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Endpoints", len(endpoints) if endpoints else 0)
            with col2:
                st.metric("Containers", len(containers) if containers else 0)
            with col3:
                running = len([c for c in containers if c.get("state") == "running"]) if containers else 0
                st.metric("Running", running)

        except Exception as e:
            st.error(f"Could not fetch status: {e}")

        st.markdown("---")

        st.markdown("#### Environment Variables")
        st.caption("These are configured via environment variables in the deployment")

        env_vars = [
            ("PORTAINER_API_URL", "Portainer API endpoint URL"),
            ("PORTAINER_API_KEY", "Portainer API authentication key"),
            ("PORTAINER_VERIFY_SSL", "SSL certificate verification"),
            ("LLM_API_ENDPOINT", "LLM API endpoint for assistant"),
            ("LLM_MODEL", "LLM model name"),
            ("KIBANA_LOGS_ENDPOINT", "Kibana logs endpoint"),
        ]

        env_df = pd.DataFrame(env_vars, columns=["Variable", "Description"])
        st.dataframe(env_df, use_container_width=True, hide_index=True)

    with tab2:
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
            st.markdown("")  # Spacer
            st.markdown("")  # Spacer
            if st.button("📦 Create Backup", use_container_width=True):
                with st.spinner("Creating backup..."):
                    try:
                        result = client.trigger_backup()
                        if result and result.get("status") == "success":
                            st.success(f"✅ Backup created: {result.get('filename', 'backup.tar.gz')}")
                        elif result:
                            st.warning(f"Backup result: {result}")
                        else:
                            st.error("Backup creation failed - no response")
                    except Exception as e:
                        st.error(f"Backup failed: {e}")

        st.markdown("---")

        # Backup list
        st.markdown("#### Backup History")

        # Note: The backup list API may not be exposed yet
        st.info(
            "💡 Backups are stored on the server. "
            "Contact your administrator to download or restore backups."
        )

        # Placeholder for backup list when API is available
        if st.button("🔄 Refresh Backup List"):
            st.info("Backup listing requires additional API implementation")

    with tab3:
        st.markdown("### About Portainer Dashboard")

        st.markdown("""
        **Portainer Dashboard** is a hybrid FastAPI + Streamlit application for managing
        and monitoring your Portainer infrastructure.

        #### Features
        - 📊 **Fleet Overview** - Monitor edge agents and stacks
        - 🐳 **Workload Explorer** - Inspect container distribution
        - 💚 **Container Health** - Track container health status
        - 📦 **Image Footprint** - Analyze image usage
        - 🤖 **LLM Assistant** - AI-powered infrastructure analysis
        - 📋 **Edge Agent Logs** - Query logs via Kibana

        #### Architecture
        - **Backend**: FastAPI with async Portainer client
        - **Frontend**: Streamlit with Plotly visualizations
        - **LLM**: WebSocket streaming to Ollama/OpenAI-compatible endpoints

        #### Version
        - Dashboard: 2.0.0 (Hybrid Architecture)
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
