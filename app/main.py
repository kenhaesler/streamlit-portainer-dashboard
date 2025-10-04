import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        load_client_from_env,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        load_client_from_env,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )

load_dotenv()

st.set_page_config(page_title="Portainer Dashboard", layout="wide")
st.title("🚀 Streamlit Portainer Dashboard")


def _humanize_value(value: object, mapping: dict[int, str]) -> object:
    """Return a human-readable label for numeric codes when available."""

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


def _humanize_stack_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Format stack metadata with human-readable labels when possible."""

    if df.empty:
        return df

    endpoint_mapping = {1: "Up", 2: "Down"}
    stack_status_mapping = {1: "Active", 2: "Inactive"}
    stack_type_mapping = {
        1: "Docker Swarm",
        2: "Docker Compose",
        3: "Kubernetes",
    }

    humanised = df.copy()
    for column, mapping in (
        ("endpoint_status", endpoint_mapping),
        ("stack_status", stack_status_mapping),
        ("stack_type", stack_type_mapping),
    ):
        if column in humanised.columns:
            humanised[column] = humanised[column].apply(
                lambda value, mapping=mapping: _humanize_value(value, mapping)
            )
    return humanised


def _fetch_portainer_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    client = load_client_from_env()
    endpoints = client.list_edge_endpoints()
    stacks: dict[int, list[dict]] = {}
    containers: dict[int, list[dict]] = {}
    warnings: list[str] = []
    for endpoint in endpoints:
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
        try:
            stacks[endpoint_id] = client.list_stacks_for_endpoint(endpoint_id)
        except PortainerAPIError as exc:
            warnings.append(f"Failed to load stacks for endpoint {endpoint_id}: {exc}")
            stacks[endpoint_id] = []
        try:
            containers[endpoint_id] = client.list_containers_for_endpoint(endpoint_id)
        except PortainerAPIError as exc:
            warnings.append(
                f"Failed to load containers for endpoint {endpoint_id}: {exc}"
            )
            containers[endpoint_id] = []
    stack_data = normalise_endpoint_stacks(endpoints, stacks)
    container_data = normalise_endpoint_containers(endpoints, containers)
    return stack_data, container_data, warnings


@st.cache_data(show_spinner=False)
def get_cached_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    return _fetch_portainer_data()


try:
    stack_data, container_data, warnings = get_cached_data()
except ValueError as exc:
    st.error(
        "Missing configuration: set `PORTAINER_API_URL` and `PORTAINER_API_KEY` "
        "environment variables.",
    )
    st.stop()
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

for warning in warnings:
    st.warning(warning, icon="⚠️")


if stack_data.empty and container_data.empty:
    st.info("No data was returned by the Portainer API for the configured account.")
    st.stop()


page_options = ["Overview", "Running containers", "Running images"]

with st.sidebar:
    if st.button("🔄 Refresh data", use_container_width=True):
        get_cached_data.clear()
        st.experimental_rerun()

    st.header("Navigation")
    selected_page = st.radio(
        "Page",
        page_options,
        index=0,
        label_visibility="collapsed",
    )

    st.header("Filters")
    endpoints = sorted(name for name in stack_data["endpoint_name"].dropna().unique())
    selected_endpoints = st.multiselect(
        "Edge agents",
        options=endpoints,
        default=endpoints,
    )
    stack_search = st.text_input("Search stack name")
    container_search = st.text_input("Search container or image")

stack_filtered = _humanize_stack_dataframe(stack_data)
if selected_endpoints:
    stack_filtered = stack_filtered[stack_filtered["endpoint_name"].isin(selected_endpoints)]
if stack_search:
    stack_filtered = stack_filtered[
        stack_filtered["stack_name"].fillna("").str.contains(stack_search, case=False)
    ]

containers_filtered = container_data.copy()
if selected_endpoints:
    containers_filtered = containers_filtered[
        containers_filtered["endpoint_name"].isin(selected_endpoints)
    ]
if container_search:
    search_mask = (
        containers_filtered["container_name"].fillna("").str.contains(container_search, case=False)
        | containers_filtered["image"].fillna("").str.contains(container_search, case=False)
    )
    containers_filtered = containers_filtered[search_mask]

if selected_page == "Overview":
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
            ["endpoint_name", "stack_name"], na_position="last"
        ).reset_index(drop=True),
        use_container_width=True,
    )

    stack_counts = stack_filtered.dropna(subset=["stack_id"])
    if not stack_counts.empty:
        chart_data = (
            stack_counts.groupby("endpoint_name")
            .agg(stack_count=("stack_id", "nunique"))
            .sort_values("stack_count", ascending=False)
        )
        st.subheader("Stacks per edge agent")
        st.bar_chart(chart_data)
    else:
        st.info("No stacks associated with the selected endpoints.")

elif selected_page == "Running containers":
    st.subheader("Running containers")
    if containers_filtered.empty:
        st.info("No running containers for the selected endpoints.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Running containers", int(containers_filtered["container_id"].nunique()))
        with col2:
            st.metric("Images in use", int(containers_filtered["image"].nunique()))

        container_display = containers_filtered.copy()
        created_series = pd.to_datetime(container_display["created_at"], errors="coerce", utc=True)
        formatted_created = created_series.dt.tz_convert(None).dt.strftime("%Y-%m-%d %H:%M:%S")
        container_display["created_at"] = formatted_created
        container_display.loc[created_series.isna(), "created_at"] = ""
        column_order = [
            "endpoint_name",
            "container_name",
            "image",
            "state",
            "status",
            "created_at",
            "ports",
            "container_id",
        ]
        existing_columns = [col for col in column_order if col in container_display.columns]
        remaining_columns = [
            col for col in container_display.columns if col not in existing_columns
        ]
        container_display = container_display[existing_columns + remaining_columns]
        container_display = container_display.sort_values(
            ["endpoint_name", "container_name"], na_position="last"
        ).reset_index(drop=True)
        st.dataframe(container_display, use_container_width=True)

elif selected_page == "Running images":
    st.subheader("Running images overview")
    if containers_filtered.empty:
        st.info("No running containers available to derive image statistics.")
    else:
        images_summary = (
            containers_filtered.groupby("image", dropna=False)
            .agg(
                running_containers=("container_id", "nunique"),
                endpoints=("endpoint_name", "nunique"),
            )
            .reset_index()
            .rename(columns={"image": "image_name"})
            .sort_values("running_containers", ascending=False)
        )
        st.metric("Unique running images", int(images_summary["image_name"].nunique()))
        st.dataframe(images_summary, use_container_width=True)
