"""Container health overview dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.auth import require_authentication  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from auth import require_authentication  # type: ignore[no-redef]

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


RESTART_ALERT_THRESHOLD = 3

require_authentication()

render_page_header(
    "Container health",
    icon="🚨",
    description=(
        "Spot stopped, crashed or unstable workloads before they impact your edge fleet."
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
    stack_data, container_data, warnings = fetch_portainer_data(
        configured_environments, include_stopped=True
    )
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

if containers_filtered.empty and stack_filtered.empty:
    st.success("Everything looks healthy for the selected scope.")
    st.stop()

state_series = containers_filtered.get("state")
status_series = containers_filtered.get("status")
if state_series is None:
    state_lower = pd.Series("", index=containers_filtered.index)
    issue_mask = pd.Series(False, index=containers_filtered.index)
else:
    state_values = state_series.astype("string").fillna("")
    state_lower = state_values.str.lower()
    issue_mask = state_lower.ne("running")

if status_series is None:
    status_issue_mask = pd.Series(False, index=containers_filtered.index)
else:
    status_issue_mask = (
        status_series.astype("string")
        .fillna("")
        .str.contains("unhealthy|restart|dead|exit|paused|error", case=False)
    )
problem_containers = containers_filtered[issue_mask | status_issue_mask]

restart_counts_raw = containers_filtered.get("restart_count")
if restart_counts_raw is None:
    restart_counts = pd.Series(0, index=containers_filtered.index, dtype=int)
else:
    restart_counts = (
        pd.to_numeric(restart_counts_raw, errors="coerce")
        .fillna(0)
        .astype(int)
    )
running_state_series = state_lower
high_restart_mask = (restart_counts >= RESTART_ALERT_THRESHOLD) & (
    running_state_series == "running"
)
high_restart_containers = containers_filtered[high_restart_mask]

offline_source = stack_filtered.drop_duplicates(
    subset=["endpoint_id", "environment_name", "endpoint_status", "endpoint_name"]
)
offline_status = (
    offline_source["endpoint_status"].astype("string").fillna("")
)
offline_mask = offline_status.str.lower().isin({"down", "offline"})
offline_agents = offline_source.loc[
    offline_mask, ["environment_name", "endpoint_name", "endpoint_status"]
].rename(
    columns={
        "environment_name": "Environment",
        "endpoint_name": "Edge agent",
        "endpoint_status": "Status",
    }
).sort_values(["Environment", "Edge agent"], na_position="last")

render_kpi_row(
    [
        (
            "Containers in scope",
            int(containers_filtered["container_id"].nunique()),
            None,
        ),
        (
            "Needs attention",
            int(problem_containers["container_id"].nunique()),
            "Stopped, exited or unhealthy containers",
        ),
        (
            "High restart loops",
            int(high_restart_containers["container_id"].nunique()),
            f"≥ {RESTART_ALERT_THRESHOLD} restarts",
        ),
        (
            "Offline agents",
            int(offline_agents["Edge agent"].nunique()) if not offline_agents.empty else 0,
            None,
        ),
    ]
)

if problem_containers.empty and high_restart_containers.empty and offline_agents.empty:
    st.success("All monitored containers and agents are healthy.")
else:
    st.divider()

if not offline_agents.empty:
    st.subheader("Offline edge agents", divider="red")
    st.dataframe(offline_agents.reset_index(drop=True), width="stretch")
    ExportableDataFrame(
        "⬇️ Download offline agent list",
        data=offline_agents,
        filename="portainer_offline_agents.csv",
    ).render_download_button()

problem_summary = (
    problem_containers.groupby(["environment_name", "state"], dropna=False)
    .agg(containers=("container_id", "nunique"))
    .reset_index()
)
if not problem_summary.empty:
    problem_summary["state"] = (
        problem_summary["state"].astype("string").fillna("Unknown state")
    )
    st.subheader("Containers requiring attention", divider="red")
    issue_chart = px.bar(
        problem_summary,
        x="containers",
        y="state",
        orientation="h",
        color="environment_name",
        labels={
            "containers": "Containers",
            "state": "State",
            "environment_name": "Environment",
        },
        title="Distribution of unhealthy containers",
    )
    issue_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
    st.plotly_chart(style_plotly_figure(issue_chart), use_container_width=True)

if not problem_containers.empty:
    attention_display = problem_containers.copy()
    attention_restart_series = attention_display.get("restart_count")
    if attention_restart_series is None:
        attention_display["restart_count"] = 0
    else:
        attention_display["restart_count"] = (
            pd.to_numeric(attention_restart_series, errors="coerce")
            .fillna(0)
            .astype(int)
        )
    created_series = pd.to_datetime(attention_display["created_at"], errors="coerce", utc=True)
    formatted_created = created_series.dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M:%S")
    attention_display["created_at"] = formatted_created
    attention_display.loc[created_series.isna(), "created_at"] = ""
    attention_display = attention_display.sort_values(
        ["environment_name", "endpoint_name", "container_name"],
        na_position="last",
    ).reset_index(drop=True)
    st.dataframe(
        attention_display.rename(
            columns={
                "environment_name": "Environment",
                "endpoint_name": "Edge agent",
                "container_name": "Container",
                "image": "Image",
                "state": "State",
                "status": "Status",
                "restart_count": "Restarts",
                "created_at": "Created",
                "ports": "Published ports",
            }
        ),
        column_config={
            "Restarts": st.column_config.NumberColumn(format="%d"),
            "Created": st.column_config.TextColumn(help="Container creation timestamp"),
        },
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download attention list",
        data=attention_display,
        filename="portainer_container_health.csv",
    ).render_download_button()
else:
    st.info("No stopped or unhealthy containers detected for the current selection.")

if not high_restart_containers.empty:
    st.subheader("Running containers with frequent restarts", divider="orange")
    restart_display = high_restart_containers.copy()
    restart_restart_series = restart_display.get("restart_count")
    if restart_restart_series is None:
        restart_display["restart_count"] = 0
    else:
        restart_display["restart_count"] = (
            pd.to_numeric(restart_restart_series, errors="coerce")
            .fillna(0)
            .astype(int)
        )
    created_series = pd.to_datetime(restart_display["created_at"], errors="coerce", utc=True)
    formatted_created = created_series.dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M:%S")
    restart_display["created_at"] = formatted_created
    restart_display.loc[created_series.isna(), "created_at"] = ""
    restart_display = restart_display.sort_values(
        ["restart_count", "environment_name", "endpoint_name"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    st.dataframe(
        restart_display.rename(
            columns={
                "environment_name": "Environment",
                "endpoint_name": "Edge agent",
                "container_name": "Container",
                "image": "Image",
                "state": "State",
                "status": "Status",
                "restart_count": "Restarts",
                "created_at": "Created",
            }
        ),
        column_config={
            "Restarts": st.column_config.NumberColumn(format="%d"),
            "Created": st.column_config.TextColumn(help="Container creation timestamp"),
        },
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download restart report",
        data=restart_display,
        filename="portainer_restart_alerts.csv",
    ).render_download_button()
else:
    st.info(
        "No running containers exceeded the restart threshold for the current selection."
    )
