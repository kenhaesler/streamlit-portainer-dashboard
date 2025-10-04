"""Running containers dashboard."""
from __future__ import annotations

import pandas as pd
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
        apply_global_theme,
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
        apply_global_theme,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )

apply_global_theme()

render_page_header(
    "Running containers",
    icon="🐳",
    description="Inspect all running workloads, their images and exposed ports.",
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

if containers_filtered.empty:
    st.info("No running containers for the selected endpoints.")
else:
    render_kpi_row(
        [
            ("Running containers", int(containers_filtered["container_id"].nunique()), None),
            ("Images in use", int(containers_filtered["image"].nunique()), None),
            (
                "Edge agents",
                int(containers_filtered["endpoint_id"].nunique()),
                None,
            ),
        ]
    )

    state_summary = (
        containers_filtered.groupby(["state"], dropna=False)
        .agg(container_count=("container_id", "nunique"))
        .reset_index()
        .rename(columns={"state": "Container state"})
    )
    if not state_summary.empty:
        import plotly.express as px

        state_chart = px.bar(
            state_summary,
            x="Container state",
            y="container_count",
            title="Container state overview",
            labels={"container_count": "Containers"},
        )
        state_chart.update_traces(hovertemplate="%{x}<br>Containers: %{y}")
        st.plotly_chart(
            style_plotly_figure(state_chart), use_container_width=True
        )

    container_display = containers_filtered.copy()
    created_series = pd.to_datetime(container_display["created_at"], errors="coerce", utc=True)
    formatted_created = created_series.dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M:%S")
    container_display["created_at"] = formatted_created
    container_display.loc[created_series.isna(), "created_at"] = ""
    column_order = [
        "environment_name",
        "endpoint_name",
        "container_name",
        "image",
        "state",
        "status",
        "created_at",
        "ports",
        "container_id",
    ]
    existing_columns = [col for col in column_order if col in container_display.columns]
    remaining_columns = [
        col for col in container_display.columns if col not in existing_columns
    ]
    container_display = container_display[existing_columns + remaining_columns]
    container_display = container_display.sort_values(
        ["environment_name", "endpoint_name", "container_name"],
        na_position="last",
    ).reset_index(drop=True)
    st.dataframe(
        container_display.rename(
            columns={
                "environment_name": "Environment",
                "endpoint_name": "Edge agent",
                "container_name": "Container",
                "image": "Image",
                "state": "State",
                "status": "Status",
                "created_at": "Created",
                "ports": "Published ports",
            }
        ),
        column_config={
            "Created": st.column_config.TextColumn(help="Container creation timestamp"),
            "Published ports": st.column_config.TextColumn(help="Public -> private port mapping"),
        },
        width="stretch",
    )

    ExportableDataFrame(
        "⬇️ Download container list",
        data=container_display,
        filename="portainer_running_containers.csv",
    ).render_download_button()

