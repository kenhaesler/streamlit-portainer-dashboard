"""Shared state and data helpers for the dashboard pages."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from .portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        PortainerClient,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )
    from .settings import (  # type: ignore[import-not-found]
        PortainerEnvironment,
        get_configured_environments,
        load_environments,
        save_environments,
    )
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        PortainerClient,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )
    from settings import (  # type: ignore[no-redef]
        PortainerEnvironment,
        get_configured_environments,
        load_environments,
        save_environments,
    )

__all__ = [
    "ConfigurationError",
    "NoEnvironmentsConfiguredError",
    "trigger_rerun",
    "FilterResult",
    "apply_selected_environment",
    "clear_cached_data",
    "fetch_portainer_data",
    "get_saved_environments",
    "get_selected_environment_name",
    "initialise_session_state",
    "load_configured_environment_settings",
    "render_sidebar_filters",
    "set_active_environment",
    "set_saved_environments",
]


class ConfigurationError(RuntimeError):
    """Raised when the configured environments are invalid."""


class NoEnvironmentsConfiguredError(RuntimeError):
    """Raised when no Portainer environments are available."""


SESSION_ENVIRONMENTS_KEY = "portainer_envs"
SESSION_SELECTED_ENV_KEY = "portainer_selected_env"
SESSION_APPLIED_ENV_KEY = "portainer_active_env_applied"
SESSION_FILTER_ENVIRONMENTS = "portainer_filter_selected_environments"
SESSION_FILTER_ENDPOINTS = "portainer_filter_selected_endpoints"
SESSION_FILTER_STACK_SEARCH = "portainer_filter_stack_search"
SESSION_FILTER_CONTAINER_SEARCH = "portainer_filter_container_search"


def trigger_rerun() -> None:
    """Request Streamlit to rerun the script, handling legacy APIs."""

    rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun is None:  # pragma: no cover - unexpected runtime configuration
        raise AttributeError("Streamlit rerun API is unavailable")
    rerun()


def initialise_session_state() -> None:
    """Ensure baseline session state is available for all pages."""

    if SESSION_ENVIRONMENTS_KEY not in st.session_state:
        st.session_state[SESSION_ENVIRONMENTS_KEY] = load_environments()

    if SESSION_SELECTED_ENV_KEY not in st.session_state:
        environments = st.session_state[SESSION_ENVIRONMENTS_KEY]
        st.session_state[SESSION_SELECTED_ENV_KEY] = (
            environments[0]["name"] if environments else ""
        )


def get_saved_environments() -> list[dict[str, object]]:
    """Return all saved environments from the current session."""

    return list(st.session_state.get(SESSION_ENVIRONMENTS_KEY, []))


def set_saved_environments(environments: Iterable[dict[str, object]]) -> None:
    """Persist and update the saved environments list."""

    serialisable = list(environments)
    st.session_state[SESSION_ENVIRONMENTS_KEY] = serialisable
    save_environments(serialisable)


def get_selected_environment_name() -> str:
    """Return the name of the currently selected environment."""

    return str(st.session_state.get(SESSION_SELECTED_ENV_KEY, ""))


def _get_selected_environment() -> dict[str, object] | None:
    selected_name = get_selected_environment_name()
    for environment in get_saved_environments():
        if environment.get("name") == selected_name:
            return environment
    return None


def _set_environment_variables(environment: dict[str, object] | None) -> None:
    """Apply environment variables for the selected Portainer environment."""

    if environment is None:
        return

    os.environ["PORTAINER_API_URL"] = str(environment.get("api_url", ""))
    os.environ["PORTAINER_API_KEY"] = str(environment.get("api_key", ""))
    os.environ["PORTAINER_VERIFY_SSL"] = (
        "true" if bool(environment.get("verify_ssl", True)) else "false"
    )
    if name := environment.get("name"):
        os.environ["PORTAINER_ENVIRONMENT_NAME"] = str(name)


def set_active_environment(name: str) -> None:
    """Update the active environment selection."""

    st.session_state[SESSION_SELECTED_ENV_KEY] = name
    st.session_state.pop(SESSION_APPLIED_ENV_KEY, None)
    clear_cached_data()


def apply_selected_environment() -> None:
    """Apply the selected environment if it has changed since the last run."""

    selected = get_selected_environment_name()
    if st.session_state.get(SESSION_APPLIED_ENV_KEY) == selected:
        return
    environment = _get_selected_environment()
    _set_environment_variables(environment)
    st.session_state[SESSION_APPLIED_ENV_KEY] = selected
    clear_cached_data()


def load_configured_environment_settings() -> tuple[PortainerEnvironment, ...]:
    """Load configured Portainer environments from environment variables."""

    try:
        environments = tuple(get_configured_environments())
    except ValueError as exc:  # pragma: no cover - depends on runtime configuration
        raise ConfigurationError(str(exc)) from exc
    if not environments:
        raise NoEnvironmentsConfiguredError
    return environments


def clear_cached_data() -> None:
    """Clear cached Portainer data."""

    fetch_portainer_data.clear()  # type: ignore[attr-defined]


@st.cache_data(show_spinner=False)
def fetch_portainer_data(
    environments: tuple[PortainerEnvironment, ...],
    *,
    include_stopped: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Fetch data for the provided environments, caching the result.

    Parameters
    ----------
    environments:
        Sequence of configured Portainer environments to query.
    include_stopped:
        When ``True`` the Docker API is queried with ``all=1`` so stopped
        containers are included in the response. Defaults to ``False`` to keep
        compatibility with dashboards that focus on running workloads.
    """

    stack_frames: list[pd.DataFrame] = []
    container_frames: list[pd.DataFrame] = []
    warnings: list[str] = []

    for environment in environments:
        client = PortainerClient(
            base_url=environment.api_url,
            api_key=environment.api_key,
            verify_ssl=environment.verify_ssl,
        )
        endpoints = client.list_edge_endpoints()
        stacks: dict[int, list[dict]] = {}
        containers: dict[int, list[dict]] = {}

        for endpoint in endpoints:
            endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
            try:
                stacks[endpoint_id] = client.list_stacks_for_endpoint(endpoint_id)
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load stacks for endpoint {endpoint_id}: {exc}"
                )
                stacks[endpoint_id] = []
            try:
                containers[endpoint_id] = client.list_containers_for_endpoint(
                    endpoint_id, include_stopped=include_stopped
                )
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load containers for endpoint {endpoint_id}: {exc}"
                )
                containers[endpoint_id] = []

        stack_df = normalise_endpoint_stacks(endpoints, stacks)
        stack_df["environment_name"] = environment.name
        stack_frames.append(stack_df)

        container_df = normalise_endpoint_containers(endpoints, containers)
        container_df["environment_name"] = environment.name
        container_frames.append(container_df)

    if stack_frames:
        stack_data = pd.concat(stack_frames, ignore_index=True)
    else:
        stack_data = normalise_endpoint_stacks([], {})
        stack_data["environment_name"] = pd.Series(dtype="object")

    if container_frames:
        container_data = pd.concat(container_frames, ignore_index=True)
    else:
        container_data = normalise_endpoint_containers([], {})
        container_data["environment_name"] = pd.Series(dtype="object")

    return stack_data, container_data, warnings


