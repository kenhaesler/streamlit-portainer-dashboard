"""Overview dashboard for Portainer data."""
from __future__ import annotations

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


st.title("Overview")

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

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Edge agents", int(stack_filtered["endpoint_id"].nunique()))
with col2:
    st.metric("Stacks", int(stack_filtered["stack_id"].nunique()))
with col3:
    stackless = stack_filtered[stack_filtered["stack_id"].isna()]["endpoint_id"].nunique()
    st.metric("Agents without stacks", int(stackless))

st.subheader("Endpoint & stack overview")
st.dataframe(
    stack_filtered.sort_values(
        ["environment_name", "endpoint_name", "stack_name"],
        na_position="last",
    ).reset_index(drop=True),
    use_container_width=True,
)

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
        x="endpoint_name",
        y="stack_count",
        color="environment_name",
        title="Stacks per edge agent",
        labels={
            "endpoint_name": "Edge agent",
            "stack_count": "Stacks",
            "environment_name": "Environment",
        },
    )
    st.plotly_chart(stack_chart, use_container_width=True)
else:
    st.info("No stacks associated with the selected endpoints.")

