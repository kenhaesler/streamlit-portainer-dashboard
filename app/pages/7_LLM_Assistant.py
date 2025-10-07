"""LLM assistant page for querying Portainer data via OpenWebUI/Ollama."""
from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

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
    from app.services.llm_client import (  # type: ignore[import-not-found]
        LLMClient,
        LLMClientError,
    )
    from app.services.llm_context import (  # type: ignore[import-not-found]
        build_context_summary,
        enforce_context_budget,
        estimate_token_count,
        serialise_records,
    )
    from app.services.llm_workflow import (  # type: ignore[import-not-found]
        ConversationHistory,
        QueryStrategy,
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
    from services.llm_client import LLMClient, LLMClientError  # type: ignore[no-redef]
    from services.llm_context import (  # type: ignore[no-redef]
        build_context_summary,
        enforce_context_budget,
        estimate_token_count,
        serialise_records,
    )
    from services.llm_workflow import (  # type: ignore[no-redef]
        ConversationHistory,
        QueryStrategy,
    )
    from ui_helpers import ExportableDataFrame, render_page_header  # type: ignore[no-redef]


@dataclass(frozen=True)
class ContextPackage:
    """Lightweight container for the context prepared for the LLM."""

    frames: dict[str, pd.DataFrame]
    payload: dict[str, object]
    summary: dict[str, object]
    token_count: int
    notices: list[str]
    json_pretty: str
    json_compact: str


def _prepare_dataframe(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(columns))
    available_columns = [column for column in columns if column in df.columns]
    if not available_columns:
        return pd.DataFrame(columns=list(columns))
    subset = df.loc[:, available_columns].copy()
    return subset.fillna("")


def _build_context_catalog(frames: Mapping[str, pd.DataFrame]) -> dict[str, object]:
    """Return a compact description of the tables available for context."""

    catalog: dict[str, object] = {}
    for name, df in frames.items():
        if df.empty:
            continue
        catalog[name] = {
            "rows": int(len(df)),
            "columns": list(df.columns),
            "sample": serialise_records(df.head(2)),
        }
    return catalog


def _extract_first_json_object(text: str) -> Mapping[str, Any] | None:
    """Return the first JSON object found in *text*, if any."""

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _filter_dataframe(df: pd.DataFrame, filters: Mapping[str, Any]) -> pd.DataFrame:
    """Apply equality filters from *filters* to *df*."""

    filtered = df
    for column, value in filters.items():
        if column not in filtered.columns:
            continue
        if isinstance(value, Mapping):
            # Nested structures are not supported; skip gracefully.
            continue
        if isinstance(value, str) or not isinstance(value, Iterable):
            candidates = [value]
        else:
            candidates = [item for item in value if not isinstance(item, Mapping)]
        normalised = {
            str(candidate).strip()
            for candidate in candidates
            if str(candidate).strip()
        }
        if not normalised:
            continue
        filtered = filtered[filtered[column].astype(str).isin(normalised)]
        if filtered.empty:
            break
    return filtered


def _initial_trim(
    frames: Mapping[str, pd.DataFrame],
    *,
    max_container_rows: int,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Return context frames trimmed according to UI limits."""

    trimmed: dict[str, pd.DataFrame] = {}
    notices: list[str] = []
    container_notice_added = False
    for name, df in frames.items():
        if df.empty:
            continue
        if name in {"containers", "container_health"} and max_container_rows > 0:
            if len(df) > max_container_rows and not container_notice_added:
                notices.append(
                    "Only the first %s containers and their detailed health metrics are included "
                    "in the LLM context to keep the prompt concise." % max_container_rows
                )
                container_notice_added = True
            trimmed[name] = df.head(max_container_rows).copy()
        elif name in {"stacks", "endpoints", "hosts", "volumes", "images"}:
            trimmed[name] = df.head(50).copy()
        else:
            trimmed[name] = df.copy()
    return trimmed, notices


def _apply_dynamic_selection(
    frames: Mapping[str, pd.DataFrame],
    selection: Mapping[str, Any],
    *,
    max_container_rows: int,
) -> tuple[dict[str, pd.DataFrame], list[str], bool]:
    """Return frames requested by the LLM along with notices and summary preference."""

    tables = selection.get("tables")
    include_summary = bool(selection.get("include_summary", True))
    if not isinstance(tables, Iterable):
        return {}, [
            "Model response did not include a `tables` list; falling back to default context.",
        ], include_summary

    selected: dict[str, pd.DataFrame] = {}
    notices: list[str] = []
    for raw_entry in tables:
        if not isinstance(raw_entry, Mapping):
            continue
        name_raw = raw_entry.get("name")
        if not isinstance(name_raw, str):
            continue
        name = name_raw.strip()
        if not name or name not in frames:
            notices.append(f"Model requested unknown context table '{name}'.")
            continue
        df = frames[name]
        if df.empty:
            continue
        filtered = df
        filters = raw_entry.get("filters")
        if isinstance(filters, Mapping):
            filtered = _filter_dataframe(filtered, filters)
        if filtered.empty:
            continue
        limit_raw = raw_entry.get("limit")
        default_limits = {
            "containers": max_container_rows,
            "container_health": max_container_rows,
            "stacks": 100,
            "endpoints": 100,
            "hosts": 100,
            "volumes": 100,
            "images": 100,
        }
        limit = default_limits.get(name, 50)
        if isinstance(limit_raw, (int, float)):
            limit_candidate = int(limit_raw)
            if limit_candidate > 0:
                limit = min(max(limit_candidate, 1), limit)
        over_limit = len(filtered) > limit
        limited = filtered.head(limit).copy()
        if limited.empty:
            continue
        selected[name] = limited
        notices.append(
            "Model selected %s row%s from '%s' context."
            % (len(limited), "s" if len(limited) != 1 else "", name)
        )
        if over_limit:
            notices.append(
                "Only the first %s row%s from '%s' were shared to respect safety limits."
                % (limit, "s" if limit != 1 else "", name)
            )

    return selected, notices, include_summary


def _build_context_package(
    frames: Mapping[str, pd.DataFrame],
    warnings: Iterable[str],
    *,
    max_tokens: int,
    include_summary: bool = True,
) -> ContextPackage:
    """Construct the payload that will be shared with the LLM."""

    frame_copies: dict[str, pd.DataFrame] = {
        key: df.copy() for key, df in frames.items() if not df.empty
    }
    payload: dict[str, object] = {
        key: serialise_records(df) for key, df in frame_copies.items()
    }
    if warnings:
        payload["warnings"] = list(warnings)

    (
        adjusted_payload,
        adjusted_frames,
        budget_notices,
        token_count,
    ) = enforce_context_budget(payload, frame_copies, max_tokens)

    containers_df = adjusted_frames.get("containers", pd.DataFrame())
    details_df = adjusted_frames.get("container_health", pd.DataFrame())
    stacks_df = adjusted_frames.get("stacks", pd.DataFrame())
    hosts_df = adjusted_frames.get("hosts", pd.DataFrame())
    summary: dict[str, object] = {}
    if include_summary:
        summary = build_context_summary(
            containers_df,
            details_df,
            stacks_df,
            hosts_df,
        )
        if summary:
            adjusted_payload["summary"] = summary
            compact_with_summary = json.dumps(
                adjusted_payload, ensure_ascii=False, separators=(",", ":")
            )
            token_count = estimate_token_count(compact_with_summary)
            if max_tokens > 0 and token_count > max_tokens:
                adjusted_payload.pop("summary", None)
                summary = {}
                compact_with_summary = json.dumps(
                    adjusted_payload, ensure_ascii=False, separators=(",", ":")
                )
                token_count = estimate_token_count(compact_with_summary)

    compact_json = json.dumps(
        adjusted_payload, ensure_ascii=False, separators=(",", ":")
    )
    pretty_json = json.dumps(adjusted_payload, indent=2, ensure_ascii=False)

    return ContextPackage(
        frames=adjusted_frames,
        payload=adjusted_payload,
        summary=summary,
        token_count=token_count,
        notices=list(budget_notices),
        json_pretty=pretty_json,
        json_compact=compact_json,
    )


require_authentication()
render_logout_button()

render_page_header(
    "LLM assistant",
    icon="🤖",
    description=(
        "Ask an Ollama/OpenWebUI hosted model about the Portainer data fetched by this dashboard."
    ),
)

st.info(
    "Provide the API endpoint and token for your OpenWebUI deployment. The assistant shares a concise "
    "snapshot of the filtered Portainer data with each question and can ask the model which tables it "
    "needs when the dynamic strategy is enabled.",
    icon="💡",
)

initialise_session_state()
apply_selected_environment()

conversation_state_raw = st.session_state.get("llm_conversation_history")
if isinstance(conversation_state_raw, ConversationHistory):
    conversation_history = conversation_state_raw
else:
    mapping_state: Mapping[str, object] | None
    if isinstance(conversation_state_raw, Mapping):
        mapping_state = conversation_state_raw
    else:
        mapping_state = None
    conversation_history = ConversationHistory.from_state(mapping_state)

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
    data_result = load_portainer_data(
        configured_environments, include_stopped=True
    )
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

render_data_refresh_notice(data_result)

warnings = tuple(data_result.warnings)
for warning in warnings:
    st.warning(warning, icon="⚠️")

stack_data = data_result.stack_data
container_data = data_result.container_data
endpoint_data = data_result.endpoint_data
container_details_data = data_result.container_details
host_data = data_result.host_data
volume_data = data_result.volume_data
image_data = data_result.image_data

filters = render_sidebar_filters(
    stack_data,
    container_data,
    endpoint_data=endpoint_data,
    container_details=container_details_data,
    host_data=host_data,
    volume_data=volume_data,
    image_data=image_data,
    data_status=data_result,
)
stack_filtered = filters.stack_data
containers_filtered = filters.container_data
endpoint_filtered = filters.endpoint_data
container_details_filtered = filters.container_details
host_filtered = filters.host_data
volume_filtered = filters.volume_data
image_filtered = filters.image_data

if stack_filtered.empty and containers_filtered.empty:
    st.info("No Portainer data matched the current filters.", icon="ℹ️")


DEFAULT_ENDPOINT = "https://llm.example.com/v1/chat/completions"
SYSTEM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT")
SYSTEM_BEARER_TOKEN = os.getenv("LLM_BEARER_TOKEN")
SYSTEM_CREDENTIALS_LOCKED = bool(SYSTEM_API_ENDPOINT and SYSTEM_BEARER_TOKEN)

with st.form("llm_query_form", enter_to_submit=False, clear_on_submit=False):
    api_endpoint_default = SYSTEM_API_ENDPOINT or st.session_state.get(
        "llm_api_endpoint", DEFAULT_ENDPOINT
    )
    endpoint_col, model_col = st.columns((2, 1))
    with endpoint_col:
        api_endpoint = st.text_input(
            "LLM API endpoint",
            value=api_endpoint_default,
            help=(
                "Full URL to the chat completions endpoint exposed by OpenWebUI or your Ollama proxy."
            ),
            disabled=SYSTEM_CREDENTIALS_LOCKED,
        )
    with model_col:
        model_name = st.text_input(
            "Model",
            value=st.session_state.get("llm_model", "gpt-oss:latest"),
            help="Model identifier as configured in OpenWebUI (for example `gpt-oss:latest`).",
        )

    auth_mode_options = [
        "Bearer token",
        "Username/password (Basic)",
        "No authentication",
    ]
    if SYSTEM_CREDENTIALS_LOCKED:
        auth_mode = auth_mode_options[0]
        st.selectbox(
            "Authentication",
            options=auth_mode_options,
            index=0,
            disabled=True,
            help="Authentication is managed by the deployment via environment variables.",
        )
        bearer_token = SYSTEM_BEARER_TOKEN or ""
        basic_username = ""
        basic_password = ""
        st.caption(
            "Using the bearer token configured via the `LLM_BEARER_TOKEN` environment variable."
        )
    else:
        auth_mode_default = st.session_state.get("llm_auth_mode", auth_mode_options[0])
        if auth_mode_default not in auth_mode_options:
            auth_mode_default = auth_mode_options[0]
        auth_mode = st.selectbox(
            "Authentication",
            options=auth_mode_options,
            index=auth_mode_options.index(auth_mode_default),
            help="Choose how to sign requests sent to your LLM endpoint.",
        )
        if "llm_bearer_token" in st.session_state:
            bearer_token_default = str(st.session_state.get("llm_bearer_token", ""))
        elif SYSTEM_BEARER_TOKEN is not None:
            bearer_token_default = SYSTEM_BEARER_TOKEN
        else:
            bearer_token_default = ""
        bearer_token = bearer_token_default
        basic_username = st.session_state.get("llm_basic_username", "")
        basic_password = st.session_state.get("llm_basic_password", "")
        if auth_mode == "Bearer token":
            bearer_token = st.text_input(
                "Bearer token",
                value=bearer_token_default,
                type="password",
                help="Token issued by your OpenWebUI or Ollama proxy deployment.",
            )
        elif auth_mode == "Username/password (Basic)":
            basic_username = st.text_input(
                "Username",
                value=basic_username,
                help="HTTP basic authentication username.",
            )
            basic_password = st.text_input(
                "Password",
                value=basic_password,
                type="password",
                help="HTTP basic authentication password.",
            )

    with st.expander("Advanced options", expanded=False):
        st.markdown("**Response controls**")
        temperature = st.slider(
            "Creativity (temperature)",
            min_value=0.0,
            max_value=1.5,
            value=float(st.session_state.get("llm_temperature", 0.2)),
            step=0.05,
            help="Lower values keep answers focused. Increase slightly if responses feel too strict.",
        )
        max_tokens = st.slider(
            "Maximum answer length",
            min_value=256,
            max_value=2048,
            value=int(st.session_state.get("llm_max_tokens", 1024)),
            step=64,
            help="Caps how long the model's answer can be. Higher values produce longer explanations.",
        )
        verify_ssl = st.toggle(
            "Require valid HTTPS certificates",
            value=bool(st.session_state.get("llm_verify_ssl", True)),
            help="Turn this off only when connecting to a trusted server with a self-signed certificate.",
        )

        st.markdown("**Portainer context**")
        max_context_rows = st.slider(
            "Containers shared with the model",
            min_value=20,
            max_value=250,
            value=int(st.session_state.get("llm_max_context_rows", 150)),
            step=10,
            help="Upper bound for container and health rows provided in the context payload.",
        )
        max_context_default = int(st.session_state.get("llm_max_context_tokens", 6000))
        if max_context_default < 2000:
            max_context_default = 2000
        max_context_tokens = st.number_input(
            "Context token budget",
            min_value=2000,
            value=max_context_default,
            step=500,
            help=(
                "Approximate ceiling for the shared Portainer data. The assistant trims lower-priority "
                "tables when this limit is exceeded."
            ),
        )

        st.markdown("**Conversation memory**")
        strategy_options: dict[str, QueryStrategy] = {
            "Direct answer": QueryStrategy.DIRECT,
            "Carry recent history": QueryStrategy.SUMMARY,
            "Plan then answer": QueryStrategy.STAGED,
            "Dynamic context selection": QueryStrategy.DYNAMIC,
        }
        strategy_default_value = str(
            st.session_state.get("llm_query_strategy", QueryStrategy.SUMMARY.value)
        )
        strategy_labels = list(strategy_options)
        try:
            default_index = strategy_labels.index(
                next(
                    label
                    for label, option in strategy_options.items()
                    if option.value == strategy_default_value
                )
            )
        except StopIteration:
            default_index = 0
        query_strategy_label = st.selectbox(
            "Orchestration strategy",
            options=strategy_labels,
            index=default_index,
            help=(
                "Decide how the assistant manages follow-ups. Dynamic selection lets the model request "
                "only the data it needs."
            ),
        )
        query_strategy = strategy_options[query_strategy_label]

        history_turns_default = int(
            st.session_state.get("llm_history_turns", conversation_history.max_turns)
        )
        history_turns = st.slider(
            "Recent exchanges to replay",
            min_value=1,
            max_value=6,
            value=history_turns_default,
            help="How many question/answer pairs to resend alongside each request.",
        )
        summary_budget_default = int(
            st.session_state.get(
                "llm_history_summary_tokens", conversation_history.summary_token_budget
            )
        )
        summary_token_budget = st.slider(
            "Summary space (tokens)",
            min_value=0,
            max_value=1200,
            value=summary_budget_default,
            step=50,
            help="Controls how much room the rolling conversation summary can use.",
        )

    question = st.text_area(
        "Ask the assistant",
        value=st.session_state.get(
            "llm_last_question",
            "Are there any containers reporting issues and what are the likely causes?",
        ),
        height=160,
        help="Describe the operational question you want help with in plain language.",
    )
    submitted = st.form_submit_button("Ask the LLM", use_container_width=True)

st.session_state["llm_api_endpoint"] = api_endpoint
st.session_state["llm_auth_mode"] = auth_mode
st.session_state["llm_bearer_token"] = bearer_token
st.session_state["llm_basic_username"] = basic_username
st.session_state["llm_basic_password"] = basic_password
st.session_state["llm_model"] = model_name
st.session_state["llm_temperature"] = temperature
st.session_state["llm_max_tokens"] = max_tokens
st.session_state["llm_verify_ssl"] = verify_ssl
st.session_state["llm_max_context_rows"] = max_context_rows
st.session_state["llm_max_context_tokens"] = max_context_tokens
st.session_state["llm_query_strategy"] = query_strategy.value
st.session_state["llm_history_turns"] = history_turns
st.session_state["llm_history_summary_tokens"] = summary_token_budget
conversation_history.configure(
    max_turns=history_turns, summary_token_budget=summary_token_budget
)
st.session_state["llm_conversation_history"] = conversation_history.to_state()

if SYSTEM_CREDENTIALS_LOCKED and SYSTEM_API_ENDPOINT:
    st.info(
        "LLM endpoint is managed by the deployment: %s" % SYSTEM_API_ENDPOINT,
        icon="🔒",
    )

container_columns = (
    "environment_name",
    "endpoint_name",
    "container_name",
    "state",
    "status",
    "restart_count",
    "image",
    "ports",
)
stack_columns = (
    "environment_name",
    "endpoint_name",
    "stack_name",
    "stack_status",
    "stack_type",
)
endpoint_columns = (
    "environment_name",
    "endpoint_name",
    "agent_version",
    "platform",
    "operating_system",
    "group_id",
    "last_check_in",
    "tags",
)
host_columns = (
    "environment_name",
    "endpoint_name",
    "docker_version",
    "architecture",
    "operating_system",
    "total_cpus",
    "total_memory",
    "containers_running",
    "containers_stopped",
    "volumes_total",
    "images_total",
)
container_detail_columns = (
    "environment_name",
    "endpoint_name",
    "container_name",
    "health_status",
    "last_exit_code",
    "last_finished_at",
    "cpu_percent",
    "memory_percent",
    "mounts",
    "networks",
    "labels",
)
volume_columns = (
    "environment_name",
    "endpoint_name",
    "volume_name",
    "driver",
    "scope",
    "mountpoint",
    "labels",
)
image_columns = (
    "environment_name",
    "endpoint_name",
    "reference",
    "size",
    "created_at",
    "dangling",
)

container_context_full = _prepare_dataframe(containers_filtered, container_columns)
stack_context_full = _prepare_dataframe(stack_filtered, stack_columns)
endpoint_context_full = _prepare_dataframe(endpoint_filtered, endpoint_columns)
host_context_full = _prepare_dataframe(host_filtered, host_columns)
container_detail_full = _prepare_dataframe(
    container_details_filtered, container_detail_columns
)
volume_context_full = _prepare_dataframe(volume_filtered, volume_columns)
image_context_full = _prepare_dataframe(image_filtered, image_columns)

container_context_template = container_context_full.iloc[0:0]
stack_context_template = stack_context_full.iloc[0:0]
endpoint_context_template = endpoint_context_full.iloc[0:0]
host_context_template = host_context_full.iloc[0:0]
container_detail_template = container_detail_full.iloc[0:0]
volume_context_template = volume_context_full.iloc[0:0]
image_context_template = image_context_full.iloc[0:0]

full_context_frames: dict[str, pd.DataFrame] = {}
if not container_context_full.empty:
    full_context_frames["containers"] = container_context_full
if not stack_context_full.empty:
    full_context_frames["stacks"] = stack_context_full
if not endpoint_context_full.empty:
    full_context_frames["endpoints"] = endpoint_context_full
if not host_context_full.empty:
    full_context_frames["hosts"] = host_context_full
if not container_detail_full.empty:
    full_context_frames["container_health"] = container_detail_full
if not volume_context_full.empty:
    full_context_frames["volumes"] = volume_context_full
if not image_context_full.empty:
    full_context_frames["images"] = image_context_full

trimmed_frames, initial_trim_notices = _initial_trim(
    full_context_frames, max_container_rows=max_context_rows
)

context_package = _build_context_package(
    trimmed_frames,
    warnings,
    max_tokens=max_context_tokens,
)
base_context_notices = list(initial_trim_notices)
context_notices = list(base_context_notices)
context_notices.extend(context_package.notices)
prompt_notices: list[str] = []

context_frames = context_package.frames
context_payload = context_package.payload
context_summary = context_package.summary
context_json_pretty = context_package.json_pretty
context_json_compact = context_package.json_compact
context_token_count = context_package.token_count
context_notices = list(dict.fromkeys(context_notices))
context_catalog = _build_context_catalog(full_context_frames)
catalog_json_compact = json.dumps(
    context_catalog, ensure_ascii=False, separators=(",", ":")
)

has_context_to_send = bool(context_payload)

# The context notice is rendered after the response section to keep feedback near the form.
response_container = st.container()
displayed_response = False

if submitted:
    question_clean = question.strip()
    endpoint_clean = api_endpoint.strip()
    token_to_send: str | None = None
    auth_error: str | None = None
    if auth_mode == "Bearer token":
        token_clean = bearer_token.strip()
        if not token_clean:
            auth_error = "Please provide a bearer token for authentication."
        else:
            token_to_send = f"Bearer {token_clean}"
    elif auth_mode == "Username/password (Basic)":
        username_clean = basic_username.strip()
        if not username_clean:
            auth_error = "Please provide a username for basic authentication."
        else:
            token_to_send = f"{username_clean}:{basic_password}"
    else:
        token_to_send = None
    if not endpoint_clean:
        st.error("Please provide the OpenWebUI/Ollama API endpoint.")
    elif not question_clean:
        st.warning("Enter a question for the LLM before submitting.", icon="ℹ️")
    elif auth_error:
        st.error(auth_error)
    else:
        context_package_for_request = context_package
        context_notices_for_request = list(base_context_notices)
        include_summary = True

        system_prompt = (
            "You are a helpful assistant that analyses Portainer container telemetry to help operators "
            "understand their Docker environments. Base your answer strictly on the provided context."
        )
        client = LLMClient(
            base_url=endpoint_clean,
            token=token_to_send,
            model=model_name.strip() or "gpt-oss:latest",
            verify_ssl=verify_ssl,
        )

        if (
            has_context_to_send
            and query_strategy == QueryStrategy.DYNAMIC
            and context_catalog
        ):
            selection_messages = conversation_history.build_catalog_messages(
                system_prompt=system_prompt,
                question=question_clean,
                catalog_json=catalog_json_compact,
            )
            with st.spinner("Asking the model which Portainer tables it needs..."):
                try:
                    selection_reply = client.chat(
                        selection_messages,
                        temperature=0.0,
                        max_tokens=min(400, max_tokens),
                    )
                except LLMClientError as exc:
                    st.error(f"LLM context selection failed: {exc}")
                    context_notices_for_request.append(
                        "Dynamic context selection failed; using the default tables."
                    )
                else:
                    selection_json = _extract_first_json_object(selection_reply)
                    if selection_json:
                        (
                            selected_frames,
                            selection_notices,
                            include_summary,
                        ) = _apply_dynamic_selection(
                            full_context_frames,
                            selection_json,
                            max_container_rows=max_context_rows,
                        )
                        if selected_frames:
                            context_package_for_request = _build_context_package(
                                selected_frames,
                                warnings,
                                max_tokens=max_context_tokens,
                                include_summary=include_summary,
                            )
                            context_notices_for_request.extend(selection_notices)
                            if not include_summary:
                                context_notices_for_request.append(
                                    "Model opted to skip the high-level summary for this turn."
                                )
                            prompt_notices.append(
                                "Let the model choose which Portainer tables to load before answering."
                            )
                        else:
                            context_notices_for_request.append(
                                "Model did not request any tables; using the default context."
                            )
                    else:
                        context_notices_for_request.append(
                            "Model response did not contain valid JSON instructions; using default context."
                        )

        context_package = context_package_for_request
        context_frames = context_package.frames
        context_payload = context_package.payload
        context_summary = context_package.summary
        context_json_pretty = context_package.json_pretty
        context_json_compact = context_package.json_compact
        context_token_count = context_package.token_count
        context_notices = list(
            dict.fromkeys(context_notices_for_request + context_package.notices)
        )
        has_context_to_send = bool(context_payload)

        if has_context_to_send:
            # Send the compact JSON payload to the model so the transmitted prompt
            # matches the representation used for the token budget estimate.
            context_json = context_json_compact
        else:
            st.info(
                "There is no Portainer data available for the current filters. The question will be "
                "sent to the LLM without additional context.",
                icon="ℹ️",
            )
            context_json = "{}"
        analysis_plan: str | None = None
        planning_failed = False
        if query_strategy == QueryStrategy.STAGED:
            plan_messages = conversation_history.build_plan_messages(
                system_prompt=system_prompt,
                question=question_clean,
                context_json=context_json,
            )
            with st.spinner("Generating analysis plan..."):
                try:
                    analysis_plan = client.chat(
                        plan_messages,
                        temperature=min(temperature, 0.5),
                        max_tokens=min(256, max_tokens),
                    )
                except LLMClientError as exc:
                    st.error(f"LLM planning request failed: {exc}")
                    planning_failed = True
                else:
                    if analysis_plan:
                        analysis_plan = analysis_plan.strip()
                        prompt_notices.append(
                            "Generated a lightweight plan before the final answer."
                        )
        if planning_failed:
            st.session_state["llm_last_plan"] = analysis_plan or ""
        else:
            answer_messages, answer_notices = conversation_history.build_answer_messages(
                strategy=query_strategy,
                system_prompt=system_prompt,
                question=question_clean,
                context_json=context_json,
                plan=analysis_plan if query_strategy == QueryStrategy.STAGED else None,
            )
            prompt_notices.extend(answer_notices)
            spinner_label = (
                "Generating final answer..."
                if query_strategy == QueryStrategy.STAGED
                else "Querying the LLM..."
            )
            with st.spinner(spinner_label):
                try:
                    answer = client.chat(
                        answer_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except LLMClientError as exc:
                    st.error(f"LLM request failed: {exc}")
                    st.session_state["llm_last_plan"] = analysis_plan or ""
                else:
                    st.session_state["llm_last_question"] = question_clean
                    st.session_state["llm_last_answer"] = answer
                    if query_strategy == QueryStrategy.STAGED:
                        st.session_state["llm_last_plan"] = analysis_plan or ""
                    else:
                        st.session_state["llm_last_plan"] = ""
                    conversation_history.record_exchange(
                        question_clean,
                        answer,
                        plan=analysis_plan if query_strategy == QueryStrategy.STAGED else None,
                    )
                    st.session_state["llm_conversation_history"] = (
                        conversation_history.to_state()
                    )
                    with response_container:
                        if analysis_plan and query_strategy == QueryStrategy.STAGED:
                            st.markdown("#### Analysis plan")
                            st.markdown(analysis_plan)
                        st.markdown("### LLM response")
                        st.markdown(answer)
                    displayed_response = True

if not submitted:
    st.session_state.setdefault("llm_last_plan", "")

if not displayed_response and (last_answer := st.session_state.get("llm_last_answer")):
    with response_container:
        last_plan = st.session_state.get("llm_last_plan", "")
        if last_plan:
            st.markdown("#### Analysis plan")
            st.markdown(last_plan)
        st.markdown("### Most recent response")
        st.markdown(last_answer)

st.caption(
    "Approximate LLM context size: %s tokens (limit %s)."
    % (context_token_count, max_context_tokens)
)
for notice in context_notices:
    st.caption(notice)
for notice in prompt_notices:
    st.caption(notice)

show_context_default = bool(st.session_state.get("llm_show_context", True))
show_context = st.toggle(
    "Show LLM context tables",
    value=show_context_default,
    help="Toggle the visibility of the Portainer data that is sent to the LLM as context.",
)
st.session_state["llm_show_context"] = show_context

if show_context:
    container_context = context_frames.get("containers", container_context_template)
    stack_context = context_frames.get("stacks", stack_context_template)
    endpoint_context = context_frames.get("endpoints", endpoint_context_template)
    host_context = context_frames.get("hosts", host_context_template)
    container_detail_context = context_frames.get(
        "container_health", container_detail_template
    )
    volume_context = context_frames.get("volumes", volume_context_template)
    image_context = context_frames.get("images", image_context_template)

    if context_summary:
        st.subheader("Summary shared with the LLM")
        st.json(context_summary)

    st.subheader("Container context shared with the LLM")
    ExportableDataFrame(
        "Download container context",
        container_context,
        "portainer_container_context.csv",
    ).render_download_button()
    st.dataframe(container_context, use_container_width=True, hide_index=True)

    if not stack_context.empty:
        st.subheader("Stack context shared with the LLM")
        ExportableDataFrame(
            "Download stack context",
            stack_context,
            "portainer_stack_context.csv",
        ).render_download_button()
        st.dataframe(stack_context, use_container_width=True, hide_index=True)

    if not endpoint_context.empty:
        st.subheader("Endpoint metadata shared with the LLM")
        ExportableDataFrame(
            "Download endpoint context",
            endpoint_context,
            "portainer_endpoint_context.csv",
        ).render_download_button()
        st.dataframe(endpoint_context, use_container_width=True, hide_index=True)

    if not host_context.empty:
        st.subheader("Host capacity shared with the LLM")
        ExportableDataFrame(
            "Download host metrics",
            host_context,
            "portainer_host_metrics.csv",
        ).render_download_button()
        st.dataframe(host_context, use_container_width=True, hide_index=True)

    if not container_detail_context.empty:
        st.subheader("Container health shared with the LLM")
        ExportableDataFrame(
            "Download container health",
            container_detail_context,
            "portainer_container_health.csv",
        ).render_download_button()
        st.dataframe(
            container_detail_context, use_container_width=True, hide_index=True
        )

    if not volume_context.empty:
        st.subheader("Volume inventory shared with the LLM")
        ExportableDataFrame(
            "Download volume context",
            volume_context,
            "portainer_volume_context.csv",
        ).render_download_button()
        st.dataframe(volume_context, use_container_width=True, hide_index=True)

    if not image_context.empty:
        st.subheader("Image inventory shared with the LLM")
        ExportableDataFrame(
            "Download image context",
            image_context,
            "portainer_image_context.csv",
        ).render_download_button()
        st.dataframe(image_context, use_container_width=True, hide_index=True)

