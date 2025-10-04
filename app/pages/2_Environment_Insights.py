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
    from app.ui_helpers import (  # type: ignore[import-not-found]
        ExportableDataFrame,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )
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
    from ui_helpers import (  # type: ignore[no-redef]
        ExportableDataFrame,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )

render_page_header(
    "Environment insights",
    icon="🧪",
    description="Dive deeper into stack coverage, container load and lifecycle trends.",
)

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
    render_kpi_row(
        [
            ("Edge agents", int(endpoint_overview["endpoint_id"].nunique()), None),
            (
                "Stacks",
                int(stack_filtered.dropna(subset=["stack_id"])["stack_id"].nunique()),
                None,
            ),
            (
                "Running containers",
                int(containers_filtered["container_id"].nunique()),
                None,
            ),
            (
                "Active images",
                int(containers_filtered["image"].dropna().nunique()),
                None,
            ),
        ]
    )

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
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download endpoint overview",
        data=endpoint_overview,
        filename="portainer_endpoints.csv",
    ).render_download_button()

    combined_load = stack_counts.merge(
        containers_filtered.groupby(
            ["environment_name", "endpoint_name"], dropna=False
        )
        .agg(container_count=("container_id", "nunique"))
        .reset_index(),
        on=["environment_name", "endpoint_name"],
        how="outer",
    ).fillna({"stack_count": 0, "container_count": 0})
    if not combined_load.empty:
        load_scatter = px.scatter(
            combined_load,
            x="stack_count",
            y="container_count",
            size="container_count",
            color="environment_name",
            hover_name="endpoint_name",
            labels={
                "stack_count": "Stacks",
                "container_count": "Containers",
                "environment_name": "Environment",
            },
            title="Stack coverage vs. container load",
        )
        load_scatter.update_traces(
            hovertemplate="%{hovertext}<br>Stacks: %{x}<br>Containers: %{y}"
        )
        st.plotly_chart(
            style_plotly_figure(load_scatter), use_container_width=True
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
    st.plotly_chart(
        style_plotly_figure(density_chart), use_container_width=True
    )

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
        image_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
        st.plotly_chart(
            style_plotly_figure(image_chart), use_container_width=True
        )
        ExportableDataFrame(
            "⬇️ Download top images",
            data=top_images,
            filename="portainer_top_images.csv",
        ).render_download_button()

    ExportableDataFrame(
        "⬇️ Download container summary",
        data=container_summary,
        filename="portainer_container_summary.csv",
    ).render_download_button()

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
        median_age = age_frame["age_days"].median()
        newest_age = age_frame["age_days"].min()
        render_kpi_row(
            [
                (
                    "Median container age",
                    round(float(median_age), 1),
                    "Days since creation",
                ),
                (
                    "Most recent container",
                    round(float(newest_age), 1),
                    "Days old",
                ),
            ]
        )
        age_chart = px.histogram(
            age_frame,
            x="age_days",
            color="environment_name",
            nbins=20,
            title="Container age distribution",
            labels={"age_days": "Age (days)", "count": "Containers"},
            color_discrete_sequence=px.colors.sequential.Agsunset,
        )
        age_chart.update_traces(hovertemplate="Age: %{x:.1f} days<br>Containers: %{y}")
        st.plotly_chart(
            style_plotly_figure(age_chart), use_container_width=True
        )
else:
    st.info("No container data available for the selected filters.")

