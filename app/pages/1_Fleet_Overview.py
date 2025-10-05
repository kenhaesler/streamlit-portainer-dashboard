"""Fleet overview dashboard for Portainer data."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.auth import require_authentication  # type: ignore[import-not-found]
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
    from auth import require_authentication  # type: ignore[no-redef]
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

render_page_header(
    "Fleet overview",
    icon="🧭",
    description=(
        "Understand how stacks and containers are distributed across your edge agents."
    ),
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

render_kpi_row(
    [
        ("Visible environments", int(stack_filtered["environment_name"].nunique()), None),
        ("Edge agents", int(stack_filtered["endpoint_id"].nunique()), None),
        ("Stacks", int(stack_filtered["stack_id"].nunique()), None),
        (
            "Running containers",
            int(containers_filtered["container_id"].nunique()),
            "Based on the applied filters",
        ),
    ]
)

stackless = stack_filtered[stack_filtered["stack_id"].isna()]["endpoint_id"].nunique()
if stackless:
    st.caption(f"⚠️ {int(stackless)} edge agent(s) without deployed stacks.")

st.divider()

tab_details, tab_containers = st.tabs([
    "Stacks & edge agents",
    "Container distribution",
])

with tab_details:
    st.subheader("Endpoint & stack overview", divider="blue")
    stack_table = stack_filtered.sort_values(
        ["environment_name", "endpoint_name", "stack_name"],
        na_position="last",
    ).reset_index(drop=True)
    st.dataframe(
        stack_table.rename(
            columns={
                "environment_name": "Environment",
                "endpoint_name": "Edge agent",
                "endpoint_status": "Agent status",
                "stack_name": "Stack",
                "stack_status": "Stack status",
                "stack_type": "Stack type",
            }
        ),
        column_config={
            "Environment": st.column_config.TextColumn(help="Configured Portainer environment"),
            "Edge agent": st.column_config.TextColumn(help="Name of the connected agent"),
            "Agent status": st.column_config.TextColumn(),
            "Stack": st.column_config.TextColumn(help="Stack deployed to the edge agent"),
            "Stack status": st.column_config.TextColumn(),
            "Stack type": st.column_config.TextColumn(),
        },
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download stack overview",
        data=stack_table,
        filename="portainer_stacks.csv",
    ).render_download_button()

    stack_counts = stack_filtered.dropna(subset=["stack_id"])
    if not stack_counts.empty:
        chart_data = (
            stack_counts.groupby(["environment_name", "endpoint_name"])
            .agg(stack_count=("stack_id", "nunique"))
            .reset_index()
            .sort_values("stack_count", ascending=False)
        )
        stack_chart = px.bar(
            chart_data,
            x="stack_count",
            y="endpoint_name",
            orientation="h",
            color="environment_name",
            labels={
                "endpoint_name": "Edge agent",
                "stack_count": "Stacks",
                "environment_name": "Environment",
            },
            title="Stacks deployed per edge agent",
        )
        stack_chart.update_traces(hovertemplate="%{y}<br>Stacks: %{x}")
        st.plotly_chart(
            style_plotly_figure(stack_chart), use_container_width=True
        )

    status_summary = (
        stack_filtered[["endpoint_id", "endpoint_status"]]
        .drop_duplicates(subset="endpoint_id")
        .dropna(subset=["endpoint_status"])
        .groupby("endpoint_status")
        .agg(endpoint_count=("endpoint_id", "count"))
        .reset_index()
    )
    if not status_summary.empty:
        status_chart = px.pie(
            status_summary,
            names="endpoint_status",
            values="endpoint_count",
            title="Edge agent health",
            hole=0.45,
        )
        status_chart.update_traces(textinfo="percent+label")
        st.plotly_chart(
            style_plotly_figure(status_chart), use_container_width=True
        )
    else:
        st.info("No status information available for the selected agents.")

with tab_containers:
    st.subheader("Container insights", divider="blue")
    if containers_filtered.empty:
        st.info("No container information available for the selected filters.")
    else:
        containers_overview = (
            containers_filtered.groupby(
                ["environment_name", "endpoint_name"], dropna=False
            )
            .agg(running_containers=("container_id", "nunique"))
            .reset_index()
        )
        container_chart = px.bar(
            containers_overview,
            x="running_containers",
            y="endpoint_name",
            color="environment_name",
            orientation="h",
            labels={
                "running_containers": "Containers",
                "endpoint_name": "Edge agent",
                "environment_name": "Environment",
            },
            title="Running containers per edge agent",
        )
        container_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
        st.plotly_chart(
            style_plotly_figure(container_chart), use_container_width=True
        )

        treemap_source = (
            containers_filtered.assign(
                image=lambda df: df["image"].fillna("Unknown image"),
                endpoint_name=lambda df: df["endpoint_name"].fillna("Unknown agent"),
            )
            .groupby(["environment_name", "endpoint_name", "image"], dropna=False)
            .agg(container_count=("container_id", "nunique"))
            .reset_index()
        )
        if not treemap_source.empty:
            treemap = px.treemap(
                treemap_source,
                path=["environment_name", "endpoint_name", "image"],
                values="container_count",
                title="Container footprint by environment, agent and image",
            )
            treemap.update_traces(hovertemplate="%{label}<br>Containers: %{value}")
            st.plotly_chart(
                style_plotly_figure(treemap), use_container_width=True
            )

        ExportableDataFrame(
            "⬇️ Download container summary",
            data=containers_filtered,
            filename="portainer_containers.csv",
        ).render_download_button()