def _humanise_value(value: object, mapping: dict[int, str]) -> object:
    if pd.isna(value):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        int_value = int(value)
        return mapping.get(int_value, value)
    if isinstance(value, str):
        try:
            int_value = int(float(value))
        except ValueError:
            return mapping.get(value, value)
        return mapping.get(int_value, mapping.get(value, value))
    return mapping.get(value, value)


def _humanise_stack_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    endpoint_mapping = {1: "Up", 2: "Down"}
    stack_status_mapping = {1: "Active", 2: "Inactive"}
    stack_type_mapping = {1: "Docker Swarm", 2: "Docker Compose", 3: "Kubernetes"}

    humanised = df.copy()
    for column, mapping in (
        ("endpoint_status", endpoint_mapping),
        ("stack_status", stack_status_mapping),
        ("stack_type", stack_type_mapping),
    ):
        if column in humanised.columns:
            humanised[column] = humanised[column].apply(
                lambda value, mapping=mapping: _humanise_value(value, mapping)
            )
    return humanised


@dataclass
class FilterResult:
    selected_environments: list[str]
    selected_endpoints: list[str]
    stack_search: str
    container_search: str
    stack_data: pd.DataFrame
    container_data: pd.DataFrame


def _ensure_session_list(key: str, options: Sequence[str]) -> list[str]:
    current = list(st.session_state.get(key, []))
    valid = [item for item in current if item in options]
    return valid or list(options)


