"""Shared state and data helpers for the dashboard pages."""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:  # pragma: no cover - import shim for Streamlit runtime
    from .portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        PortainerClient,
        normalise_endpoint_containers,
        normalise_endpoint_images,
        normalise_endpoint_metadata,
        normalise_endpoint_host_metrics,
        normalise_endpoint_stacks,
        normalise_endpoint_volumes,
        normalise_container_details,
    )
    from .environment_cache import (  # type: ignore[import-not-found]
        CacheEntry,
        build_cache_key as build_portainer_cache_key,
        clear_cache as clear_persistent_portainer_cache,
        load_cache_entry as load_portainer_cache_entry,
        store_cache_entry as store_portainer_cache_entry,
    )
    from .services.backup_scheduler import maybe_run_scheduled_backups  # type: ignore[import-not-found]
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
        normalise_endpoint_images,
        normalise_endpoint_metadata,
        normalise_endpoint_host_metrics,
        normalise_endpoint_stacks,
        normalise_endpoint_volumes,
        normalise_container_details,
    )
    from environment_cache import (  # type: ignore[no-redef]
        CacheEntry,
        build_cache_key as build_portainer_cache_key,
        clear_cache as clear_persistent_portainer_cache,
        load_cache_entry as load_portainer_cache_entry,
        store_cache_entry as store_portainer_cache_entry,
    )
    from services.backup_scheduler import (  # type: ignore[no-redef]
        maybe_run_scheduled_backups,
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
    "PortainerDataResult",
    "apply_selected_environment",
    "clear_cached_data",
    "fetch_portainer_data",
    "load_portainer_data",
    "get_saved_environments",
    "get_selected_environment_name",
    "initialise_session_state",
    "load_configured_environment_settings",
    "render_data_refresh_notice",
    "render_sidebar_filters",
    "set_active_environment",
    "set_saved_environments",
]


LOGGER = logging.getLogger(__name__)

_REFRESH_LOCK = threading.Lock()
_ACTIVE_REFRESHERS: dict[str, threading.Thread] = {}


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
SESSION_AUTO_REFRESH_INTERVAL = "portainer_auto_refresh_interval"
SESSION_AUTO_REFRESH_COUNT = "_portainer_auto_refresh_count"


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

    environments = st.session_state[SESSION_ENVIRONMENTS_KEY]
    try:
        maybe_run_scheduled_backups(environments)
    except Exception:  # pragma: no cover - defensive guard for Streamlit runtime
        LOGGER.warning("Scheduled backup execution failed", exc_info=True)

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

    previous_selection = st.session_state.get(SESSION_SELECTED_ENV_KEY, "")
    st.session_state[SESSION_SELECTED_ENV_KEY] = name
    st.session_state.pop(SESSION_APPLIED_ENV_KEY, None)
    clear_cached_data(persistent=bool(str(previous_selection).strip()))


def apply_selected_environment() -> None:
    """Apply the selected environment if it has changed since the last run."""

    selected = get_selected_environment_name()
    applied = st.session_state.get(SESSION_APPLIED_ENV_KEY)
    if applied == selected:
        return
    environment = _get_selected_environment()
    _set_environment_variables(environment)
    st.session_state[SESSION_APPLIED_ENV_KEY] = selected
    clear_cached_data(persistent=applied is not None)


def load_configured_environment_settings() -> tuple[PortainerEnvironment, ...]:
    """Load configured Portainer environments from environment variables."""

    try:
        environments = tuple(get_configured_environments())
    except ValueError as exc:  # pragma: no cover - depends on runtime configuration
        raise ConfigurationError(str(exc)) from exc
    if not environments:
        raise NoEnvironmentsConfiguredError
    return environments


def clear_cached_data(*, persistent: bool = True) -> None:
    """Clear cached Portainer data.

    Parameters
    ----------
    persistent:
        When ``True`` (the default), remove any entries stored in the
        cross-session cache on disk. When ``False`` only the Streamlit
        in-memory cache for the current session is cleared. This is useful for
        avoiding unnecessary cache invalidations across user sessions while
        still ensuring the current session refreshes its data.
    """

    fetch_portainer_data.clear()  # type: ignore[attr-defined]
    if persistent:
        clear_persistent_portainer_cache()


