"""Streamlit Dashboard Home - connects to FastAPI backend."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import get_api_client
from shared import render_sidebar as shared_sidebar, render_session_expiry_banner

st.set_page_config(
    page_title="Portainer Dashboard",
    page_icon="🐳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS that works in both light and dark mode
st.markdown("""
<style>
    [data-testid="stMetric"] {
        background-color: rgba(28, 131, 225, 0.1);
        border: 1px solid rgba(28, 131, 225, 0.2);
        padding: 15px;
        border-radius: 10px;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.9rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
</style>
""", unsafe_allow_html=True)


def require_auth():
    """Check authentication and show login if needed.

    This function first checks if the user is already authenticated via session state.
    If not, it attempts to restore the session from the browser cookie (persisted
    across browser refreshes). Only if both checks fail, the login form is displayed.
    """
    client = get_api_client()

    # Fast path: already authenticated in this session
    if client.is_authenticated():
        return

    # Try to restore session from browser cookie (survives F5 refresh)
    if client.try_restore_session():
        return

    # No valid session - show login form
    st.title("🐳 Portainer Dashboard")
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("Login")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            remember_me = st.checkbox("Keep me logged in", value=True)
            submitted = st.form_submit_button("Login", use_container_width=True)

            if submitted:
                if client.login(username, password, remember_me=remember_me):
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid credentials")

    st.stop()


def render_sidebar():
    """Render sidebar with user info and logout."""
    shared_sidebar()


def main():
    """Main dashboard page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("🐳 Portainer Dashboard")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_home"):
            # Clear Streamlit's data cache to force fresh data
            st.cache_data.clear()
            st.rerun()

    # Check if we should force refresh (bypass cache)
    force_refresh = st.session_state.get("_force_refresh", False)
    if force_refresh:
        st.session_state["_force_refresh"] = False

    st.markdown("Infrastructure overview and quick navigation")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading data from Portainer..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)
        stacks = client.get_stacks()

    if not endpoints:
        st.warning("No endpoints found. Check your Portainer configuration.")
        st.stop()

    # Convert to DataFrames
    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()
    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()
    df_stacks = pd.DataFrame(stacks) if stacks else pd.DataFrame()

    # Calculate metrics
    total_endpoints = len(df_endpoints)
    online_endpoints = len(df_endpoints[df_endpoints.get("endpoint_status", pd.Series()) == 1]) if not df_endpoints.empty else 0
    total_containers = len(df_containers)
    running_containers = len(df_containers[df_containers.get("state", pd.Series()) == "running"]) if not df_containers.empty else 0
    unique_stacks = df_stacks["stack_name"].nunique() if not df_stacks.empty and "stack_name" in df_stacks.columns else 0
    unique_images = df_containers["image"].nunique() if not df_containers.empty and "image" in df_containers.columns else 0

    # Quick Navigation Cards
    st.markdown("### Quick Navigation")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; color: white;">
            <h3 style="margin: 0; color: white;">🚀 Fleet & Stacks</h3>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Edge agents and deployments</p>
        </div>
        """, unsafe_allow_html=True)
        st.metric("Stacks", unique_stacks)
        st.metric("Edge Agents", total_endpoints, f"{online_endpoints} online")

    with col2:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); padding: 20px; border-radius: 10px; color: white;">
            <h3 style="margin: 0; color: white;">🐳 Containers</h3>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Health and management</p>
        </div>
        """, unsafe_allow_html=True)
        st.metric("Total", total_containers)
        st.metric("Running", running_containers)

    with col3:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 20px; border-radius: 10px; color: white;">
            <h3 style="margin: 0; color: white;">📋 Logs</h3>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Live and searchable</p>
        </div>
        """, unsafe_allow_html=True)
        st.metric("Images", unique_images)

    with col4:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); padding: 20px; border-radius: 10px; color: white;">
            <h3 style="margin: 0; color: white;">🤖 AI Operations</h3>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Insights and self-healing</p>
        </div>
        """, unsafe_allow_html=True)
        # Check for alerts
        offline = total_endpoints - online_endpoints
        stopped = total_containers - running_containers
        if offline > 0:
            st.error(f"{offline} offline endpoint(s)")
        elif stopped > 5:
            st.warning(f"{stopped} stopped containers")
        else:
            st.success("Systems healthy")

    st.markdown("---")

    # Status Overview
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Endpoint Status")
        if not df_endpoints.empty and "endpoint_status" in df_endpoints.columns:
            status_counts = df_endpoints["endpoint_status"].map(
                {1: "Online", 2: "Offline"}
            ).fillna("Unknown").value_counts()

            fig = px.pie(
                values=status_counts.values,
                names=status_counts.index,
                color=status_counts.index,
                color_discrete_map={"Online": "#10B981", "Offline": "#EF4444", "Unknown": "#6B7280"},
                hole=0.4,
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            fig.update_layout(
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, x=0.5, xanchor="center"),
                margin=dict(t=20, b=20, l=20, r=20),
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No endpoint data available")

    with col2:
        st.markdown("### Container States")
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
                margin=dict(t=20, b=20, l=20, r=20),
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No container data available")

    # Summary export
    st.markdown("---")
    summary_data = {
        "Metric": ["Total Endpoints", "Online Endpoints", "Total Containers", "Running Containers", "Deployed Stacks", "Unique Images"],
        "Value": [total_endpoints, online_endpoints, total_containers, running_containers, unique_stacks, unique_images],
    }
    summary_df = pd.DataFrame(summary_data)
    csv = summary_df.to_csv(index=False)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        "📥 Download Summary CSV",
        csv,
        f"dashboard_summary_{timestamp_str}.csv",
        "text/csv",
        use_container_width=False,
    )


if __name__ == "__main__":
    main()