def render_sidebar_filters(
    stack_data: pd.DataFrame,
    container_data: pd.DataFrame,
    *,
    show_stack_search: bool = True,
    show_container_search: bool = True,
) -> FilterResult:
    """Render common sidebar controls and return the applied filters."""

    with st.sidebar:
        if st.button("🔄 Refresh data", width="stretch"):
            clear_cached_data()
            trigger_rerun()

        saved_envs = get_saved_environments()
        env_names = [env.get("name", "") for env in saved_envs if env.get("name")]
        if env_names:
            current_name = get_selected_environment_name()
            if current_name not in env_names:
                current_name = env_names[0]
                set_active_environment(current_name)
            selection = st.selectbox(
                "Active environment",
                env_names,
                index=env_names.index(current_name),
            )
            if selection != current_name:
                set_active_environment(selection)
                trigger_rerun()
        else:
            st.info("No saved environments. Use the Settings page to add one.")

        st.divider()

        environment_options = sorted(
            pd.concat(
                [
                    stack_data.get("environment_name", pd.Series(dtype="object")),
                    container_data.get("environment_name", pd.Series(dtype="object")),
                ]
            )
            .dropna()
            .unique()
            .tolist()
        )

        selected_envs = _ensure_session_list(
            SESSION_FILTER_ENVIRONMENTS, environment_options
        )
        selected_environments = st.multiselect(
            "Environments",
            options=environment_options,
            default=selected_envs,
            key=SESSION_FILTER_ENVIRONMENTS,
        )

        if selected_environments:
            endpoint_source = pd.concat(
                [
                    stack_data[stack_data["environment_name"].isin(selected_environments)][
                        "endpoint_name"
                    ],
                    container_data[
                        container_data["environment_name"].isin(selected_environments)
                    ]["endpoint_name"],
                ],
                ignore_index=True,
            )
        else:
            endpoint_source = pd.Series(dtype="object")

        endpoint_options = sorted(endpoint_source.dropna().unique().tolist())
        selected_endpoint_defaults = _ensure_session_list(
            SESSION_FILTER_ENDPOINTS, endpoint_options
        )
        selected_endpoints = st.multiselect(
            "Edge agents",
            options=endpoint_options,
            default=selected_endpoint_defaults,
            key=SESSION_FILTER_ENDPOINTS,
        )

        stack_search = ""
        if show_stack_search:
            stack_search = st.text_input(
                "Search stack name",
                key=SESSION_FILTER_STACK_SEARCH,
            )

        container_search = ""
        if show_container_search:
            container_search = st.text_input(
                "Search container or image",
                key=SESSION_FILTER_CONTAINER_SEARCH,
            )

    stack_filtered = _humanise_stack_dataframe(stack_data)
    if selected_environments:
        stack_filtered = stack_filtered[
            stack_filtered["environment_name"].isin(selected_environments)
        ]
    if selected_endpoints:
        stack_filtered = stack_filtered[
            stack_filtered["endpoint_name"].isin(selected_endpoints)
        ]
    if show_stack_search and stack_search:
        stack_filtered = stack_filtered[
            stack_filtered["stack_name"].fillna("").str.contains(stack_search, case=False)
        ]

    containers_filtered = container_data.copy()
    if selected_environments:
        containers_filtered = containers_filtered[
            containers_filtered["environment_name"].isin(selected_environments)
        ]
    if selected_endpoints:
        containers_filtered = containers_filtered[
            containers_filtered["endpoint_name"].isin(selected_endpoints)
        ]
    if show_container_search and container_search:
        search_mask = (
            containers_filtered["container_name"].fillna("").str.contains(
                container_search, case=False
            )
            | containers_filtered["image"].fillna("").str.contains(
                container_search, case=False
            )
        )
        containers_filtered = containers_filtered[search_mask]

    return FilterResult(
        selected_environments=selected_environments,
        selected_endpoints=selected_endpoints,
        stack_search=stack_search,
        container_search=container_search,
        stack_data=stack_filtered,
        container_data=containers_filtered,
    )
