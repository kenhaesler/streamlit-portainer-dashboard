"""Image footprint dashboard."""
from __future__ import annotations

import re
from typing import Sequence

import pandas as pd
import plotly.express as px
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
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from auth import (  # type: ignore[no-redef]
        render_logout_button,
        require_authentication,
    )

try:  # pragma: no cover - import shim for Streamlit runtime
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
    from app.portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        PortainerClient,
    )
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
        initialise_session_state,
        load_configured_environment_settings,
        load_portainer_data,
        render_data_refresh_notice,
        render_sidebar_filters,
    )
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        PortainerClient,
    )
    from ui_helpers import (  # type: ignore[no-redef]
        ExportableDataFrame,
        render_kpi_row,
        render_page_header,
        style_plotly_figure,
    )


_IMAGE_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*(?::[A-Za-z0-9_.-]+)?(?:@sha256:[0-9a-f]{64})?"
)
_TRUE_STRINGS = {
    "true",
    "yes",
    "1",
    "updated",
    "up to date",
    "up-to-date",
    "uptodate",
    "latest",
    "new",
}
_FALSE_STRINGS = {
    "false",
    "0",
    "no",
    "outdated",
    "out of date",
    "out-of-date",
    "stale",
    "needs update",
    "needs-update",
    "update available",
    "updates available",
    "not new",
    "obsolete",
}
_IMAGE_KEYS = {
    "image",
    "imagename",
    "image_name",
    "name",
    "tag",
    "imagetag",
    "repository",
    "repo",
    "repotag",
    "current",
    "currentimage",
    "current_image",
}


