"""Fleet overview dashboard for Portainer data."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.config import (  # type: ignore[import-not-found]
        ConfigurationError as ConfigError,
        get_config,
    )
    from app.auth import (  # type: ignore[import-not-found]
        render_logout_button,
        require_authentication,
    )
    from app.dashboard_state import (  # type: ignore[import-not-found]
        ConfigurationError,
        NoEnvironmentsConfiguredError,
        apply_selected_environment,
        initialise_session_state,
        load_configured_environment_settings,
        load_portainer_data,
        render_data_refresh_notice,
        render_sidebar_filters,
    )
    from app.managers.background_job_runner import (  # type: ignore[import-not-found]
        BackgroundJobRunner,
    )
    from app.managers.environment_manager import (  # type: ignore[import-not-found]
        EnvironmentManager,
    )
    from app.portainer_client import PortainerAPIError  # type: ignore[import-not-found]
    from app.ui_helpers import (  # type: ignore[import-not-found]
        ExportableDataFrame,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from config import (  # type: ignore[no-redef]
        ConfigurationError as ConfigError,
        get_config,
    )
    from auth import (  # type: ignore[no-redef]
        render_logout_button,
        require_authentication,
    )
    from dashboard_state import (  # type: ignore[no-redef]
        ConfigurationError,
        NoEnvironmentsConfiguredError,
        apply_selected_environment,
        initialise_session_state,
        load_configured_environment_settings,
        load_portainer_data,
        render_data_refresh_notice,
        render_sidebar_filters,
    )
    from managers.background_job_runner import (  # type: ignore[no-redef]
        BackgroundJobRunner,
    )
    from managers.environment_manager import (  # type: ignore[no-redef]
        EnvironmentManager,
    )
    from portainer_client import PortainerAPIError  # type: ignore[no-redef]
    from ui_helpers import (  # type: ignore[no-redef]
        ExportableDataFrame,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )

try:
    CONFIG = get_config()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

require_authentication(CONFIG)
render_logout_button()

render_page_header(
    "Fleet overview",
    icon="🧭",
    description=(
        "Understand how stacks and containers are distributed across your edge agents."
    ),
)

initialise_session_state(CONFIG)
apply_selected_environment(CONFIG)
environment_manager = EnvironmentManager(st.session_state)
environments = environment_manager.initialise()
BackgroundJobRunner().maybe_run_backups(environments)
environment_manager.apply_selected_environment()

try:
    configured_environments = load_configured_environment_settings(CONFIG)
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
    data_result = load_portainer_data(
        CONFIG,
        configured_environments,
    )
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

render_data_refresh_notice(data_result)

for warning in data_result.warnings:
    st.warning(warning, icon="⚠️")

stack_data = data_result.stack_data
container_data = data_result.container_data

if stack_data.empty and container_data.empty:
    st.info("No data was returned by the Portainer API for the configured account.")
    st.stop()

filters = render_sidebar_filters(
    CONFIG,
    stack_data,
    container_data,
    data_status=data_result,
)

stack_filtered = filters.stack_data
containers_filtered = filters.container_data

if "image" in containers_filtered.columns:
    active_image_count = int(containers_filtered["image"].dropna().nunique())
else:
    active_image_count = 0

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
        (
            "Active images",
            active_image_count,
            "Unique container images across the selected endpoints",
        ),
    ]
)

stackless = stack_filtered[stack_filtered["stack_id"].isna()]["endpoint_id"].nunique()
if stackless:
    st.caption(f"⚠️ {int(stackless)} edge agent(s) without deployed stacks.")

st.divider()

tab_overview, tab_visuals = st.tabs([
    "Operational overview",
    "Visual insights",
])

stack_table = stack_filtered.sort_values(
    ["environment_name", "endpoint_name", "stack_name"],
    na_position="last",
).reset_index(drop=True)

stack_counts = (
    stack_filtered.dropna(subset=["stack_id"])
    .groupby(["environment_name", "endpoint_name"], dropna=False)
    .agg(stack_count=("stack_id", "nunique"))
    .reset_index()
)

status_summary = (
    stack_filtered[["endpoint_id", "endpoint_status"]]
    .drop_duplicates(subset="endpoint_id")
    .dropna(subset=["endpoint_status"])
    .groupby("endpoint_status")
    .agg(endpoint_count=("endpoint_id", "count"))
    .reset_index()
)

endpoint_overview = (
    stack_filtered[
        [
            "environment_name",
            "endpoint_id",
            "endpoint_name",
            "endpoint_status",
        ]
    ]
    .drop_duplicates()
    .reset_index(drop=True)
)

if not endpoint_overview.empty:
    endpoint_overview = endpoint_overview.merge(
        stack_counts,
        on=["environment_name", "endpoint_name"],
        how="left",
    )
    container_counts = (
        containers_filtered.groupby(["environment_name", "endpoint_name"], dropna=False)
        .agg(container_count=("container_id", "nunique"))
        .reset_index()
    )
    endpoint_overview = endpoint_overview.merge(
        container_counts,
        on=["environment_name", "endpoint_name"],
        how="left",
    )
    endpoint_overview["stack_count"] = endpoint_overview["stack_count"].fillna(0).astype(int)
    endpoint_overview["container_count"] = (
        endpoint_overview["container_count"].fillna(0).astype(int)
    )

containers_overview = (
    containers_filtered.groupby(["environment_name", "endpoint_name"], dropna=False)
    .agg(running_containers=("container_id", "nunique"))
    .reset_index()
)

treemap_source = pd.DataFrame()
if "image" in containers_filtered.columns:
    treemap_source = (
        containers_filtered.assign(
            image=lambda df: df["image"].fillna("Unknown image"),
            endpoint_name=lambda df: df["endpoint_name"].fillna("Unknown agent"),
        )
        .groupby(["environment_name", "endpoint_name", "image"], dropna=False)
        .agg(container_count=("container_id", "nunique"))
        .reset_index()
    )

top_images = pd.DataFrame()
if not treemap_source.empty:
    top_images = (
        treemap_source.groupby(["environment_name", "image"])
        .agg(container_count=("container_count", "sum"))
        .reset_index()
        .sort_values("container_count", ascending=False)
        .head(10)
    )

created_raw = containers_filtered.get("created_at")
age_frame = pd.DataFrame()
if created_raw is not None:
    created_series = pd.to_datetime(created_raw, errors="coerce", utc=True)
    age_days = (pd.Timestamp.utcnow() - created_series).dt.total_seconds() / 86400
    age_frame = pd.DataFrame(
        {
            "environment_name": containers_filtered["environment_name"],
            "age_days": age_days,
        }
    ).dropna(subset=["age_days"])

with tab_overview:
    st.subheader("Stack directory", divider="blue")
    st.caption("Browse all stacks with search and filtering applied above.")
    stack_search = st.text_input(
        "Search stacks",
        placeholder="Filter by stack name, agent, environment or status…",
        help="Quickly narrow down the stack list by typing part of a name or status.",
    ).strip()
    stack_display = stack_table
    if stack_search:
        query = stack_search.lower()
        search_columns = [
            "environment_name",
            "endpoint_name",
            "stack_name",
            "stack_status",
            "stack_type",
        ]
        stack_display = stack_display[
            stack_display[search_columns]
            .fillna("")
            .apply(lambda row: any(query in str(value).lower() for value in row), axis=1)
        ]
        st.caption(f"Showing {len(stack_display)} stack(s) matching “{stack_search}”.")
    if stack_display.empty:
        st.info("No stacks match the current filters. Try adjusting the filters or clearing the search.")
    else:
        st.dataframe(
            stack_display.rename(
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
            use_container_width=True,
            hide_index=True,
            height=420,
        )
    ExportableDataFrame(
        "⬇️ Download stack overview",
        data=stack_display,
        filename="portainer_stacks.csv",
    ).render_download_button()

    st.subheader("Edge agent coverage", divider="blue")
    if endpoint_overview.empty:
        st.info("No edge agent information available for the selected filters.")
    else:
        st.dataframe(
            endpoint_overview.rename(
                columns={
                    "environment_name": "Environment",
                    "endpoint_name": "Edge agent",
                    "endpoint_status": "Agent status",
                    "stack_count": "Stacks",
                    "container_count": "Running containers",
                }
            ).sort_values(["Environment", "Edge agent"], na_position="last"),
            use_container_width=True,
            hide_index=True,
            height=320,
        )
        ExportableDataFrame(
            "⬇️ Download endpoint coverage",
            data=endpoint_overview,
            filename="portainer_endpoint_coverage.csv",
        ).render_download_button()

    st.subheader("Container summary", divider="blue")
    if containers_overview.empty:
        st.info("No container information available for the selected filters.")
    else:
        st.dataframe(
            containers_overview.rename(
                columns={
                    "environment_name": "Environment",
                    "endpoint_name": "Edge agent",
                    "running_containers": "Running containers",
                }
            ).sort_values(["Environment", "Edge agent"], na_position="last"),
            use_container_width=True,
            hide_index=True,
            height=320,
        )
        ExportableDataFrame(
            "⬇️ Download container summary",
            data=containers_overview,
            filename="portainer_container_summary.csv",
        ).render_download_button()

    ExportableDataFrame(
        "⬇️ Download container details",
        data=containers_filtered,
        filename="portainer_containers.csv",
    ).render_download_button()

with tab_visuals:
    st.subheader("Stack insights", divider="blue")
    if stack_counts.empty:
        st.info("Add stacks or adjust the filters to view stack analytics.")
    else:
        chart_data = stack_counts.sort_values("stack_count", ascending=False)
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
        st.plotly_chart(style_plotly_figure(stack_chart), use_container_width=True)

    if status_summary.empty:
        st.info("No status information available for the selected agents.")
    else:
        status_chart = px.pie(
            status_summary,
            names="endpoint_status",
            values="endpoint_count",
            title="Edge agent health",
            hole=0.45,
        )
        status_chart.update_traces(textinfo="percent+label")
        st.plotly_chart(style_plotly_figure(status_chart), use_container_width=True)

    if endpoint_overview.empty:
        st.info("No combined stack and container data to visualise yet.")
    else:
        combined_load = endpoint_overview[
            [
                "environment_name",
                "endpoint_name",
                "stack_count",
                "container_count",
            ]
        ]
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
            st.plotly_chart(style_plotly_figure(load_scatter), use_container_width=True)

    st.subheader("Container insights", divider="blue")
    if containers_overview.empty:
        st.info("No container information available for the selected filters.")
    else:
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
        st.plotly_chart(style_plotly_figure(container_chart), use_container_width=True)

    if treemap_source.empty:
        st.info("Add container image metadata to explore image distribution.")
    else:
        treemap = px.treemap(
            treemap_source,
            path=["environment_name", "endpoint_name", "image"],
            values="container_count",
            title="Container footprint by environment, agent and image",
        )
        treemap.update_traces(hovertemplate="%{label}<br>Containers: %{value}")
        st.plotly_chart(style_plotly_figure(treemap), use_container_width=True)

    if not top_images.empty:
        image_chart = px.bar(
            top_images,
            x="container_count",
            y="image",
            orientation="h",
            title="Top running images",
            color="environment_name",
            labels={
                "container_count": "Containers",
                "image": "Image",
                "environment_name": "Environment",
            },
        )
        image_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
        st.plotly_chart(style_plotly_figure(image_chart), use_container_width=True)
        ExportableDataFrame(
            "⬇️ Download top images",
            data=top_images,
            filename="portainer_top_images.csv",
        ).render_download_button()

    if not age_frame.empty:
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
        )
        age_chart.update_traces(
            hovertemplate="Age: %{x:.1f} days<br>Containers: %{y}"
        )
        st.plotly_chart(style_plotly_figure(age_chart), use_container_width=True)