def _serialise_dataframe(df: pd.DataFrame) -> dict[str, object]:
    return {"columns": list(df.columns), "records": df.to_dict(orient="records")}


def _deserialise_dataframe(payload: object) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise ValueError("Invalid dataframe payload")
    columns = payload.get("columns")
    records = payload.get("records")
    if not isinstance(columns, list) or not all(isinstance(col, str) for col in columns):
        raise ValueError("Invalid dataframe columns")
    if not isinstance(records, list):
        raise ValueError("Invalid dataframe records")
    if records:
        return pd.DataFrame.from_records(records, columns=columns)
    return pd.DataFrame(columns=columns)


def _timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.astimezone()


def _build_cached_payload(
    stack_data: pd.DataFrame,
    container_data: pd.DataFrame,
    endpoint_data: pd.DataFrame,
    container_details: pd.DataFrame,
    host_data: pd.DataFrame,
    volume_data: pd.DataFrame,
    image_data: pd.DataFrame,
    warnings: list[str],
) -> dict[str, object]:
    return {
        "stack_data": _serialise_dataframe(stack_data),
        "container_data": _serialise_dataframe(container_data),
        "endpoint_data": _serialise_dataframe(endpoint_data),
        "container_details": _serialise_dataframe(container_details),
        "host_data": _serialise_dataframe(host_data),
        "volume_data": _serialise_dataframe(volume_data),
        "image_data": _serialise_dataframe(image_data),
        "warnings": warnings,
    }


def _deserialise_cache_entry(
    entry: CacheEntry,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[str],
] | None:
    payload = entry.payload
    try:
        stack_data = _deserialise_dataframe(payload.get("stack_data"))
        container_data = _deserialise_dataframe(payload.get("container_data"))
        endpoint_data = _deserialise_dataframe(payload.get("endpoint_data"))
        container_details = _deserialise_dataframe(payload.get("container_details"))
        host_data = _deserialise_dataframe(payload.get("host_data"))
        volume_data = _deserialise_dataframe(payload.get("volume_data"))
        image_data = _deserialise_dataframe(payload.get("image_data"))
    except ValueError:
        return None
    warnings_raw = payload.get("warnings")
    if isinstance(warnings_raw, list) and all(
        isinstance(item, str) for item in warnings_raw
    ):
        warnings = list(warnings_raw)
    else:
        warnings = []
    return (
        stack_data,
        container_data,
        endpoint_data,
        container_details,
        host_data,
        volume_data,
        image_data,
        warnings,
    )


