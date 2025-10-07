"""LLM assistant page for querying Portainer data via OpenWebUI/Ollama."""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Mapping

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


def _prepare_dataframe(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(columns))
    available_columns = [column for column in columns if column in df.columns]
    if not available_columns:
        return pd.DataFrame(columns=list(columns))
    subset = df.loc[:, available_columns].copy()
    return subset.fillna("")


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
    "Provide the API endpoint and token for your OpenWebUI deployment. The assistant sends a concise "
    "summary of the filtered Portainer containers and stacks as context for each question.",
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
    api_endpoint = st.text_input(
        "OpenWebUI/Ollama API endpoint",
        value=api_endpoint_default,
        help=(
            "Provide the full chat completion endpoint, for example "
            "`https://llm.example.com/v1/chat/completions`."
        ),
        disabled=SYSTEM_CREDENTIALS_LOCKED,
    )
    auth_mode_options = [
        "Bearer token",
        "Username/password (Basic)",
        "No authentication",
    ]
    if SYSTEM_CREDENTIALS_LOCKED:
        auth_mode = auth_mode_options[0]
        st.selectbox(
            "Authentication method",
            options=auth_mode_options,
            index=0,
            disabled=True,
            help=(
                "Authentication is managed by the deployment via environment variables."
            ),
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
            "Authentication method",
            options=auth_mode_options,
            index=auth_mode_options.index(auth_mode_default),
            help=(
                "Select how to authenticate with the ParisNeo Ollama proxy server or OpenWebUI "
                "deployment. Bearer tokens are sent using the `Authorization: Bearer` header and "
                "username/password credentials use HTTP Basic auth."
            ),
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
                help="Provide the access token issued by your Ollama proxy or OpenWebUI deployment.",
            )
        elif auth_mode == "Username/password (Basic)":
            basic_username = st.text_input(
                "Username",
                value=basic_username,
                help="Username for HTTP basic authentication.",
            )
            basic_password = st.text_input(
                "Password",
                value=basic_password,
                type="password",
                help="Password for HTTP basic authentication.",
            )
    model_name = st.text_input(
        "Model",
        value=st.session_state.get("llm_model", "gpt-oss"),
        help="Name of the model to query via OpenWebUI (e.g. `gpt-oss`).",
    )
    temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=2.0,
        value=float(st.session_state.get("llm_temperature", 0.3)),
        step=0.1,
        help="Higher values increase creativity; lower values make responses more deterministic.",
    )
    max_tokens = st.slider(
        "Max tokens",
        min_value=64,
        max_value=2048,
        value=int(st.session_state.get("llm_max_tokens", 512)),
        step=64,
        help="Maximum number of tokens to generate per response.",
    )
    verify_ssl = st.toggle(
        "Verify TLS certificates",
        value=bool(st.session_state.get("llm_verify_ssl", True)),
        help="Disable this only when your OpenWebUI deployment uses a self-signed certificate.",
    )
    max_context_rows = st.slider(
        "Max containers in context",
        min_value=5,
        max_value=200,
        value=int(st.session_state.get("llm_max_context_rows", 50)),
        step=5,
        help="Limit the number of container rows shared with the LLM to keep prompts concise.",
    )
    max_context_default = int(st.session_state.get("llm_max_context_tokens", 3000))
    if max_context_default < 500:
        max_context_default = 500
    max_context_tokens = st.number_input(
        "Max context tokens",
        min_value=500,
        value=max_context_default,
        step=250,
        help=(
            "Upper bound for the approximate number of tokens allowed in the LLM context payload. "
            "Enter larger values when using models with extended context windows; the assistant will "
            "trim or omit low-priority tables when this limit is exceeded."
        ),
    )
    strategy_options: dict[str, QueryStrategy] = {
        "Direct (single prompt)": QueryStrategy.DIRECT,
        "Carry summary + recent turns": QueryStrategy.SUMMARY,
        "Two-step (plan then answer)": QueryStrategy.STAGED,
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
        "Query orchestration strategy",
        options=strategy_labels,
        index=default_index,
        help=(
            "Control how the assistant manages follow-up turns. Append a rolling summary, or "
            "run a lightweight planning call before issuing the final request to the LLM."
        ),
    )
    query_strategy = strategy_options[query_strategy_label]
    history_turns_default = int(
        st.session_state.get("llm_history_turns", conversation_history.max_turns)
    )
    history_turns = st.slider(
        "Conversation turns to retain",
        min_value=1,
        max_value=6,
        value=history_turns_default,
        help=(
            "How many recent question/answer pairs should be resent to the model on each call. "
            "Older turns are summarised to keep the prompt within budget."
        ),
    )
    summary_budget_default = int(
        st.session_state.get(
            "llm_history_summary_tokens", conversation_history.summary_token_budget
        )
    )
    summary_token_budget = st.slider(
        "Summary token budget",
        min_value=0,
        max_value=1200,
        value=summary_budget_default,
        step=50,
        help=(
            "Approximate number of tokens reserved for the rolling conversation summary."
            " Lower values keep prompts shorter; higher values preserve more nuance."
        ),
    )
    question = st.text_area(
        "Ask the LLM",
        value=st.session_state.get(
            "llm_last_question",
            "Are there any containers reporting issues and what are the likely causes?",
        ),
        height=160,
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

container_context = _prepare_dataframe(containers_filtered, container_columns)
stack_context = _prepare_dataframe(stack_filtered, stack_columns)
endpoint_context = _prepare_dataframe(endpoint_filtered, endpoint_columns)
host_context = _prepare_dataframe(host_filtered, host_columns)
container_detail_context = _prepare_dataframe(
    container_details_filtered, container_detail_columns
)
volume_context = _prepare_dataframe(volume_filtered, volume_columns)
image_context = _prepare_dataframe(image_filtered, image_columns)

container_context_template = container_context.iloc[0:0]
stack_context_template = stack_context.iloc[0:0]
endpoint_context_template = endpoint_context.iloc[0:0]
host_context_template = host_context.iloc[0:0]
container_detail_template = container_detail_context.iloc[0:0]
volume_context_template = volume_context.iloc[0:0]
image_context_template = image_context.iloc[0:0]

context_notices: list[str] = []
prompt_notices: list[str] = []
truncation_notice = (
    "Only the first %s containers and their detailed health metrics are included in the LLM context "
    "to keep the prompt concise."
    % max_context_rows
)
if len(container_context) > max_context_rows:
    container_context = container_context.head(max_context_rows)
    context_notices.append(truncation_notice)
if len(container_detail_context) > max_context_rows:
    container_detail_context = container_detail_context.head(max_context_rows)
    if truncation_notice not in context_notices:
        context_notices.append(truncation_notice)

if not stack_context.empty:
    stack_context = stack_context.head(50)
if not endpoint_context.empty:
    endpoint_context = endpoint_context.head(50)
if not host_context.empty:
    host_context = host_context.head(50)
if not volume_context.empty:
    volume_context = volume_context.head(50)
if not image_context.empty:
    image_context = image_context.head(50)

context_frames: dict[str, pd.DataFrame] = {}
if not container_context.empty:
    context_frames["containers"] = container_context
if not stack_context.empty:
    context_frames["stacks"] = stack_context
if not endpoint_context.empty:
    context_frames["endpoints"] = endpoint_context
if not host_context.empty:
    context_frames["hosts"] = host_context
if not container_detail_context.empty:
    context_frames["container_health"] = container_detail_context
if not volume_context.empty:
    context_frames["volumes"] = volume_context
if not image_context.empty:
    context_frames["images"] = image_context

context_payload: dict[str, object] = {
    key: serialise_records(df) for key, df in context_frames.items()
}
if warnings:
    context_payload["warnings"] = list(warnings)

context_summary = build_context_summary(
    containers_filtered,
    container_details_filtered,
    stack_filtered,
    host_filtered,
)
if context_summary:
    context_payload["summary"] = context_summary

(
    context_payload,
    context_frames,
    budget_notices,
    context_token_count,
) = enforce_context_budget(context_payload, context_frames, max_context_tokens)
context_notices.extend(budget_notices)

container_context = context_frames.get("containers", container_context_template)
stack_context = context_frames.get("stacks", stack_context_template)
endpoint_context = context_frames.get("endpoints", endpoint_context_template)
host_context = context_frames.get("hosts", host_context_template)
container_detail_context = context_frames.get(
    "container_health", container_detail_template
)
volume_context = context_frames.get("volumes", volume_context_template)
image_context = context_frames.get("images", image_context_template)

if "summary" in context_payload:
    context_summary = context_payload["summary"]  # type: ignore[assignment]
else:
    context_summary = {}

context_notices = list(dict.fromkeys(context_notices))

if context_payload:
    context_json_pretty = json.dumps(context_payload, indent=2, ensure_ascii=False)
    context_json_compact = json.dumps(
        context_payload, ensure_ascii=False, separators=(",", ":")
    )
    context_token_count = estimate_token_count(context_json_compact)
else:
    context_json_pretty = "{}"
    context_json_compact = "{}"
    context_token_count = 0

has_context_to_send = (
    bool(context_frames)
    or bool(context_summary)
    or bool(context_payload.get("warnings"))
)

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
        system_prompt = (
            "You are a helpful assistant that analyses Portainer container telemetry to help operators "
            "understand their Docker environments. Base your answer strictly on the provided context."
        )
        client = LLMClient(
            base_url=endpoint_clean,
            token=token_to_send,
            model=model_name.strip() or "gpt-oss",
            verify_ssl=verify_ssl,
        )
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

