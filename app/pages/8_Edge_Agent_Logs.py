"""Edge agent log explorer backed by Kibana / Elasticsearch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

try:
    from app.utils.edge_agent_logs import (  # type: ignore[import-not-found]
        build_agent_dataframe,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from pathlib import Path
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))

    from app.utils.edge_agent_logs import (  # type: ignore[no-redef]
        build_agent_dataframe,
    )

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
    from app.managers.background_job_runner import (  # type: ignore[import-not-found]
        BackgroundJobRunner,
    )
    from app.managers.environment_manager import (  # type: ignore[import-not-found]
        EnvironmentManager,
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
    from managers.background_job_runner import (  # type: ignore[no-redef]
        BackgroundJobRunner,
    )
    from managers.environment_manager import (  # type: ignore[no-redef]
        EnvironmentManager,
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
        include_stopped=True,
    )
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

render_data_refresh_notice(data_result)

for warning in data_result.warnings:
    st.warning(warning, icon="⚠️")

container_data = data_result.container_data
endpoint_data = data_result.endpoint_data

agents_df = build_agent_dataframe(container_data, endpoint_data)
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

agents_in_scope = build_agent_dataframe(filters.container_data, filters.endpoint_data)
if agents_in_scope.empty:
    st.info(
        "The current filters hide all edge agents. Adjust the sidebar scope to continue.",
        icon="ℹ️",
    )
    st.stop()

agents_in_scope = agents_in_scope.assign(
    query_hostname=lambda df: df["agent_hostname"]
    .fillna(df["endpoint_name"])
    .astype("string")
    .fillna("")
)
agents_in_scope = agents_in_scope[
    agents_in_scope["query_hostname"].str.strip() != ""
].copy()

if agents_in_scope.empty:
    st.info(
        "No edge agents expose a hostname to query. Check the Portainer endpoint configuration.",
        icon="ℹ️",
    )
    st.stop()

def _format_agent_label(row: pd.Series) -> str:
    endpoint_name = row.get("endpoint_name")
    hostname = row.get("query_hostname")
    label: str | None
    if endpoint_name and hostname and endpoint_name != hostname:
        label = f"{endpoint_name} · {hostname}"
    else:
        label = endpoint_name or hostname
    if not label:
        label = f"Endpoint {row.get('endpoint_id')}"
    return str(label)

agents_in_scope = agents_in_scope.assign(
    display_label=lambda df: df.apply(_format_agent_label, axis=1)
).sort_values("display_label", kind="stable").reset_index(drop=True)

default_index = 0

with st.form("kibana_log_filters"):
    option_indices = agents_in_scope.index.tolist()
    selected_position = st.selectbox(
        "Edge agent",
        options=option_indices,
        index=default_index,
        format_func=lambda idx: agents_in_scope.loc[idx, "display_label"],
        help="Select the edge agent to query logs for. The hostname is used to match Kibana log entries.",
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

hostname = agents_in_scope.loc[selected_position, "query_hostname"].strip()

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
