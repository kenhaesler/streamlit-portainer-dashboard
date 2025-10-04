import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        load_client_from_env,
        normalise_endpoint_stacks,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        load_client_from_env,
        normalise_endpoint_stacks,
    )

load_dotenv()

st.set_page_config(page_title="Portainer Dashboard", layout="wide")
st.title("🚀 Streamlit Portainer Dashboard")


def _fetch_portainer_data() -> tuple[pd.DataFrame, list[str]]:
    client = load_client_from_env()
    endpoints = client.list_edge_endpoints()
    stacks: dict[int, list[dict]] = {}
    warnings: list[str] = []
    for endpoint in endpoints:
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
        try:
            stacks[endpoint_id] = client.list_stacks_for_endpoint(endpoint_id)
        except PortainerAPIError as exc:
            warnings.append(f"Failed to load stacks for endpoint {endpoint_id}: {exc}")
            stacks[endpoint_id] = []
    data = normalise_endpoint_stacks(endpoints, stacks)
    return data, warnings


@st.cache_data(show_spinner=False)
def get_cached_data() -> tuple[pd.DataFrame, list[str]]:
    return _fetch_portainer_data()


try:
    data, warnings = get_cached_data()
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


if data.empty:
    st.info("No edge endpoints or stacks were returned by the Portainer API.")
    st.stop()


with st.sidebar:
    st.header("Filters")
    endpoints = sorted(name for name in data["endpoint_name"].dropna().unique())
    selected_endpoints = st.multiselect(
        "Edge agents",
        options=endpoints,
        default=endpoints,
    )
    stack_search = st.text_input("Search stack name")

filtered = data.copy()
if selected_endpoints:
    filtered = filtered[filtered["endpoint_name"].isin(selected_endpoints)]
if stack_search:
    filtered = filtered[filtered["stack_name"].fillna("").str.contains(stack_search, case=False)]

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Edge agents", int(filtered["endpoint_id"].nunique()))
with col2:
    st.metric("Stacks", int(filtered["stack_id"].nunique()))
with col3:
    stackless = filtered[filtered["stack_id"].isna()]["endpoint_id"].nunique()
    st.metric("Agents without stacks", int(stackless))

st.subheader("Endpoint & stack overview")
st.dataframe(
    filtered.sort_values(["endpoint_name", "stack_name"], na_position="last").reset_index(drop=True),
    use_container_width=True,
)

stack_counts = filtered.dropna(subset=["stack_id"])
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
