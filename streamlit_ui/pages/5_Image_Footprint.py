"""Image Footprint - Analyze container image distribution and usage."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth, render_sidebar


st.set_page_config(
    page_title="Image Footprint - Portainer Dashboard",
    page_icon="📦",
    layout="wide",
)


def main():
    """Image footprint page."""
    require_auth()
    render_sidebar()

    st.title("📦 Image Footprint")
    st.markdown("Analyze container image distribution across your infrastructure")

    client = get_api_client()

    # Fetch data
    with st.spinner("Loading image data..."):
        containers = client.get_containers(include_stopped=True)
        endpoints = client.get_endpoints()

    df_containers = pd.DataFrame(containers) if containers else pd.DataFrame()
    df_endpoints = pd.DataFrame(endpoints) if endpoints else pd.DataFrame()

    if df_containers.empty:
        st.info("No containers found")
        st.stop()

    # Filter to running containers for most analyses
    running_df = df_containers[df_containers["state"] == "running"] if "state" in df_containers.columns else df_containers

    # KPIs
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        unique_images = running_df["image"].nunique() if "image" in running_df.columns else 0
        st.metric("Unique Running Images", unique_images)

    with col2:
        total_running = len(running_df)
        avg_per_image = total_running / unique_images if unique_images > 0 else 0
        st.metric("Avg Containers/Image", f"{avg_per_image:.1f}")

    with col3:
        num_endpoints = running_df["endpoint_id"].nunique() if "endpoint_id" in running_df.columns else 0
        st.metric("Endpoints with Containers", num_endpoints)

    with col4:
        total_containers = len(df_containers)
        st.metric("Total Containers", total_containers)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📊 Image Analytics", "🗺️ Distribution Map", "📋 Image Details"])

    with tab1:
        # Top Images Chart
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Top Images by Running Containers")
            if "image" in running_df.columns:
                image_counts = running_df["image"].value_counts().head(15)

                # Shorten image names for display
                display_data = pd.DataFrame({
                    "image": [img.split("/")[-1][:40] for img in image_counts.index],
                    "full_image": image_counts.index,
                    "count": image_counts.values
                })

                fig = px.bar(
                    display_data,
                    y="image",
                    x="count",
                    orientation='h',
                    color="count",
                    color_continuous_scale="Viridis",
                    hover_data={"full_image": True, "image": False},
                )
                fig.update_layout(
                    showlegend=False,
                    xaxis_title="Container Count",
                    yaxis_title="",
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=400,
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No image data")

        with col2:
            st.markdown("#### Image Distribution Across Agents")
            if "image" in running_df.columns and "endpoint_name" in running_df.columns:
                # Count how many endpoints use each image
                image_endpoint_counts = running_df.groupby("image")["endpoint_name"].nunique().sort_values(ascending=False).head(15)

                display_data = pd.DataFrame({
                    "image": [img.split("/")[-1][:40] for img in image_endpoint_counts.index],
                    "endpoints": image_endpoint_counts.values
                })

                fig = px.bar(
                    display_data,
                    y="image",
                    x="endpoints",
                    orientation='h',
                    color="endpoints",
                    color_continuous_scale="Blues",
                )
                fig.update_layout(
                    showlegend=False,
                    xaxis_title="Number of Agents",
                    yaxis_title="",
                    margin=dict(t=20, b=50, l=20, r=20),
                    height=400,
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No distribution data")

        # Container state by image
        st.markdown("#### Container States by Image")
        if "image" in df_containers.columns and "state" in df_containers.columns:
            # Get top 10 images by total container count
            top_images = df_containers["image"].value_counts().head(10).index.tolist()
            filtered_df = df_containers[df_containers["image"].isin(top_images)]

            state_counts = filtered_df.groupby(["image", "state"]).size().reset_index(name="count")
            state_counts["image_short"] = state_counts["image"].apply(lambda x: x.split("/")[-1][:30])

            state_colors = {
                "running": "#10B981",
                "exited": "#6B7280",
                "paused": "#F59E0B",
                "restarting": "#3B82F6",
                "created": "#8B5CF6",
                "dead": "#EF4444",
            }

            fig = px.bar(
                state_counts,
                x="image_short",
                y="count",
                color="state",
                color_discrete_map=state_colors,
                barmode="stack",
            )
            fig.update_layout(
                xaxis_title="Image",
                yaxis_title="Containers",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                margin=dict(t=50, b=100, l=50, r=20),
                height=350,
                xaxis_tickangle=-45,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No state data available")

    with tab2:
        st.markdown("#### Image Distribution Treemap")
        st.caption("Visualization of images across agents - size represents container count")

        if all(col in running_df.columns for col in ["endpoint_name", "image"]):
            # Shorten image names
            treemap_df = running_df.copy()
            treemap_df["image_short"] = treemap_df["image"].apply(lambda x: x.split("/")[-1][:25] if x else "unknown")

            agg_df = treemap_df.groupby(["endpoint_name", "image_short"]).size().reset_index(name="count")

            if not agg_df.empty:
                fig = px.treemap(
                    agg_df,
                    path=["endpoint_name", "image_short"],
                    values="count",
                    color="count",
                    color_continuous_scale="Tealgrn",
                )
                fig.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=500,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for treemap")
        else:
            st.info("Insufficient data for distribution map")

        # Sunburst chart as alternative view
        st.markdown("#### Sunburst View")
        if all(col in running_df.columns for col in ["endpoint_name", "image"]):
            treemap_df = running_df.copy()
            treemap_df["image_short"] = treemap_df["image"].apply(lambda x: x.split("/")[-1][:20] if x else "unknown")

            agg_df = treemap_df.groupby(["endpoint_name", "image_short"]).size().reset_index(name="count")

            if not agg_df.empty:
                fig = px.sunburst(
                    agg_df,
                    path=["endpoint_name", "image_short"],
                    values="count",
                    color="count",
                    color_continuous_scale="Tealgrn",
                )
                fig.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=500,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for sunburst")
        else:
            st.info("Insufficient data for sunburst view")

    with tab3:
        st.markdown("#### Image Summary")

        # Filters
        col1, col2 = st.columns(2)
        with col1:
            search = st.text_input("Search images", placeholder="Filter by image name...")
        with col2:
            show_all = st.checkbox("Include stopped containers", value=False)

        # Use appropriate dataframe
        work_df = df_containers if show_all else running_df

        if "image" in work_df.columns:
            # Build summary table
            summary_data = []

            for image in work_df["image"].unique():
                image_df = work_df[work_df["image"] == image]
                running_count = len(image_df[image_df["state"] == "running"]) if "state" in image_df.columns else len(image_df)
                total_count = len(image_df)
                endpoints_count = image_df["endpoint_name"].nunique() if "endpoint_name" in image_df.columns else 0

                summary_data.append({
                    "image": image,
                    "image_short": image.split("/")[-1][:50] if image else "unknown",
                    "running": running_count,
                    "total": total_count,
                    "endpoints": endpoints_count,
                })

            summary_df = pd.DataFrame(summary_data)
            summary_df = summary_df.sort_values("running", ascending=False)

            # Apply search filter
            if search:
                summary_df = summary_df[summary_df["image"].str.contains(search, case=False, na=False)]

            # Display
            display_df = summary_df[["image_short", "running", "total", "endpoints"]].copy()
            display_df.columns = ["Image", "Running", "Total", "Endpoints"]

            st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

            # Export
            export_df = summary_df[["image", "running", "total", "endpoints"]].copy()
            export_df.columns = ["Image", "Running Containers", "Total Containers", "Endpoints"]
            csv = export_df.to_csv(index=False)
            st.download_button("📥 Download Image Summary CSV", csv, "image_summary.csv", "text/csv")
        else:
            st.info("No image data available")


if __name__ == "__main__":
    main()
