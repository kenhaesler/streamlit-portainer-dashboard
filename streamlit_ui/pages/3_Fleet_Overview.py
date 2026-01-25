"""Fleet Overview - Endpoint and stack management with visual analytics."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Fleet Overview - Portainer Dashboard",
    page_icon="🚀",
    layout="wide",
)


def main():
    """Fleet overview page."""
    require_auth()
    render_sidebar()

    st.title("🚀 Fleet Overview")
    st.markdown("Monitor your edge agents, stacks, and container distribution")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading fleet data..."):
        endpoints = client.get_endpoints()
        stacks = client.get_stacks()
        containers = client.get_containers(include_stopped=True)

    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()
    df_stacks = pd.DataFrame(stacks) if stacks else pd.DataFrame()
    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()

    # KPIs
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        total = len(df_endpoints)
        st.metric("Edge Agents", total)

    with col2:
        online = len(df_endpoints[df_endpoints["endpoint_status"] == 1]) if not df_endpoints.empty and "endpoint_status" in df_endpoints.columns else 0
        st.metric("Online", online, delta=f"{online}/{total}" if total > 0 else None)

    with col3:
        unique_stacks = df_stacks["stack_name"].nunique() if not df_stacks.empty and "stack_name" in df_stacks.columns else 0
        st.metric("Unique Stacks", unique_stacks)

    with col4:
        running = len(df_containers[df_containers["state"] == "running"]) if not df_containers.empty and "state" in df_containers.columns else 0
        st.metric("Running Containers", running)

    with col5:
        unique_images = df_containers["image"].nunique() if not df_containers.empty and "image" in df_containers.columns else 0
        st.metric("Active Images", unique_images)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📊 Visual Insights", "📡 Endpoints", "📚 Stacks"])

    with tab1:
        # Visual Insights Tab
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Edge Agent Health")
            if not df_endpoints.empty and "endpoint_status" in df_endpoints.columns:
                status_counts = df_endpoints["endpoint_status"].map({1: "Online", 2: "Offline"}).fillna("Unknown").value_counts()

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
                    legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center"),
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=300,
                    annotations=[dict(text=f"{len(df_endpoints)}<br>Total", x=0.5, y=0.5, font_size=14, showarrow=False)]
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No endpoint data")

        with col2:
            st.markdown("#### Running Containers per Agent")
            if not df_containers.empty and "endpoint_name" in df_containers.columns and "state" in df_containers.columns:
                running_df = df_containers[df_containers["state"] == "running"]
                container_counts = running_df.groupby("endpoint_name").size().sort_values(ascending=True).tail(15)

                fig = px.bar(
                    y=container_counts.index,
                    x=container_counts.values,
                    orientation='h',
                    color=container_counts.values,
                    color_continuous_scale="Viridis",
                )
                fig.update_layout(
                    showlegend=False,
                    xaxis_title="Containers",
                    yaxis_title="",
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=300,
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No container data")

        # Second row of charts
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Stacks per Agent")
            if not df_stacks.empty and "endpoint_name" in df_stacks.columns and "stack_name" in df_stacks.columns:
                stack_counts = df_stacks.groupby("endpoint_name")["stack_name"].nunique().sort_values(ascending=True).tail(15)

                fig = px.bar(
                    y=stack_counts.index,
                    x=stack_counts.values,
                    orientation='h',
                    color=stack_counts.values,
                    color_continuous_scale="Blues",
                )
                fig.update_layout(
                    showlegend=False,
                    xaxis_title="Stacks",
                    yaxis_title="",
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=300,
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No stack data")

        with col2:
            st.markdown("#### Top Running Images")
            if not df_containers.empty and "image" in df_containers.columns and "state" in df_containers.columns:
                running_df = df_containers[df_containers["state"] == "running"]
                image_counts = running_df["image"].value_counts().head(10)

                # Shorten image names for display
                display_names = [img.split("/")[-1][:40] for img in image_counts.index]

                fig = px.bar(
                    y=display_names,
                    x=image_counts.values,
                    orientation='h',
                    color=image_counts.values,
                    color_continuous_scale="Oranges",
                )
                fig.update_layout(
                    showlegend=False,
                    xaxis_title="Containers",
                    yaxis_title="",
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=300,
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No image data")

        # Container Footprint Treemap
        st.markdown("#### Container Footprint by Agent and Image")
        if not df_containers.empty and all(col in df_containers.columns for col in ["endpoint_name", "image", "state"]):
            running_df = df_containers[df_containers["state"] == "running"].copy()
            if not running_df.empty:
                # Shorten image names
                running_df["image_short"] = running_df["image"].apply(lambda x: x.split("/")[-1][:30] if x else "unknown")

                treemap_df = running_df.groupby(["endpoint_name", "image_short"]).size().reset_index(name="count")

                fig = px.treemap(
                    treemap_df,
                    path=["endpoint_name", "image_short"],
                    values="count",
                    color="count",
                    color_continuous_scale="Tealgrn",
                )
                fig.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=400,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No running containers")
        else:
            st.info("Insufficient data for treemap")

        # Container Age Distribution
        st.markdown("#### Container Age Distribution")
        if not df_containers.empty and "created_at" in df_containers.columns:
            # Calculate age in days
            now = datetime.now(timezone.utc)
            df_age = df_containers.copy()
            df_age["created_at"] = pd.to_datetime(df_age["created_at"], errors="coerce", utc=True)
            df_age["age_days"] = (now - df_age["created_at"]).dt.total_seconds() / 86400
            df_age = df_age.dropna(subset=["age_days"])

            if not df_age.empty:
                fig = px.histogram(
                    df_age,
                    x="age_days",
                    nbins=20,
                    color_discrete_sequence=["#6366F1"],
                )
                fig.update_layout(
                    xaxis_title="Age (days)",
                    yaxis_title="Container Count",
                    margin=dict(t=20, b=50, l=50, r=20),
                    height=300,
                    bargap=0.1,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Age stats
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Median Age", f"{df_age['age_days'].median():.1f} days")
                with col2:
                    st.metric("Oldest Container", f"{df_age['age_days'].max():.1f} days")
                with col3:
                    st.metric("Newest Container", f"{df_age['age_days'].min():.1f} days")
            else:
                st.info("No container age data available")
        else:
            st.info("No container creation data")

    with tab2:
        st.markdown("### Edge Agents")

        if not df_endpoints.empty:
            # Search filter
            search = st.text_input("Search endpoints", placeholder="Filter by name...")

            filtered_df = df_endpoints.copy()
            if search:
                filtered_df = filtered_df[
                    filtered_df["endpoint_name"].str.contains(search, case=False, na=False)
                ]

            # Prepare display
            display_cols = ["endpoint_name", "endpoint_status", "agent_version", "platform", "operating_system", "last_check_in"]
            available_cols = [c for c in display_cols if c in filtered_df.columns]

            display_df = filtered_df[available_cols].copy()

            # Format status
            if "endpoint_status" in display_df.columns:
                display_df["endpoint_status"] = display_df["endpoint_status"].map({1: "🟢 Online", 2: "🔴 Offline"}).fillna("⚪ Unknown")

            # Rename columns
            display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]

            st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

            # Export
            csv = df_endpoints.to_csv(index=False)
            st.download_button("📥 Download Endpoints CSV", csv, "endpoints.csv", "text/csv")
        else:
            st.info("No endpoints found")

    with tab3:
        st.markdown("### Stacks")

        if not df_stacks.empty:
            # Filter out rows without stack names
            stacks_df = df_stacks[df_stacks["stack_name"].notna()].copy()

            if not stacks_df.empty:
                display_cols = ["endpoint_name", "stack_name", "stack_status", "stack_type"]
                available_cols = [c for c in display_cols if c in stacks_df.columns]

                display_df = stacks_df[available_cols].drop_duplicates()
                display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]

                st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

                csv = stacks_df.to_csv(index=False)
                st.download_button("📥 Download Stacks CSV", csv, "stacks.csv", "text/csv")
            else:
                st.info("No stacks deployed")
        else:
            st.info("No stack data available")


if __name__ == "__main__":
    main()
