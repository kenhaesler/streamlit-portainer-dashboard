"""Intelligent assistant for querying Portainer telemetry with adaptive context."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

try:  # pragma: no cover - runtime imports resolved differently during tests
    from app.config import (  # type: ignore[import-not-found]
        ConfigurationError as ConfigError,
        get_config,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from config import (  # type: ignore[no-redef]
        ConfigurationError as ConfigError,
        get_config,
    )

try:  # pragma: no cover - runtime imports resolved differently during tests
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
    from app.managers.background_job_runner import (  # type: ignore[import-not-found]
        BackgroundJobRunner,
    )
    from app.managers.environment_manager import (  # type: ignore[import-not-found]
        EnvironmentManager,
    )
    from app.portainer_client import PortainerAPIError  # type: ignore[import-not-found]
    from app.services.llm_client import (  # type: ignore[import-not-found]
        LLMClient,
        LLMClientError,
    )
    from app.services.llm_context import (  # type: ignore[import-not-found]
        DataTable,
        LLMDataHub,
        QueryPlan,
        QueryRequest,
        parse_query_plan,
    )
    from app.ui_helpers import (  # type: ignore[import-not-found]
        ExportableDataFrame,
        render_page_header,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for direct execution
    from auth import render_logout_button, require_authentication  # type: ignore[no-redef]
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
    from managers.background_job_runner import (  # type: ignore[no-redef]
        BackgroundJobRunner,
    )
    from managers.environment_manager import (  # type: ignore[no-redef]
        EnvironmentManager,
    )
    from portainer_client import PortainerAPIError  # type: ignore[no-redef]
    from services.llm_client import LLMClient, LLMClientError  # type: ignore[no-redef]
    from services.llm_context import (  # type: ignore[no-redef]
        DataTable,
        LLMDataHub,
        QueryPlan,
        QueryRequest,
        parse_query_plan,
    )
    from ui_helpers import ExportableDataFrame, render_page_header  # type: ignore[no-redef]


@dataclass(slots=True)
class AssistantTurn:
    """Stores a completed interaction for UI replay."""

    question: str
    answer: str
    plan: str | None = None
    datasets: Sequence[QueryRequest] | None = None
    results_payload: Mapping[str, Any] | None = None


def _prepare_dataframe(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(columns))
    available = [column for column in columns if column in df.columns]
    if not available:
        return pd.DataFrame(columns=list(columns))
    prepared = df.loc[:, available].copy()
    string_columns = prepared.select_dtypes(include=["object", "string"]).columns
    if len(string_columns) > 0:
        prepared[string_columns] = prepared[string_columns].fillna("")
    return prepared


def _build_data_hub(filters: Mapping[str, pd.DataFrame]) -> LLMDataHub:
    tables: list[DataTable] = []

    table_configs = [
        (
            "containers",
            "Containers",
            filters.get("containers"),
            "Container inventory with Portainer metadata, filtered by the current sidebar settings.",
            (
                "environment_name",
                "endpoint_name",
                "container_name",
                "stack_name",
                "state",
                "status",
                "created",
            ),
        ),
        (
            "container_health",
            "Container health",
            filters.get("container_health"),
            "Detailed health checks and resource utilisation for each container.",
            (
                "environment_name",
                "endpoint_name",
                "container_name",
                "health_status",
                "last_exit_code",
                "last_finished_at",
                "cpu_percent",
                "memory_percent",
            ),
        ),
        (
            "stacks",
            "Stacks",
            filters.get("stacks"),
            "Stack definitions and deployment status across environments.",
            (
                "environment_name",
                "endpoint_name",
                "stack_name",
                "stack_status",
                "created_at",
                "updated_at",
            ),
        ),
        (
            "hosts",
            "Hosts",
            filters.get("hosts"),
            "Agent host capacity, CPU and memory footprint, and endpoint details.",
            (
                "environment_name",
                "endpoint_name",
                "host_name",
                "total_cpus",
                "total_memory",
                "architecture",
            ),
        ),
        (
            "endpoints",
            "Endpoints",
            filters.get("endpoints"),
            "Endpoint metadata including platform, status and group membership.",
            (
                "environment_name",
                "endpoint_name",
                "status",
                "endpoint_type",
                "group_name",
            ),
        ),
        (
            "volumes",
            "Volumes",
            filters.get("volumes"),
            "Docker volumes discovered in the selected environments.",
            (
                "environment_name",
                "endpoint_name",
                "volume_name",
                "driver",
                "scope",
                "mountpoint",
            ),
        ),
        (
            "images",
            "Images",
            filters.get("images"),
            "Container images cached by the hosts, including size and creation date.",
            (
                "environment_name",
                "endpoint_name",
                "reference",
                "size",
                "created_at",
                "dangling",
            ),
        ),
    ]

    for name, label, dataframe, description, default_columns in table_configs:
        if dataframe is None or dataframe.empty:
            continue
        prepared = _prepare_dataframe(dataframe, default_columns)
        tables.append(
            DataTable(
                name=name,
                display_name=label,
                dataframe=prepared,
                description=description,
                default_columns=tuple(default_columns),
                searchable_columns=tuple(default_columns),
            )
        )
    return LLMDataHub(tables, max_rows_per_request=1000)


def _build_research_prompt(
    question: str,
    catalog_json: str,
    overview_json: str,
    history: Sequence[AssistantTurn],
) -> list[Mapping[str, str]]:
    messages: list[Mapping[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are an operations co-pilot that builds query plans for a second assistant. "
                "Return **only JSON** with a `plan` field summarising your intent and a `requests` list. "
                "Each request must include the `table` name, optional `filters`, optional `columns`, optional `group_by`, optional `metrics`, and a `limit`. "
                "Prefer aggregated views when many rows might match."
            ),
        }
    ]
    if history:
        trimmed = history[-3:]
        summary_lines = [
            f"Earlier question: {turn.question}\nEarlier answer: {turn.answer}" for turn in trimmed
        ]
        messages.append(
            {
                "role": "system",
                "content": "\n\n".join(summary_lines),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": (
                "Available tables (JSON):\n"
                f"{catalog_json}\n\n"
                "Operational overview (JSON):\n"
                f"{overview_json}\n\n"
                "Question: "
                f"{question.strip()}"
            ),
        }
    )
    return messages


def _build_answer_prompt(
    question: str,
    overview_json: str,
    plan: QueryPlan | None,
    results_payload: Mapping[str, Any],
    history: Sequence[AssistantTurn],
) -> list[Mapping[str, str]]:
    messages: list[Mapping[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a Site Reliability assistant. Use the supplied Portainer data to explain what is happening, highlight risks, and recommend actions. "
                "Do not fabricate data beyond the provided results."
            ),
        }
    ]
    if history:
        trimmed = history[-3:]
        for turn in trimmed:
            messages.extend(
                [
                    {"role": "user", "content": turn.question},
                    {"role": "assistant", "content": turn.answer},
                ]
            )
    if plan and plan.plan:
        messages.append(
            {
                "role": "system",
                "content": f"Data gathering plan that was executed:\n{plan.plan}",
            }
        )
    messages.append(
        {
            "role": "system",
            "content": (
                "Operational overview (JSON):\n"
                f"{overview_json}"
            ),
        }
    )
    messages.append(
        {
            "role": "user",
            "content": (
                f"Question: {question.strip()}\n\n"
                "Data returned from your requests (JSON):\n"
                f"{json.dumps(results_payload, ensure_ascii=False)}"
            ),
        }
    )
    return messages


try:
    CONFIG = get_config()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

require_authentication(CONFIG)
render_logout_button()

render_page_header(
    "AI infrastructure analyst",
    icon="🛰️",
    description=(
        "Let an LLM inspect filtered Portainer data, request the slices it needs, and explain where action is required."
    ),
)

initialise_session_state(CONFIG)
apply_selected_environment(CONFIG)
environment_manager = EnvironmentManager(st.session_state)
environments = environment_manager.initialise()
BackgroundJobRunner().maybe_run_backups(environments)
environment_manager.apply_selected_environment()

conversation: list[AssistantTurn] = st.session_state.setdefault("llm_assistant_turns", [])

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
        include_stopped=True,
        include_container_details=True,
        include_resource_utilisation=True,
    )
except PortainerAPIError as exc:
    st.error(f"Failed to load data from Portainer: {exc}")
    st.stop()

render_data_refresh_notice(data_result)

warnings = tuple(data_result.warnings)
for warning in warnings:
    st.warning(warning, icon="⚠️")

filters = render_sidebar_filters(
    CONFIG,
    data_result.stack_data,
    data_result.container_data,
    endpoint_data=data_result.endpoint_data,
    container_details=data_result.container_details,
    host_data=data_result.host_data,
    volume_data=data_result.volume_data,
    image_data=data_result.image_data,
    data_status=data_result,
)

if filters.stack_data.empty and filters.container_data.empty:
    st.info("No Portainer data matched the current filters.", icon="ℹ️")

filtered_frames = {
    "containers": filters.container_data,
    "container_health": filters.container_details,
    "stacks": filters.stack_data,
    "hosts": filters.host_data,
    "endpoints": filters.endpoint_data,
    "volumes": filters.volume_data,
    "images": filters.image_data,
}

hub = _build_data_hub(filtered_frames)
overview = hub.build_overview()

snapshot_columns = st.columns(4)
snapshot_columns[0].metric(
    "Environments",
    overview.get("issues", {}).get("environments", 0),
)
snapshot_columns[1].metric(
    "Unhealthy containers",
    overview.get("issues", {}).get("unhealthy_containers", 0),
)
snapshot_columns[2].metric(
    "Restarting containers",
    overview.get("issues", {}).get("restarting_containers", 0),
)
container_total = overview.get("containers", {}).get("total", 0)
snapshot_columns[3].metric("Containers", container_total)

hotspots_cpu = overview.get("hotspots_cpu")
if isinstance(hotspots_cpu, pd.DataFrame):
    if not hotspots_cpu.empty:
        st.markdown("### Containers using the most CPU")
        st.dataframe(hotspots_cpu, hide_index=True, width="stretch")
elif hotspots_cpu:
    st.markdown("### Containers using the most CPU")
    st.dataframe(hotspots_cpu, hide_index=True, width="stretch")

hotspots_mem = overview.get("hotspots_memory")
if isinstance(hotspots_mem, pd.DataFrame):
    if not hotspots_mem.empty:
        st.markdown("### Containers using the most memory")
        st.dataframe(hotspots_mem, hide_index=True, width="stretch")
elif hotspots_mem:
    st.markdown("### Containers using the most memory")
    st.dataframe(hotspots_mem, hide_index=True, width="stretch")

catalog = hub.describe_for_llm()
catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
catalog_payload = json.dumps(catalog, ensure_ascii=False)
overview_for_prompt = overview.copy()
if isinstance(hotspots_cpu, pd.DataFrame):
    overview_for_prompt["hotspots_cpu"] = hotspots_cpu.to_dict(orient="records")
if isinstance(hotspots_mem, pd.DataFrame):
    overview_for_prompt["hotspots_memory"] = hotspots_mem.to_dict(orient="records")
overview_json = json.dumps(overview_for_prompt, ensure_ascii=False)

DEFAULT_ENDPOINT = "https://llm.example.com/v1/chat/completions"
SYSTEM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT")
SYSTEM_BEARER_TOKEN = os.getenv("LLM_BEARER_TOKEN")
SYSTEM_CREDENTIALS_LOCKED = bool(SYSTEM_API_ENDPOINT and SYSTEM_BEARER_TOKEN)
LLM_MAX_TOKENS_ENV_VAR = "LLM_MAX_TOKENS"
DEFAULT_MAX_TOKENS_LIMIT = 200000
LARGE_CONTEXT_WARNING_THRESHOLD = 32000

assistant_tab, data_tab = st.tabs(["Ask the assistant", "Datasets shared with the LLM"])

with assistant_tab:
    with st.expander("LLM connection", expanded=not SYSTEM_CREDENTIALS_LOCKED):
        max_tokens_limit = DEFAULT_MAX_TOKENS_LIMIT
        invalid_max_tokens_limit = False
        raw_max_tokens_limit = os.getenv(LLM_MAX_TOKENS_ENV_VAR)
        if raw_max_tokens_limit:
            try:
                max_tokens_limit = max(int(raw_max_tokens_limit), 256)
            except ValueError:
                invalid_max_tokens_limit = True
        api_endpoint = st.text_input(
            "LLM API endpoint",
            value=SYSTEM_API_ENDPOINT or st.session_state.get("llm_api_endpoint", DEFAULT_ENDPOINT),
            help="OpenAI-compatible /v1/chat/completions endpoint exposed by your LLM deployment.",
            disabled=SYSTEM_CREDENTIALS_LOCKED,
        )
        model_name = st.text_input(
            "Model identifier",
            value=st.session_state.get("llm_model", "gpt-oss:latest"),
        )
        if SYSTEM_CREDENTIALS_LOCKED:
            bearer_token = SYSTEM_BEARER_TOKEN or ""
            auth_mode = "Bearer token"
            basic_username = ""
            basic_password = ""
            st.caption("Using the credentials provided via environment variables.")
        else:
            auth_mode = st.selectbox(
                "Authentication",
                options=["Bearer token", "Username/password", "No authentication"],
                index=0,
            )
            bearer_token = st.text_input(
                "Bearer token",
                value=st.session_state.get("llm_bearer_token", ""),
                type="password",
                help="Token issued by your OpenWebUI or Ollama proxy deployment.",
            )
            basic_username = st.text_input(
                "Username",
                value=st.session_state.get("llm_basic_username", ""),
                disabled=auth_mode != "Username/password",
            )
            basic_password = st.text_input(
                "Password",
                value=st.session_state.get("llm_basic_password", ""),
                type="password",
                disabled=auth_mode != "Username/password",
            )
        temperature = st.slider(
            "Creativity",
            min_value=0.0,
            max_value=1.2,
            value=float(st.session_state.get("llm_temperature", 0.2)),
            help="Lower values keep the answer focused on the supplied telemetry.",
        )
        max_tokens = st.slider(
            "Maximum answer length",
            min_value=256,
            max_value=max_tokens_limit,
            value=int(st.session_state.get("llm_max_tokens", 1024)),
            step=256,
        )
        if invalid_max_tokens_limit:
            st.warning(
                f"{LLM_MAX_TOKENS_ENV_VAR} must be set to an integer; using the default limit of "
                f"{DEFAULT_MAX_TOKENS_LIMIT:,} tokens."
            )
        if max_tokens > LARGE_CONTEXT_WARNING_THRESHOLD:
            st.warning(
                "This answer length exceeds 32k tokens. Ensure your model and infrastructure can handle "
                "large responses and plan for longer runtimes.",
                icon="⚠️",
            )
        verify_ssl = st.toggle(
            "Require HTTPS certificates",
            value=bool(st.session_state.get("llm_verify_ssl", True)),
        )

    st.markdown(
        "#### What would you like to investigate?"
    )
    question = st.text_area(
        "Question",
        value="",
        placeholder="e.g. Why are pods in production restarting?",
    )
    max_requests = st.slider(
        "How many dataset requests may the LLM make?",
        min_value=1,
        max_value=6,
        value=int(st.session_state.get("llm_max_requests", 3)),
        help="Higher values allow deeper dives at the cost of longer response times.",
    )
    submit = st.button("Analyse with AI", width="stretch")

    for turn in conversation:
        with st.chat_message("user"):
            st.markdown(turn.question)
        with st.chat_message("assistant"):
            if turn.plan:
                st.caption("Data gathering plan")
                st.markdown(turn.plan)
            st.markdown(turn.answer)

    if submit:
        cleaned_question = question.strip()
        endpoint_clean = api_endpoint.strip()
        if not cleaned_question:
            st.warning("Please enter a question for the assistant.", icon="ℹ️")
        elif not endpoint_clean:
            st.error("Please provide the LLM API endpoint.")
        else:
            token_to_send: str | None = None
            if auth_mode == "Bearer token":
                if not bearer_token.strip():
                    st.error("A bearer token is required to authenticate.")
                    st.stop()
                token_to_send = f"Bearer {bearer_token.strip()}"
            elif auth_mode == "Username/password":
                if not basic_username.strip():
                    st.error("Please supply a username for basic authentication.")
                    st.stop()
                token_to_send = f"{basic_username.strip()}:{basic_password}"
            client = LLMClient(
                base_url=endpoint_clean,
                token=token_to_send,
                model=model_name.strip() or "gpt-oss:latest",
                verify_ssl=verify_ssl,
            )
            with st.spinner("Asking the model which data it needs..."):
                research_messages = _build_research_prompt(
                    cleaned_question,
                    catalog_payload,
                    overview_json,
                    conversation,
                )
                try:
                    plan_text = client.chat(research_messages, temperature=0.0, max_tokens=600)
                except LLMClientError as exc:
                    st.error(f"Failed to plan data retrieval: {exc}")
                    plan_text = ""
                    plan = None
                else:
                    plan = parse_query_plan(plan_text)
                    if plan and plan.warnings:
                        for message in plan.warnings:
                            st.warning(message, icon="⚠️")
                    if plan and plan.notes:
                        for note in plan.notes:
                            st.caption(note)
            executed_requests: list[QueryRequest] = []
            if plan and plan.requests:
                executed_requests = list(plan.requests[:max_requests])
                if len(plan.requests) > max_requests:
                    st.info(
                        "Only the first %s data requests were executed to respect the limit."
                        % max_requests,
                        icon="ℹ️",
                    )
                results = hub.execute_requests(executed_requests)
            else:
                results = []
            results_payload = hub.serialise_results(results)
            with st.spinner("Generating the analysis..."):
                answer_messages = _build_answer_prompt(
                    cleaned_question,
                    overview_json,
                    plan,
                    results_payload,
                    conversation,
                )
                try:
                    answer = client.chat(
                        answer_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except LLMClientError as exc:
                    st.error(f"LLM request failed: {exc}")
                    st.stop()
                    answer = ""
                else:
                    answer = answer.strip()
            if answer:
                turn = AssistantTurn(
                    question=cleaned_question,
                    answer=answer,
                    plan=plan.plan if plan else plan_text,
                    datasets=executed_requests,
                    results_payload=results_payload,
                )
                conversation.append(turn)
                st.session_state["llm_assistant_turns"] = conversation
                st.session_state["llm_api_endpoint"] = endpoint_clean
                st.session_state["llm_model"] = model_name
                st.session_state["llm_bearer_token"] = bearer_token
                st.session_state["llm_basic_username"] = basic_username
                st.session_state["llm_basic_password"] = basic_password
                st.session_state["llm_temperature"] = temperature
                st.session_state["llm_max_tokens"] = max_tokens
                st.session_state["llm_verify_ssl"] = verify_ssl
                st.session_state["llm_max_requests"] = max_requests
                st.rerun()

with data_tab:
    st.markdown("### Tables available to the assistant")
    st.json(catalog)
    for table_name in catalog.keys():
        table_obj = hub.get_table(table_name)
        if not table_obj:
            continue
        st.subheader(table_obj.display_name)
        ExportableDataFrame(
            f"Download {table_obj.name}",
            table_obj.dataframe,
            f"llm_{table_obj.name}.csv",
        ).render_download_button()
        st.dataframe(table_obj.dataframe, hide_index=True, width="stretch")

if conversation and conversation[-1].results_payload:
    st.markdown("### Last analysis payload sent to the model")
    st.json(conversation[-1].results_payload)