def _coerce_boolish(value: object) -> bool | None:
    """Best-effort conversion of Portainer status values to booleans."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        normalised = lowered.replace("-", " ")
        if normalised in _TRUE_STRINGS:
            return True
        if normalised in _FALSE_STRINGS:
            return False
    return None


def _normalise_image_name(value: object) -> str | None:
    """Attempt to coerce ``value`` into a container image reference."""

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or " " in cleaned:
            return None
        lowered = cleaned.lower()
        if lowered in _TRUE_STRINGS or lowered in _FALSE_STRINGS:
            return None
        if not any(sep in cleaned for sep in (":", "/", "@", ".")):
            return None
        return cleaned
    if isinstance(value, dict):
        for key in ("Image", "image", "Name", "name", "RepoTag", "repoTag", "RepoTags", "repoTags", "Tag", "tag"):
            if key in value:
                candidate = _normalise_image_name(value[key])
                if candidate:
                    return candidate
        return None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidate = _normalise_image_name(item)
            if candidate:
                return candidate
    return None


def _extract_outdated_images(payload: object) -> list[str]:
    """Return image names identified as outdated within ``payload``."""

    images: set[str] = set()

    def _walk(obj: object, flagged: bool = False) -> None:
        if isinstance(obj, dict):
            local_flag = flagged
            for key, value in obj.items():
                key_lower = str(key).lower()
                if key_lower in {"isnew", "new", "fresh", "uptodate", "up_to_date", "up-to-date"}:
                    coerced = _coerce_boolish(value)
                    if coerced is not None:
                        local_flag = not coerced
                elif key_lower in {"status", "state", "result"}:
                    coerced = _coerce_boolish(value)
                    if coerced is not None:
                        local_flag = not coerced
                elif key_lower in {"outdated", "outdatedimages", "imagesrequiringupdate", "imagesrequiringupdates"}:
                    _walk(value, flagged=True)
                    continue

                if key_lower in _IMAGE_KEYS:
                    candidate = _normalise_image_name(value)
                    if candidate and (local_flag or flagged):
                        images.add(candidate)

                if isinstance(value, (dict, list, tuple, set)):
                    _walk(value, flagged=local_flag)
                elif local_flag:
                    candidate = _normalise_image_name(value)
                    if candidate:
                        images.add(candidate)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _walk(item, flagged=flagged)
        elif isinstance(obj, str) and flagged:
            for candidate in _IMAGE_NAME_PATTERN.findall(obj):
                cleaned = candidate.strip()
                if cleaned:
                    images.add(cleaned)

    _walk(payload, flagged=False)

    if not images and isinstance(payload, dict):
        message = payload.get("Message")
        if isinstance(message, str):
            for candidate in _IMAGE_NAME_PATTERN.findall(message):
                cleaned = candidate.strip()
                if cleaned:
                    images.add(cleaned)

    return sorted(images)


@st.cache_data(show_spinner=False)
def load_stack_image_statuses(
    environments: Sequence[object],
    stack_requests: Sequence[tuple[str, int, str]],
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch image status information for the provided stacks."""

    env_map = {env.name: env for env in environments}
    clients: dict[str, PortainerClient] = {}
    records: list[dict[str, object]] = []
    warnings: list[str] = []

    for env_name, stack_id, stack_name in stack_requests:
        environment = env_map.get(env_name)
        if environment is None:
            warnings.append(
                f"[{env_name}] Stack '{stack_name}' is not associated with a configured environment."
            )
            continue

        client = clients.get(env_name)
        if client is None:
            client = PortainerClient(
                base_url=environment.api_url,
                api_key=environment.api_key,
                verify_ssl=environment.verify_ssl,
            )
            clients[env_name] = client

        try:
            payload = client.get_stack_image_status(stack_id)
        except PortainerAPIError as exc:
            warnings.append(
                f"[{env_name}] Failed to load image status for stack '{stack_name}' (ID {stack_id}): {exc}"
            )
            continue

        status = None
        message = None
        if isinstance(payload, dict):
            status = payload.get("Status")
            message = payload.get("Message")

        outdated_images = _extract_outdated_images(payload)

        if outdated_images:
            for image_name in outdated_images:
                records.append(
                    {
                        "environment_name": env_name,
                        "stack_id": stack_id,
                        "stack_name": stack_name,
                        "image_name": image_name,
                        "status": status,
                        "message": message,
                    }
                )
        elif isinstance(status, str) and status.lower() in {"outdated", "update available", "updates available"}:
            records.append(
                {
                    "environment_name": env_name,
                    "stack_id": stack_id,
                    "stack_name": stack_name,
                    "image_name": None,
                    "status": status,
                    "message": message,
                }
            )

    columns = [
        "environment_name",
        "stack_id",
        "stack_name",
        "image_name",
        "status",
        "message",
    ]

    if records:
        status_df = pd.DataFrame.from_records(records, columns=columns)
    else:
        status_df = pd.DataFrame(columns=columns)

    return status_df, warnings


try:
    CONFIG = get_config()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

require_authentication(CONFIG)
render_logout_button()

render_page_header(
    "Image footprint",
    icon="🖼️",
    description="Identify the images powering your workloads and where they are deployed.",
)

initialise_session_state(CONFIG)
apply_selected_environment()

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

    render_kpi_row(
        [
            ("Unique running images", int(images_summary["image_name"].nunique()), None),
            (
                "Average containers per image",
                round(
                    float(
                        images_summary["running_containers"].sum()
                        / max(len(images_summary), 1)
                    ),
                    1,
                ),
                None,
            ),
        ]
    )

    renamed_summary = images_summary.rename(
        columns={
            "environment_name": "Environment",
            "image_name": "Image",
            "running_containers": "Running containers",
            "endpoints": "Edge agents",
        }
    ).reset_index(drop=True)
    st.dataframe(
        renamed_summary,
        column_config={
            "Running containers": st.column_config.NumberColumn(format="%d"),
            "Edge agents": st.column_config.NumberColumn(format="%d"),
        },
        width="stretch",
    )
    ExportableDataFrame(
        "⬇️ Download image summary",
        data=images_summary,
        filename="portainer_running_images.csv",
    ).render_download_button()

    top_image_chart = px.bar(
        images_summary.head(15),
        x="running_containers",
        y="image_name",
        orientation="h",
        color="environment_name",
        labels={
            "running_containers": "Containers",
            "image_name": "Image",
            "environment_name": "Environment",
        },
        title="Top images by running containers",
    )
    top_image_chart.update_traces(hovertemplate="%{y}<br>Containers: %{x}")
    st.plotly_chart(
        style_plotly_figure(top_image_chart), use_container_width=True
    )

    footprint_source = (
        containers_filtered.assign(image=lambda df: df["image"].fillna("Unknown image"))
        .groupby(["environment_name", "endpoint_name", "image"], dropna=False)
        .agg(container_count=("container_id", "nunique"))
        .reset_index()
    )
    if not footprint_source.empty:
        footprint = px.treemap(
            footprint_source,
            path=["environment_name", "endpoint_name", "image"],
            values="container_count",
            title="Where images are running",
        )
        footprint.update_traces(hovertemplate="%{label}<br>Containers: %{value}")
        st.plotly_chart(
            style_plotly_figure(footprint), use_container_width=True
        )