def _fetch_portainer_payload(
    environments: tuple[PortainerEnvironment, ...], *, include_stopped: bool
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[str],
]:
    stack_frames: list[pd.DataFrame] = []
    container_frames: list[pd.DataFrame] = []
    endpoint_frames: list[pd.DataFrame] = []
    container_detail_frames: list[pd.DataFrame] = []
    host_frames: list[pd.DataFrame] = []
    volume_frames: list[pd.DataFrame] = []
    image_frames: list[pd.DataFrame] = []
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
        inspections: dict[int, dict[str, dict]] = {}
        stats: dict[int, dict[str, dict]] = {}
        host_info: dict[int, dict[str, object]] = {}
        host_usage: dict[int, dict[str, object]] = {}
        volumes: dict[int, list[dict]] = {}
        images: dict[int, list[dict]] = {}

        def _load_endpoint_payload(
            endpoint: dict[str, object]
        ) -> tuple[int, list[dict], list[dict], list[str]]:
            endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
            endpoint_warnings: list[str] = []

            try:
                endpoint_stacks = client.list_stacks_for_endpoint(endpoint_id)
            except PortainerAPIError as exc:
                endpoint_warnings.append(
                    f"[{environment.name}] Failed to load stacks for endpoint {endpoint_id}: {exc}"
                )
                endpoint_stacks = []
            else:
                if not isinstance(endpoint_stacks, list):
                    endpoint_stacks = []

            try:
                endpoint_containers = client.list_containers_for_endpoint(
                    endpoint_id, include_stopped=include_stopped
                )
            except PortainerAPIError as exc:
                endpoint_warnings.append(
                    f"[{environment.name}] Failed to load containers for endpoint {endpoint_id}: {exc}"
                )
                endpoint_containers = []
            else:
                if not isinstance(endpoint_containers, list):
                    endpoint_containers = []

            try:
                host_info[endpoint_id] = client.get_endpoint_host_info(endpoint_id)
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load host info for endpoint {endpoint_id}: {exc}"
                )
                host_info[endpoint_id] = {}
            try:
                host_usage[endpoint_id] = client.get_endpoint_system_df(endpoint_id)
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load host usage for endpoint {endpoint_id}: {exc}"
                )
                host_usage[endpoint_id] = {}
            try:
                volumes[endpoint_id] = client.list_volumes_for_endpoint(endpoint_id)
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load volumes for endpoint {endpoint_id}: {exc}"
                )
                volumes[endpoint_id] = []
            try:
                images[endpoint_id] = client.list_images_for_endpoint(endpoint_id)
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load images for endpoint {endpoint_id}: {exc}"
                )
                images[endpoint_id] = []

            inspections.setdefault(endpoint_id, {})
            stats.setdefault(endpoint_id, {})
            for container in endpoint_containers:
                container_id = (
                    container.get("Id")
                    or container.get("ID")
                    or container.get("id")
                )
                if not isinstance(container_id, str) or not container_id:
                    continue
                try:
                    inspections[endpoint_id][container_id] = client.inspect_container(
                        endpoint_id, container_id
                    )
                except PortainerAPIError as exc:
                    warnings.append(
                        f"[{environment.name}] Failed to inspect container {container_id[:12]} on endpoint {endpoint_id}: {exc}"
                    )
                try:
                    stats[endpoint_id][container_id] = client.get_container_stats(
                        endpoint_id, container_id
                    )
                except PortainerAPIError as exc:
                    warnings.append(
                        f"[{environment.name}] Failed to load stats for container {container_id[:12]} on endpoint {endpoint_id}: {exc}"
                    )

            return endpoint_id, endpoint_stacks, endpoint_containers, endpoint_warnings

        for endpoint in endpoints:
            endpoint_id, endpoint_stacks, endpoint_containers, endpoint_warnings = _load_endpoint_payload(
                endpoint
            )
            stacks[endpoint_id] = endpoint_stacks
            containers[endpoint_id] = endpoint_containers
            if endpoint_warnings:
                warnings.extend(endpoint_warnings)

        stack_df = normalise_endpoint_stacks(endpoints, stacks)
        stack_df["environment_name"] = environment.name
        stack_frames.append(stack_df)

        container_df = normalise_endpoint_containers(endpoints, containers)
        container_df["environment_name"] = environment.name
        container_frames.append(container_df)

        endpoint_df = normalise_endpoint_metadata(endpoints)
        endpoint_df["environment_name"] = environment.name
        endpoint_frames.append(endpoint_df)

        container_details_df = normalise_container_details(
            endpoints, containers, inspections, stats
        )
        container_details_df["environment_name"] = environment.name
        container_detail_frames.append(container_details_df)

        host_df = normalise_endpoint_host_metrics(endpoints, host_info, host_usage)
        host_df["environment_name"] = environment.name
        host_frames.append(host_df)

        volume_df = normalise_endpoint_volumes(endpoints, volumes)
        volume_df["environment_name"] = environment.name
        volume_frames.append(volume_df)

        image_df = normalise_endpoint_images(endpoints, images)
        image_df["environment_name"] = environment.name
        image_frames.append(image_df)

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

    if endpoint_frames:
        endpoint_data = pd.concat(endpoint_frames, ignore_index=True)
    else:
        endpoint_data = normalise_endpoint_metadata([])
        endpoint_data["environment_name"] = pd.Series(dtype="object")

    if container_detail_frames:
        container_detail_data = pd.concat(container_detail_frames, ignore_index=True)
    else:
        container_detail_data = normalise_container_details([], {}, {}, {})
        container_detail_data["environment_name"] = pd.Series(dtype="object")

    if host_frames:
        host_data = pd.concat(host_frames, ignore_index=True)
    else:
        host_data = normalise_endpoint_host_metrics([], {}, {})
        host_data["environment_name"] = pd.Series(dtype="object")

    if volume_frames:
        volume_data = pd.concat(volume_frames, ignore_index=True)
    else:
        volume_data = normalise_endpoint_volumes([], {})
        volume_data["environment_name"] = pd.Series(dtype="object")

    if image_frames:
        image_data = pd.concat(image_frames, ignore_index=True)
    else:
        image_data = normalise_endpoint_images([], {})
        image_data["environment_name"] = pd.Series(dtype="object")

    return (
        stack_data,
        container_data,
        endpoint_data,
        container_detail_data,
        host_data,
        volume_data,
        image_data,
        warnings,
    )


