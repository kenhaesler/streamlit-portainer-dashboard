"""Running images dashboard."""
from __future__ import annotations

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


st.title("Running images")

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
    st.metric("Unique running images", int(images_summary["image_name"].nunique()))
    st.dataframe(
        images_summary.rename(
            columns={
                "environment_name": "Environment",
                "image_name": "Image",
                "running_containers": "Running containers",
                "endpoints": "Edge agents",
            }
        ).reset_index(drop=True),
        use_container_width=True,
    )