st.subheader("Stacks with outdated images")

stack_overview = filters.stack_data
if stack_overview.empty or "stack_id" not in stack_overview.columns:
    st.info("No stack assignments were returned by Portainer to check image status.")
else:
    stack_candidates = (
        stack_overview[["environment_name", "stack_id", "stack_name"]]
        .dropna(subset=["environment_name", "stack_id"])
        .copy()
    )
    stack_candidates["stack_id"] = pd.to_numeric(
        stack_candidates["stack_id"], errors="coerce"
    )
    stack_candidates = stack_candidates.dropna(subset=["stack_id"])

    if stack_candidates.empty:
        st.info("No stack identifiers are available to query image status.")
    else:
        unique_requests = []
        for row in (
            stack_candidates.drop_duplicates(subset=["environment_name", "stack_id"])
            .itertuples(index=False)
        ):
            env_name = str(row.environment_name)
            stack_id_value = int(row.stack_id)
            raw_name = getattr(row, "stack_name", None)
            stack_name = (
                str(raw_name).strip()
                if raw_name is not None and str(raw_name).strip()
                else f"Stack {stack_id_value}"
            )
            unique_requests.append((env_name, stack_id_value, stack_name))

        if not unique_requests:
            st.info("No stack identifiers are available to query image status.")
        else:
            with st.spinner("Checking stack image status via Portainer..."):
                image_status_df, image_status_warnings = load_stack_image_statuses(
                    tuple(configured_environments),
                    tuple(unique_requests),
                )

            for warning in image_status_warnings:
                st.warning(warning, icon="⚠️")

            if image_status_df.empty:
                st.success("All monitored stacks are reporting the newest images available.")
            else:
                display_df = image_status_df.copy()
                display_df["Environment"] = display_df["environment_name"]
                display_df["Stack"] = display_df["stack_name"].fillna("")
                empty_stack_mask = display_df["Stack"].str.strip() == ""
                display_df.loc[empty_stack_mask, "Stack"] = display_df.loc[
                    empty_stack_mask, "stack_id"
                ].apply(lambda value: f"Stack {int(value)}" if pd.notna(value) else "Unknown stack")
                display_df["Image"] = display_df["image_name"].fillna("(not specified)")
                display_df["Status"] = display_df["status"].fillna("outdated")
                display_df["Details"] = display_df["message"].fillna("")

                ordered = (
                    display_df[
                        ["Environment", "Stack", "Image", "Status", "Details"]
                    ]
                    .sort_values(["Environment", "Stack", "Image"], ignore_index=True)
                )

                st.dataframe(
                    ordered,
                    column_config={
                        "Environment": st.column_config.TextColumn(),
                        "Stack": st.column_config.TextColumn(),
                        "Image": st.column_config.TextColumn(),
                        "Status": st.column_config.TextColumn(),
                        "Details": st.column_config.TextColumn(),
                    },
                    width="stretch",
                )

                ExportableDataFrame(
                    "⬇️ Download outdated image list",
                    data=image_status_df,
                    filename="portainer_outdated_stack_images.csv",
                ).render_download_button()