def _start_background_refresh(
    cache_key: str,
    environments: tuple[PortainerEnvironment, ...],
    *,
    include_stopped: bool,
) -> bool:
    if not environments:
        return False

    def _worker() -> None:
        try:
            (
                stack_data,
                container_data,
                endpoint_data,
                container_details,
                host_data,
                volume_data,
                image_data,
                warnings,
            ) = _fetch_portainer_payload(
                environments, include_stopped=include_stopped
            )
            payload = _build_cached_payload(
                stack_data,
                container_data,
                endpoint_data,
                container_details,
                host_data,
                volume_data,
                image_data,
                warnings,
            )
            store_portainer_cache_entry(cache_key, payload)
        except Exception:  # pragma: no cover - defensive guard for background thread
            LOGGER.warning(
                "Background refresh for cache key %s failed", cache_key, exc_info=True
            )
        finally:
            fetch_portainer_data.clear()  # type: ignore[attr-defined]
            with _REFRESH_LOCK:
                _ACTIVE_REFRESHERS.pop(cache_key, None)

    with _REFRESH_LOCK:
        existing = _ACTIVE_REFRESHERS.get(cache_key)
        if existing and existing.is_alive():
            return True
        thread = threading.Thread(
            target=_worker,
            name=f"portainer-refresh-{cache_key[:8]}",
            daemon=True,
        )
        _ACTIVE_REFRESHERS[cache_key] = thread
        try:
            thread.start()
        except RuntimeError:  # pragma: no cover - unexpected runtime limitation
            LOGGER.warning(
                "Unable to start background refresh thread for cache key %s",
                cache_key,
                exc_info=True,
            )
            _ACTIVE_REFRESHERS.pop(cache_key, None)
            return False
    return True


@st.cache_data(show_spinner=False)
def fetch_portainer_data(
    environments: tuple[PortainerEnvironment, ...],
    *,
    include_stopped: bool = False,
) -> PortainerDataResult:
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

    cache_key = build_portainer_cache_key(environments, include_stopped=include_stopped)
    cache_entry = load_portainer_cache_entry(cache_key)

    if cache_entry:
        cached = _deserialise_cache_entry(cache_entry)
        if cached:
            (
                stack_data,
                container_data,
                endpoint_data,
                container_details,
                host_data,
                volume_data,
                image_data,
                warnings,
            ) = cached
            refreshed_at = _timestamp_to_datetime(cache_entry.refreshed_at)
            is_refreshing = False
            if cache_entry.is_expired:
                is_refreshing = _start_background_refresh(
                    cache_key, environments, include_stopped=include_stopped
                )
            if is_refreshing or not cache_entry.is_expired:
                return PortainerDataResult(
                    stack_data=stack_data,
                    container_data=container_data,
                    endpoint_data=endpoint_data,
                    container_details=container_details,
                    host_data=host_data,
                    volume_data=volume_data,
                    image_data=image_data,
                    warnings=warnings,
                    refreshed_at=refreshed_at,
                    is_stale=cache_entry.is_expired,
                    is_refreshing=is_refreshing,
                )

    (
        stack_data,
        container_data,
        endpoint_data,
        container_details,
        host_data,
        volume_data,
        image_data,
        warnings,
    ) = _fetch_portainer_payload(
        environments, include_stopped=include_stopped
    )
    refreshed_timestamp = store_portainer_cache_entry(
        cache_key,
        _build_cached_payload(
            stack_data,
            container_data,
            endpoint_data,
            container_details,
            host_data,
            volume_data,
            image_data,
            warnings,
        ),
    )
    refreshed_at = _timestamp_to_datetime(refreshed_timestamp)
    if refreshed_at is None:
        refreshed_at = datetime.now(timezone.utc).astimezone()

    return PortainerDataResult(
        stack_data=stack_data,
        container_data=container_data,
        endpoint_data=endpoint_data,
        container_details=container_details,
        host_data=host_data,
        volume_data=volume_data,
        image_data=image_data,
        warnings=warnings,
        refreshed_at=refreshed_at,
        is_stale=False,
        is_refreshing=False,
    )


