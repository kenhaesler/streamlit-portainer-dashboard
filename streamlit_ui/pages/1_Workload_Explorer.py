"""Workload Explorer - Container distribution across endpoints."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Workload Explorer - Portainer Dashboard",
    page_icon="🐳",
    layout="wide",
)


def main():
    """Workload explorer page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("🐳 Workload Explorer")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_workload"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("Inspect container distribution across endpoints")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading workload data..."):
        endpoints = client.get_endpoints()
        containers = client.get_containers(include_stopped=True)

    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()
    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()

    if df_containers.empty:
        st.info("No containers found")
        st.stop()

    # KPI Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Containers", len(df_containers))

    with col2:
        running = len(df_containers[df_containers["state"] == "running"]) if "state" in df_containers.columns else 0
        st.metric("Running", running)

    with col3:
        unique_images = df_containers["image"].nunique() if "image" in df_containers.columns else 0
        st.metric("Unique Images", unique_images)

    with col4:
        num_endpoints = df_containers["endpoint_id"].nunique() if "endpoint_id" in df_containers.columns else 0
        st.metric("Endpoints", num_endpoints)

    st.markdown("---")

    # Container Distribution Chart
    st.markdown("### 📊 Container Distribution by Endpoint")
    st.caption("Click on a bar to filter the table below")

    if "endpoint_name" in df_containers.columns and "state" in df_containers.columns:
        # Aggregate by endpoint and state
        agg_df = df_containers.groupby(["endpoint_name", "endpoint_id", "state"]).size().reset_index(name="count")

        # Pivot for stacked bar chart
        pivot_df = agg_df.pivot_table(
            index=["endpoint_name", "endpoint_id"],
            columns="state",
            values="count",
            fill_value=0
        ).reset_index()

        # Create stacked bar chart
        fig = go.Figure()

        state_colors = {
            "running": "#10B981",
            "exited": "#6B7280",
            "paused": "#F59E0B",
            "restarting": "#3B82F6",
            "created": "#8B5CF6",
            "dead": "#EF4444",
        }

        states_in_data = [col for col in pivot_df.columns if col not in ["endpoint_name", "endpoint_id"]]

        for state in states_in_data:
            fig.add_trace(go.Bar(
                name=state.capitalize(),
                x=pivot_df["endpoint_name"],
                y=pivot_df[state],
                marker_color=state_colors.get(state, "#9CA3AF"),
                customdata=pivot_df["endpoint_id"],
                hovertemplate="<b>%{x}</b><br>" + state.capitalize() + ": %{y}<extra></extra>",
            ))

        fig.update_layout(
            barmode='stack',
            xaxis_title="Endpoint",
            yaxis_title="Containers",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            margin=dict(t=50, b=50, l=50, r=50),
            height=400,
            hovermode="x unified",
        )

        # Display chart and capture click events
        selected_points = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="workload_chart")

        # Handle click selection
        selected_endpoint = None
        selected_endpoint_name = None

        if selected_points and selected_points.selection and selected_points.selection.points:
            point = selected_points.selection.points[0]
            if "x" in point:
                selected_endpoint_name = point["x"]
                # Find the endpoint_id
                match = pivot_df[pivot_df["endpoint_name"] == selected_endpoint_name]
                if not match.empty:
                    selected_endpoint = int(match.iloc[0]["endpoint_id"])
    else:
        st.warning("Missing endpoint or state data")
        selected_endpoint = None
        selected_endpoint_name = None

    st.markdown("---")

    # Filters
    st.markdown("### 🔍 Filters")

    col1, col2, col3 = st.columns(3)

    with col1:
        search_term = st.text_input("Search containers", placeholder="Container name or image...")

    with col2:
        states = ["All"] + list(df_containers["state"].unique()) if "state" in df_containers.columns else ["All"]
        selected_state = st.selectbox("State", states)

    with col3:
        endpoint_options = ["All"] + list(df_containers["endpoint_name"].dropna().unique()) if "endpoint_name" in df_containers.columns else ["All"]
        # If chart selection, use that as default
        default_idx = 0
        if selected_endpoint_name and selected_endpoint_name in endpoint_options:
            default_idx = endpoint_options.index(selected_endpoint_name)
        selected_endpoint_filter = st.selectbox("Endpoint", endpoint_options, index=default_idx)

    # Apply filters
    filtered_df = df_containers.copy()

    if search_term:
        mask = (
            filtered_df["container_name"].str.contains(search_term, case=False, na=False) |
            filtered_df["image"].str.contains(search_term, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    if selected_state != "All":
        filtered_df = filtered_df[filtered_df["state"] == selected_state]

    if selected_endpoint_filter != "All":
        filtered_df = filtered_df[filtered_df["endpoint_name"] == selected_endpoint_filter]

    # Show selection indicator
    if selected_endpoint_name and selected_endpoint_filter == selected_endpoint_name:
        st.info(f"📍 Filtered by chart selection: **{selected_endpoint_name}**")

    st.markdown("---")

    # Container Table
    st.markdown(f"### 📋 Containers ({len(filtered_df)})")

    if not filtered_df.empty:
        # Prepare display columns
        display_cols = [
            "endpoint_name",
            "container_name",
            "image",
            "state",
            "status",
            "restart_count",
            "created_at",
            "ports",
        ]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        display_df = filtered_df[available_cols].copy()

        # Format dates
        if "created_at" in display_df.columns:
            display_df["created_at"] = pd.to_datetime(display_df["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

        # Rename columns for display
        column_names = {
            "endpoint_name": "Endpoint",
            "container_name": "Container",
            "image": "Image",
            "state": "State",
            "status": "Status",
            "restart_count": "Restarts",
            "created_at": "Created",
            "ports": "Ports",
        }
        display_df = display_df.rename(columns=column_names)

        # Apply state coloring
        def highlight_state(val):
            if val == "running":
                return "background-color: #D1FAE5; color: #065F46"
            elif val == "exited":
                return "background-color: #F3F4F6; color: #374151"
            elif val == "paused":
                return "background-color: #FEF3C7; color: #92400E"
            return ""

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # Export button
        csv = filtered_df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            "containers.csv",
            "text/csv",
            use_container_width=False,
        )
    else:
        st.info("No containers match the current filters")


if __name__ == "__main__":
    main()
