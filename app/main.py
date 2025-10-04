import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        PortainerClient,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )
    from app.settings import (  # type: ignore[import-not-found]
        PortainerEnvironment,
        get_configured_environments,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        PortainerClient,
        normalise_endpoint_containers,
        normalise_endpoint_stacks,
    )
    from settings import (  # type: ignore[no-redef]
        PortainerEnvironment,
        get_configured_environments,
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


def _fetch_portainer_data(
    environments: tuple[PortainerEnvironment, ...]
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
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
                    f"[{environment.name}] Failed to load stacks for endpoint "
                    f"{endpoint_id}: {exc}"
                )
                stacks[endpoint_id] = []
            try:
                containers[endpoint_id] = client.list_containers_for_endpoint(
                    endpoint_id
                )
            except PortainerAPIError as exc:
                warnings.append(
                    f"[{environment.name}] Failed to load containers for endpoint "
                    f"{endpoint_id}: {exc}"
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


@st.cache_data(show_spinner=False)
def get_cached_data(
    environments: tuple[PortainerEnvironment, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    return _fetch_portainer_data(environments)


try:
    configured_environments = tuple(get_configured_environments())
except ValueError as exc:
    st.error(str(exc))
    st.stop()

if not configured_environments:
    st.warning(
        "No Portainer environments configured. Provide `PORTAINER_API_URL` and "
        "`PORTAINER_API_KEY`, or define `PORTAINER_ENVIRONMENTS` with specific "
        "environment settings to continue.",
        icon="ℹ️",
    )
    st.stop()

try:
    stack_data, container_data, warnings = get_cached_data(configured_environments)
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

for warning in warnings:
    st.warning(warning, icon="⚠️")


if stack_data.empty and container_data.empty:
    st.info("No data was returned by the Portainer API for the configured account.")
    st.stop()


page_options = [
    "Overview",
    "Environment insights",
    "Running containers",
    "Running images",
]

with st.sidebar:
    if st.button("🔄 Refresh data", use_container_width=True):
        get_cached_data.clear()
        st.rerun()

    st.header("Navigation")
    selected_page = st.radio(
        "Page",
        page_options,
        index=0,
        label_visibility="collapsed",
    )

    st.header("Filters")
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
    selected_environments = st.multiselect(
        "Environments",
        options=environment_options,
        default=environment_options,
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
    endpoints = sorted(endpoint_source.dropna().unique().tolist())
    selected_endpoints = st.multiselect(
        "Edge agents",
        options=endpoints,
        default=endpoints,
    )
    stack_search = st.text_input("Search stack name")
    container_search = st.text_input("Search container or image")

stack_filtered = _humanize_stack_dataframe(stack_data)
if selected_environments:
    stack_filtered = stack_filtered[
        stack_filtered["environment_name"].isin(selected_environments)
    ]
if selected_endpoints:
    stack_filtered = stack_filtered[stack_filtered["endpoint_name"].isin(selected_endpoints)]
if stack_search:
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
        st.subheader("Stacks per edge agent")
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

elif selected_page == "Environment insights":
    st.subheader("Environment health at a glance")

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

    total_endpoints = int(endpoint_overview["endpoint_id"].nunique())
    status_series = endpoint_overview["endpoint_status"].fillna("Unknown").astype(str)
    healthy_count = int(status_series.str.lower().eq("up").sum())
    stack_coverage = 0
    if total_endpoints:
        endpoints_with_stacks = (
            stack_filtered.dropna(subset=["stack_id"])["endpoint_id"].nunique()
        )
        stack_coverage = round((endpoints_with_stacks / total_endpoints) * 100)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Edge agents", total_endpoints)
    with col2:
        st.metric("Healthy agents", healthy_count)
    with col3:
        st.metric("Stack coverage", f"{stack_coverage}%")

    environment_health = []
    for environment_name, group in endpoint_overview.groupby("environment_name"):
        total = int(group["endpoint_id"].nunique())
        healthy = int(
            group["endpoint_status"].fillna("Unknown").str.lower().eq("up").sum()
        )
        coverage = 0
        if total:
            endpoints_with_stacks = int(
                stack_filtered[
                    (stack_filtered["environment_name"] == environment_name)
                    & stack_filtered["stack_id"].notna()
                ]["endpoint_id"].nunique()
            )
            coverage = round((endpoints_with_stacks / total) * 100)
        environment_health.append(
            {
                "environment_name": environment_name,
                "edge_agents": total,
                "healthy_agents": healthy,
                "stack_coverage_percent": coverage,
            }
        )

    if environment_health:
        st.dataframe(
            pd.DataFrame(environment_health)
            .sort_values("edge_agents", ascending=False)
            .rename(
                columns={
                    "environment_name": "Environment",
                    "edge_agents": "Edge agents",
                    "healthy_agents": "Healthy agents",
                    "stack_coverage_percent": "Stack coverage %",
                }
            ),
            use_container_width=True,
        )

    if not endpoint_overview.empty:
        status_counts = (
            endpoint_overview.assign(endpoint_status=status_series)
            .groupby(["environment_name", "endpoint_status"])
            .size()
            .reset_index(name="count")
        )
        status_chart = px.bar(
            status_counts,
            x="endpoint_status",
            y="count",
            color="environment_name",
            title="Endpoint status distribution by environment",
            labels={
                "endpoint_status": "Status",
                "count": "Edge agents",
                "environment_name": "Environment",
            },
            barmode="stack",
        )
        st.plotly_chart(status_chart, use_container_width=True)
    else:
        st.info("No endpoint metadata available for the selected filters.")

    st.subheader("Endpoint activity overview")

    stack_counts = (
        stack_filtered.dropna(subset=["stack_id"])
        .groupby(["environment_name", "endpoint_name"])
        .agg(stacks=("stack_id", "nunique"))
    )
    container_activity = (
        containers_filtered.groupby(["environment_name", "endpoint_name"])
        .agg(
            running_containers=("container_id", "nunique"),
            unique_images=("image", "nunique"),
        )
    )
    endpoint_status_lookup = (
        endpoint_overview.set_index(["environment_name", "endpoint_name"])[
            "endpoint_status"
        ].to_frame()
    )
    endpoint_summary = (
        endpoint_status_lookup.join(stack_counts, how="left")
        .join(container_activity, how="left")
        .fillna({"stacks": 0, "running_containers": 0, "unique_images": 0})
        .astype({"stacks": int, "running_containers": int, "unique_images": int})
        .sort_values(["running_containers", "stacks"], ascending=False)
        .reset_index()
    )
    st.dataframe(endpoint_summary, use_container_width=True)

    if not containers_filtered.empty:
        st.subheader("Container landscape")

        state_counts = (
            containers_filtered.assign(
                state=containers_filtered["state"].fillna("unknown").astype(str)
            )
            .groupby(["environment_name", "state"])
            .size()
            .reset_index(name="count")
        )
        state_chart = px.bar(
            state_counts,
            x="state",
            y="count",
            color="environment_name",
            title="Container state distribution",
            labels={
                "state": "State",
                "count": "Containers",
                "environment_name": "Environment",
            },
            barmode="stack",
            color_discrete_sequence=px.colors.sequential.Cividis,
        )
        st.plotly_chart(state_chart, use_container_width=True)

        container_counts = (
            containers_filtered.groupby(["environment_name", "endpoint_name"])
            .agg(container_count=("container_id", "nunique"))
            .sort_values("container_count", ascending=False)
            .reset_index()
        )
        if not container_counts.empty:
            density_chart = px.bar(
                container_counts,
                x="container_count",
                y="endpoint_name",
                orientation="h",
                title="Running containers per endpoint",
                color="environment_name",
                labels={
                    "endpoint_name": "Endpoint",
                    "container_count": "Containers",
                    "environment_name": "Environment",
                },
            )
            density_chart.update_layout(yaxis_title="Endpoint", xaxis_title="Containers")
            st.plotly_chart(density_chart, use_container_width=True)

        top_images = (
            containers_filtered.groupby(["environment_name", "image"], dropna=False)
            .agg(count=("container_id", "nunique"))
            .reset_index()
            .sort_values("count", ascending=False)
            .head(10)
        )
        if not top_images.empty:
            image_chart = px.bar(
                top_images,
                x="count",
                y="image",
                orientation="h",
                title="Top running images",
                color="environment_name",
                labels={
                    "count": "Containers",
                    "image": "Image",
                    "environment_name": "Environment",
                },
            )
            image_chart.update_layout(yaxis_title="Image", xaxis_title="Containers")
            st.plotly_chart(image_chart, use_container_width=True)

        created_series = pd.to_datetime(
            containers_filtered["created_at"], errors="coerce", utc=True
        )
        age_days = (pd.Timestamp.utcnow() - created_series).dt.total_seconds() / 86400
        if age_days.notna().any():
            age_frame = pd.DataFrame(
                {
                    "environment_name": containers_filtered["environment_name"],
                    "age_days": age_days,
                }
            ).dropna(subset=["age_days"])
            age_chart = px.histogram(
                age_frame,
                x="age_days",
                color="environment_name",
                nbins=20,
                title="Container age distribution",
                labels={"age_days": "Age (days)", "count": "Containers"},
                color_discrete_sequence=px.colors.sequential.Agsunset,
            )
            st.plotly_chart(age_chart, use_container_width=True)
    else:
        st.info("No container data available for the selected filters.")

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
            "environment_name",
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
            ["environment_name", "endpoint_name", "container_name"],
            na_position="last",
        ).reset_index(drop=True)
        st.dataframe(container_display, use_container_width=True)

elif selected_page == "Running images":
    st.subheader("Running images overview")
    if containers_filtered.empty:
        st.info("No running containers available to derive image statistics.")
    else:
        images_summary = (
            containers_filtered.groupby(
                ["environment_name", "image"], dropna=False
            )
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
            ),
            use_container_width=True,
        )