def _format_refresh_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    formatted = value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return formatted or value.strftime("%Y-%m-%d %H:%M:%S")


def render_data_refresh_notice(result: PortainerDataResult) -> None:
    """Display the current refresh state to the user."""

    timestamp_text = _format_refresh_timestamp(result.refreshed_at)

    if result.is_refreshing:
        message = "Refreshing Portainer data in the background."
        if timestamp_text:
            message += f" Showing cached results from {timestamp_text}."
        st.info(message, icon="🔄")
    elif result.is_stale:
        message = "Cached Portainer data is out of date."
        if timestamp_text:
            message += f" Last successful refresh {timestamp_text}."
        st.warning(message, icon="⚠️")
    elif timestamp_text:
        st.caption(f"Last synced with Portainer on {timestamp_text}.")


def load_portainer_data(
    environments: tuple[PortainerEnvironment, ...],
    *,
    include_stopped: bool = False,
    progress_message: str | None = None,
) -> PortainerDataResult:
    """Fetch Portainer data while surfacing progress feedback to the user."""

    message = progress_message or "🔄 Fetching the latest data from Portainer…"
    with st.spinner(message):
        return fetch_portainer_data(
            environments, include_stopped=include_stopped
        )


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

    endpoint_mapping = {
        0: "Unknown",
        1: "Up",
        2: "Down",
        3: "Warning",
        "UP": "Up",
        "up": "Up",
        "DOWN": "Down",
        "down": "Down",
        "WARNING": "Warning",
        "warning": "Warning",
        "unknown": "Unknown",
    }
    stack_status_mapping = {1: "Active", 2: "Inactive"}
    stack_type_mapping = {1: "Docker Swarm", 2: "Docker Compose", 3: "Kubernetes"}

    humanised = df.copy()
    for column, mapping in (
        ("endpoint_status", endpoint_mapping),
        ("stack_status", stack_status_mapping),
        ("stack_type", stack_type_mapping),
    ):
        if column in humanised.columns:
            humanised[column] = (
                humanised[column]
                .apply(lambda value, mapping=mapping: _humanise_value(value, mapping))
                .astype("string")
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
    endpoint_data: pd.DataFrame
    container_details: pd.DataFrame
    host_data: pd.DataFrame
    volume_data: pd.DataFrame
    image_data: pd.DataFrame


@dataclass
class PortainerDataResult:
    stack_data: pd.DataFrame
    container_data: pd.DataFrame
    endpoint_data: pd.DataFrame
    container_details: pd.DataFrame
    host_data: pd.DataFrame
    volume_data: pd.DataFrame
    image_data: pd.DataFrame
    warnings: list[str]
    refreshed_at: datetime | None
    is_stale: bool
    is_refreshing: bool


def _ensure_session_list(key: str, options: Sequence[str]) -> list[str]:
    current = list(st.session_state.get(key, []))
    valid = [item for item in current if item in options]
    return valid or list(options)


def _render_sidebar_refresh_status(status: PortainerDataResult) -> None:
    timestamp_text = _format_refresh_timestamp(status.refreshed_at)
    if status.is_refreshing:
        message = "🔄 Refreshing Portainer data…"
        if timestamp_text:
            message += f" Last update {timestamp_text}."
        st.caption(message)
    elif status.is_stale:
        message = "⚠️ Cached data is out of date."
        if timestamp_text:
            message += f" Last update {timestamp_text}."
        st.caption(message)
    elif timestamp_text:
        st.caption(f"📅 Last update {timestamp_text}.")


def render_sidebar_filters(
    stack_data: pd.DataFrame,
    container_data: pd.DataFrame,
    *,
    endpoint_data: pd.DataFrame | None = None,
    container_details: pd.DataFrame | None = None,
    host_data: pd.DataFrame | None = None,
    volume_data: pd.DataFrame | None = None,
    image_data: pd.DataFrame | None = None,
    data_status: PortainerDataResult | None = None,
    show_stack_search: bool = True,
    show_container_search: bool = True,
) -> FilterResult:
    """Render common sidebar controls and return the applied filters."""

    with st.sidebar:
        if data_status is not None:
            _render_sidebar_refresh_status(data_status)
        if st.button("🔄 Refresh data", width="stretch"):
            clear_cached_data()
            trigger_rerun()

        refresh_options = [0, 15, 30, 60, 120, 300]
        refresh_interval = st.session_state.get(SESSION_AUTO_REFRESH_INTERVAL, 0)
        if refresh_interval not in refresh_options:
            refresh_interval = 0

        refresh_interval = st.select_slider(
            "Auto-refresh interval",
            options=refresh_options,
            value=refresh_interval,
            help="Automatically refresh Portainer data. Set to 0 to disable auto-refresh.",
            format_func=lambda value: "Off" if value == 0 else f"Every {value} seconds",
        )
        st.session_state[SESSION_AUTO_REFRESH_INTERVAL] = refresh_interval

        if refresh_interval > 0:
            refresh_count = st_autorefresh(
                interval=int(refresh_interval * 1000),
                key="portainer_data_auto_refresh",
            )
            previous_count = st.session_state.get(SESSION_AUTO_REFRESH_COUNT)
            st.session_state[SESSION_AUTO_REFRESH_COUNT] = refresh_count
            if previous_count is not None and refresh_count != previous_count:
                clear_cached_data()
                trigger_rerun()
        else:
            st.session_state.pop(SESSION_AUTO_REFRESH_COUNT, None)

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

    def _ensure_dataframe(value: pd.DataFrame | None) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        return value

    endpoint_source = _ensure_dataframe(endpoint_data)
    host_source = _ensure_dataframe(host_data)
    volume_source = _ensure_dataframe(volume_data)
    image_source = _ensure_dataframe(image_data)
    container_detail_source = _ensure_dataframe(container_details)

    def _filter_scope(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        filtered = df
        if selected_environments:
            if "environment_name" in filtered.columns:
                filtered = filtered[
                    filtered["environment_name"].isin(selected_environments)
                ]
        if selected_endpoints and "endpoint_name" in filtered.columns:
            filtered = filtered[
                filtered["endpoint_name"].isin(selected_endpoints)
            ]
        return filtered

    endpoint_filtered = _filter_scope(endpoint_source)
    host_filtered = _filter_scope(host_source)
    volume_filtered = _filter_scope(volume_source)
    image_filtered = _filter_scope(image_source)
    container_details_filtered = _filter_scope(container_detail_source)

    if not containers_filtered.empty and not container_details_filtered.empty:
        visible_ids = {
            str(identifier)
            for identifier in containers_filtered["container_id"].fillna("")
            if str(identifier)
        }
        if visible_ids and "container_id" in container_details_filtered.columns:
            container_details_filtered = container_details_filtered[
                container_details_filtered["container_id"].astype(str).isin(visible_ids)
            ]

    return FilterResult(
        selected_environments=selected_environments,
        selected_endpoints=selected_endpoints,
        stack_search=stack_search,
        container_search=container_search,
        stack_data=stack_filtered,
        container_data=containers_filtered,
        endpoint_data=endpoint_filtered,
        container_details=container_details_filtered,
        host_data=host_filtered,
        volume_data=volume_filtered,
        image_data=image_filtered,
    )
