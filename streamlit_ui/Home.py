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
    """Check authentication and show login if needed."""
    client = get_api_client()

    if not client.is_authenticated():
        st.title("🐳 Portainer Dashboard")
        st.markdown("---")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.subheader("Login")
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Login", use_container_width=True)

                if submitted:
                    if client.login(username, password):
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
            st.cache_data.clear()
            st.rerun()

    st.markdown("Infrastructure overview and monitoring")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading data from Portainer..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)

    if not endpoints:
        st.warning("No endpoints found. Check your Portainer configuration.")
        st.stop()

    # Convert to DataFrames
    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()
    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()

    # KPI Metrics
    st.markdown("### 📊 Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_endpoints = len(df_endpoints)
        online_endpoints = len(df_endpoints[df_endpoints.get("endpoint_status", pd.Series()) == 1]) if not df_endpoints.empty else 0
        st.metric(
            "Endpoints",
            total_endpoints,
            f"{online_endpoints} online",
            delta_color="normal"
        )

    with col2:
        total_containers = len(df_containers)
        running_containers = len(df_containers[df_containers.get("state", pd.Series()) == "running"]) if not df_containers.empty else 0
        st.metric(
            "Containers",
            total_containers,
            f"{running_containers} running"
        )

    with col3:
        unique_images = df_containers["image"].nunique() if not df_containers.empty and "image" in df_containers.columns else 0
        st.metric("Unique Images", unique_images)

    with col4:
        stopped = total_containers - running_containers
        st.metric(
            "Stopped Containers",
            stopped,
            delta=-stopped if stopped > 0 else None,
            delta_color="inverse"
        )

    st.markdown("---")

    # Charts
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🟢 Endpoint Status")
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
                height=300,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No endpoint data available")

    with col2:
        st.markdown("### 📦 Container States")
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
                height=300,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No container data available")

    st.markdown("---")

    # Recent containers table
    st.markdown("### 🐳 Recent Containers")
    if not df_containers.empty:
        display_cols = ["endpoint_name", "container_name", "image", "state", "status"]
        available_cols = [c for c in display_cols if c in df_containers.columns]

        if available_cols:
            display_df = df_containers[available_cols].head(10).copy()
            display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_containers.head(10), use_container_width=True, hide_index=True)

        # CSV Export - Summary data
        summary_data = {
            "Metric": ["Total Endpoints", "Online Endpoints", "Total Containers", "Running Containers", "Stopped Containers", "Unique Images"],
            "Value": [total_endpoints, online_endpoints, total_containers, running_containers, stopped, unique_images],
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
    else:
        st.info("No containers found")


if __name__ == "__main__":
    main()
