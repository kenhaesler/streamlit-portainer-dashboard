"""Environment insights dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.dashboard_state import (  # type: ignore[import-not-found]
        ConfigurationError,
        NoEnvironmentsConfiguredError,
        apply_selected_environment,
        fetch_portainer_data,
        initialise_session_state,
        load_configured_environment_settings,
        render_sidebar_filters,
    )
    from app.portainer_client import PortainerAPIError  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from dashboard_state import (  # type: ignore[no-redef]
        ConfigurationError,
        NoEnvironmentsConfiguredError,
        apply_selected_environment,
        fetch_portainer_data,
        initialise_session_state,
        load_configured_environment_settings,
        render_sidebar_filters,
    )
    from portainer_client import PortainerAPIError  # type: ignore[no-redef]


st.title("Environment insights")

initialise_session_state()
apply_selected_environment()

try:
    configured_environments = load_configured_environment_settings()
except ConfigurationError as exc:
    st.error(str(exc))
    st.stop()
except NoEnvironmentsConfiguredError:
    st.warning(
        "No Portainer environments configured. Visit the Settings page to add one.",
        icon="ℹ️",
    )
    st.stop()

try:
    stack_data, container_data, warnings = fetch_portainer_data(configured_environments)
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

for warning in warnings:
    st.warning(warning, icon="⚠️")

if stack_data.empty and container_data.empty:
    st.info("No data was returned by the Portainer API for the configured account.")
    st.stop()

filters = render_sidebar_filters(stack_data, container_data)

stack_filtered = filters.stack_data
containers_filtered = filters.container_data

st.subheader("Environment health at a glance")

endpoint_overview = (
    stack_filtered[
        [
            "environment_name",
            "endpoint_id",
            "endpoint_name",
            "endpoint_status",
            "stack_id",
        ]
    ]
    .drop_duplicates()
    .rename(columns={"stack_id": "stack_count"})
)

if not endpoint_overview.empty:
    stack_counts = (
        stack_filtered.groupby(["environment_name", "endpoint_name"])  # type: ignore[arg-type]
        .agg(stack_count=("stack_id", "nunique"))
        .reset_index()
    )
    endpoint_overview = endpoint_overview.drop(columns=["stack_count"], errors="ignore")
    endpoint_overview = endpoint_overview.merge(
        stack_counts,
        on=["environment_name", "endpoint_name"],
        how="left",
    )

    st.dataframe(
        endpoint_overview.sort_values(
            ["environment_name", "endpoint_name"], na_position="last"
        ).reset_index(drop=True),
        use_container_width=True,
    )
else:
    st.info("No stack information available for the selected filters.")

container_summary = (
    containers_filtered.groupby(["environment_name", "endpoint_name"], dropna=False)
    .agg(container_count=("container_id", "nunique"))
    .reset_index()
)

if not container_summary.empty:
    density_chart = px.bar(
        container_summary,
        x="container_count",
        y="endpoint_name",
        orientation="h",
        title="Running containers per endpoint",
        color="environment_name",
        labels={
            "endpoint_name": "Endpoint",
            "container_count": "Containers",
            "environment_name": "Environment",
        },
    )
    density_chart.update_layout(yaxis_title="Endpoint", xaxis_title="Containers")
    st.plotly_chart(density_chart, use_container_width=True)

    top_images = (
        containers_filtered.groupby(["environment_name", "image"], dropna=False)
        .agg(count=("container_id", "nunique"))
        .reset_index()
        .sort_values("count", ascending=False)
        .head(10)
    )
    if not top_images.empty:
        image_chart = px.bar(
            top_images,
            x="count",
            y="image",
            orientation="h",
            title="Top running images",
            color="environment_name",
            labels={
                "count": "Containers",
                "image": "Image",
                "environment_name": "Environment",
            },
        )
        image_chart.update_layout(yaxis_title="Image", xaxis_title="Containers")
        st.plotly_chart(image_chart, use_container_width=True)

    created_series = pd.to_datetime(
        containers_filtered.get("created_at"), errors="coerce", utc=True
    )
    age_days = (pd.Timestamp.utcnow() - created_series).dt.total_seconds() / 86400
    if age_days.notna().any():
        age_frame = pd.DataFrame(
            {
                "environment_name": containers_filtered["environment_name"],
                "age_days": age_days,
            }
        ).dropna(subset=["age_days"])
        age_chart = px.histogram(
            age_frame,
            x="age_days",
            color="environment_name",
            nbins=20,
            title="Container age distribution",
            labels={"age_days": "Age (days)", "count": "Containers"},
            color_discrete_sequence=px.colors.sequential.Agsunset,
        )
        st.plotly_chart(age_chart, use_container_width=True)
else:
    st.info("No container data available for the selected filters.")

