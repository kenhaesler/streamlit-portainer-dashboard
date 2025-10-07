"""Edge agent log explorer backed by Kibana / Elasticsearch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.config import (  # type: ignore[import-not-found]
        ConfigurationError as ConfigError,
        get_config,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from config import (  # type: ignore[no-redef]
        ConfigurationError as ConfigError,
        get_config,
    )

try:  # pragma: no cover - import shim for Streamlit runtime
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
    from app.portainer_client import PortainerAPIError  # type: ignore[import-not-found]
    from app.services.kibana_client import (  # type: ignore[import-not-found]
        KibanaClientError,
        load_kibana_client_from_env,
    )
    from app.ui_helpers import (  # type: ignore[import-not-found]
        ExportableDataFrame,
        render_page_header,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
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
    from portainer_client import PortainerAPIError  # type: ignore[no-redef]
    from services.kibana_client import (  # type: ignore[no-redef]
        KibanaClientError,
        load_kibana_client_from_env,
    )
    from ui_helpers import (  # type: ignore[no-redef]
        ExportableDataFrame,
        render_page_header,
    )


TIME_WINDOWS = {
    "Last 15 minutes": timedelta(minutes=15),
    "Last 1 hour": timedelta(hours=1),
    "Last 6 hours": timedelta(hours=6),
    "Last 24 hours": timedelta(hours=24),
}


def _build_agent_dataframe(container_data: pd.DataFrame) -> pd.DataFrame:
    if container_data.empty:
        return container_data
    columns = ["endpoint_id", "endpoint_name"]
    available_columns = [column for column in columns if column in container_data.columns]
    if not available_columns:
        return pd.DataFrame(columns=columns)
    agents = (
        container_data[available_columns]
        .dropna()
        .drop_duplicates()
        .sort_values(by=available_columns)
        .reset_index(drop=True)
    )
    if "endpoint_name" not in agents.columns:
        agents["endpoint_name"] = agents[available_columns[0]].astype("string")
    return agents


try:
    CONFIG = get_config()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

require_authentication(CONFIG)
render_logout_button()

render_page_header(
    "Edge agent logs",
    icon="🪵",
    description=(
        "Query container logs stored in Elasticsearch / Kibana using the configured API key."
    ),
)

initialise_session_state(CONFIG)
apply_selected_environment(CONFIG)

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
        include_stopped=True,
    )
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

render_data_refresh_notice(data_result)

for warning in data_result.warnings:
    st.warning(warning, icon="⚠️")

container_data = data_result.container_data

agents_df = _build_agent_dataframe(container_data)
if agents_df.empty:
    st.info(
        "No edge agents were discovered from the Portainer API response. Logs cannot be queried yet.",
        icon="ℹ️",
    )
    st.stop()

kibana_client = load_kibana_client_from_env()
if kibana_client is None:
    st.info(
        "Configure the `KIBANA_LOGS_ENDPOINT` and `KIBANA_API_KEY` environment variables to enable log queries.",
        icon="ℹ️",
    )
    st.stop()

st.sidebar.header("Log filters")

filters = render_sidebar_filters(
    CONFIG,
    data_result.stack_data,
    container_data,
    data_status=data_result,
)

agents_in_scope = _build_agent_dataframe(filters.container_data)
if agents_in_scope.empty:
    st.info(
        "The current filters hide all edge agents. Adjust the sidebar scope to continue.",
        icon="ℹ️",
    )
    st.stop()

default_agent = agents_in_scope["endpoint_name"].astype("string").iloc[0]

with st.form("kibana_log_filters"):
    agent_display = (
        agents_in_scope["endpoint_name"].astype("string").sort_values().unique().tolist()
    )
    selected_agent = st.selectbox(
        "Edge agent",
        options=agent_display,
        index=agent_display.index(default_agent) if default_agent in agent_display else 0,
        help="Select the edge agent to query logs for. This maps directly to the `host.hostname` value.",
    )
    container_filter = st.text_input(
        "Container name filter",
        value="",
        help="Optional. When provided only logs from this exact container name are returned.",
    ).strip() or None
    search_term = st.text_input(
        "Search within message",
        value="",
        help="Optional free-text search applied to the log message field.",
    ).strip() or None
    time_window_label = st.selectbox(
        "Time range",
        options=list(TIME_WINDOWS.keys()),
        index=1,
    )
    max_results = st.slider(
        "Maximum number of log entries",
        min_value=10,
        max_value=500,
        value=200,
        step=10,
    )
    submitted = st.form_submit_button("Query logs", type="primary")

if not submitted:
    st.stop()

hostname = selected_agent.strip()

if not hostname:
    st.warning("Provide a hostname to query logs for.", icon="⚠️")
    st.stop()

time_window = TIME_WINDOWS.get(time_window_label, timedelta(hours=1))
now = datetime.now(timezone.utc)
start_time = now - time_window

try:
    logs_df = kibana_client.fetch_logs(
        hostname=hostname,
        start_time=start_time,
        end_time=now,
        container_name=container_filter,
        search_term=search_term,
        size=max_results,
    )
except (ValueError, KibanaClientError) as exc:
    st.error(f"Failed to query Kibana logs: {exc}")
    st.stop()

if logs_df.empty:
    st.info("No logs matched the selected filters for the requested time range.", icon="ℹ️")
    st.stop()

logs_df = logs_df.sort_values("timestamp", ascending=False).reset_index(drop=True)

st.dataframe(logs_df, use_container_width=True, hide_index=True)

export = ExportableDataFrame(
    label="Download results as CSV",
    data=logs_df,
    filename=f"edge-agent-logs-{hostname}-{now:%Y%m%d%H%M%S}.csv",
)
export.render_download_button()

st.caption(
    "Results ordered by the most recent log entry first."
)
