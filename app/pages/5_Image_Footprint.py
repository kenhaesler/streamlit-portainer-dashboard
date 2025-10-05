"""Image footprint dashboard."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.auth import (  # type: ignore[import-not-found]
        render_logout_button,
        require_authentication,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from auth import (  # type: ignore[no-redef]
        render_logout_button,
        require_authentication,
    )

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

require_authentication()
render_logout_button()

render_page_header(
    "Image footprint",
    icon="🖼️",
    description="Identify the images powering your workloads and where they are deployed.",
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

containers_filtered = filters.container_data

st.subheader("Running images overview")
if containers_filtered.empty:
    st.info("No running containers available to derive image statistics.")
else:
    images_summary = (
        containers_filtered.groupby(["environment_name", "image"], dropna=False)
        .agg(
            running_containers=("container_id", "nunique"),
            endpoints=("endpoint_name", "nunique"),
        )
        .reset_index()
        .rename(columns={"image": "image_name"})
        .sort_values("running_containers", ascending=False)
    )

    render_kpi_row(
        [
            ("Unique running images", int(images_summary["image_name"].nunique()), None),
            (
                "Average containers per image",
                round(
                    float(
                        images_summary["running_containers"].sum()
                        / max(len(images_summary), 1)
                    ),
                    1,
                ),
                None,
            ),
        ]
    )

    renamed_summary = images_summary.rename(
        columns={
            "environment_name": "Environment",
            "image_name": "Image",
            "running_containers": "Running containers",
            "endpoints": "Edge agents",
        }
    ).reset_index(drop=True)
    st.dataframe(
        renamed_summary,
        column_config={
            "Running containers": st.column_config.NumberColumn(format="%d"),
            "Edge agents": st.column_config.NumberColumn(format="%d"),
        },
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download image summary",
        data=images_summary,
        filename="portainer_running_images.csv",
    ).render_download_button()

    top_image_chart = px.bar(
        images_summary.head(15),
        x="running_containers",
        y="image_name",
        orientation="h",
        color="environment_name",
        labels={
            "running_containers": "Containers",
            "image_name": "Image",
            "environment_name": "Environment",
        },
        title="Top images by running containers",
    )
    top_image_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
    st.plotly_chart(
        style_plotly_figure(top_image_chart), width="stretch"
    )

    footprint_source = (
        containers_filtered.assign(image=lambda df: df["image"].fillna("Unknown image"))
        .groupby(["environment_name", "endpoint_name", "image"], dropna=False)
        .agg(container_count=("container_id", "nunique"))
        .reset_index()
    )
    if not footprint_source.empty:
        footprint = px.treemap(
            footprint_source,
            path=["environment_name", "endpoint_name", "image"],
            values="container_count",
            title="Where images are running",
        )
        footprint.update_traces(hovertemplate="%{label}<br>Containers: %{value}")
        st.plotly_chart(
            style_plotly_figure(footprint), width="stretch"
        )

