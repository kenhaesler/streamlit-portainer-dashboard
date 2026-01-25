"""WebSocket endpoint for LLM chat streaming."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from portainer_dashboard.config import get_settings
from portainer_dashboard.services.llm_client import (
    AsyncLLMClient,
    LLMClientError,
    create_llm_client,
)
from portainer_dashboard.services.portainer_client import (
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_containers,
    normalise_endpoint_metadata,
    normalise_endpoint_stacks,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()


async def _build_context() -> str:
    """Build a context string with current infrastructure data."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    context_parts: list[str] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                # Get endpoints
                endpoints = await client.list_edge_endpoints()
                df_endpoints = normalise_endpoint_metadata(endpoints)

                online_count = len(df_endpoints[df_endpoints["endpoint_status"] == 1])
                offline_count = len(df_endpoints[df_endpoints["endpoint_status"] != 1])

                context_parts.append(
                    f"Environment '{env.name}' has {len(endpoints)} endpoints "
                    f"({online_count} online, {offline_count} offline)."
                )

                # Get containers for each endpoint
                all_endpoints: list[dict] = []
                containers_by_endpoint: dict[int, list[dict]] = {}
                stacks_by_endpoint: dict[int, list[dict]] = {}

                for ep in endpoints[:10]:  # Limit to first 10 endpoints for context
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    all_endpoints.append(ep)

                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        containers_by_endpoint[ep_id] = containers
                    except PortainerAPIError:
                        containers_by_endpoint[ep_id] = []

                    try:
                        stacks = await client.list_stacks_for_endpoint(ep_id)
                        stacks_by_endpoint[ep_id] = stacks
                    except PortainerAPIError:
                        stacks_by_endpoint[ep_id] = []

                df_containers = normalise_endpoint_containers(
                    all_endpoints, containers_by_endpoint
                )
                df_stacks = normalise_endpoint_stacks(all_endpoints, stacks_by_endpoint)

                running_containers = len(
                    df_containers[df_containers["state"] == "running"]
                )
                total_containers = len(df_containers)
                unique_stacks = df_stacks[df_stacks["stack_name"].notna()][
                    "stack_name"
                ].nunique()

                context_parts.append(
                    f"  - {total_containers} containers ({running_containers} running)"
                )
                context_parts.append(f"  - {unique_stacks} unique stacks")

                # Add some endpoint details
                if not df_endpoints.empty:
                    context_parts.append("  Endpoints:")
                    for _, row in df_endpoints.head(5).iterrows():
                        status = "online" if row["endpoint_status"] == 1 else "offline"
                        context_parts.append(
                            f"    - {row['endpoint_name']}: {status}"
                        )

        except PortainerAPIError as exc:
            context_parts.append(
                f"Environment '{env.name}': Unable to fetch data ({exc})"
            )
            continue

    return "\n".join(context_parts) if context_parts else "No infrastructure data available."


def _build_system_prompt(context: str) -> str:
    """Build the system prompt with infrastructure context."""
    return f"""You are a helpful assistant for managing Portainer infrastructure. You have access to the current state of the infrastructure:

{context}

When answering questions:
1. Be concise and direct
2. Use the provided infrastructure context to answer questions
3. If you don't have enough information, say so
4. Format responses with markdown when helpful
5. For lists of containers or endpoints, use tables when appropriate"""


@router.websocket("/ws/llm/chat")
async def llm_chat_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for LLM chat with streaming responses."""
    await websocket.accept()
    LOGGER.info("LLM chat WebSocket connected")

    settings = get_settings()
    llm_client = create_llm_client(settings.llm)

    if llm_client is None:
        await websocket.send_json({
            "type": "error",
            "content": "LLM is not configured. Please set LLM_API_ENDPOINT.",
        })
        await websocket.close()
        return

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                request = json.loads(data)
                messages = request.get("messages", [])
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "Invalid JSON request",
                })
                continue

            if not messages:
                await websocket.send_json({
                    "type": "error",
                    "content": "No messages provided",
                })
                continue

            try:
                # Build context from infrastructure
                context = await _build_context()
                system_prompt = _build_system_prompt(context)

                # Prepare messages with system prompt
                full_messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt}
                ]
                full_messages.extend(messages)

                # Stream the response
                async for chunk in llm_client.stream_chat(
                    full_messages,
                    max_tokens=settings.llm.max_tokens,
                    temperature=0.2,
                ):
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk,
                    })

                # Signal completion
                await websocket.send_json({
                    "type": "done",
                    "content": "",
                })

            except LLMClientError as exc:
                LOGGER.error("LLM error: %s", exc)
                await websocket.send_json({
                    "type": "error",
                    "content": str(exc),
                })

    except WebSocketDisconnect:
        LOGGER.info("LLM chat WebSocket disconnected")
    except Exception as exc:
        LOGGER.exception("WebSocket error: %s", exc)
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"Internal error: {exc}",
            })
        except Exception:
            pass


__all__ = ["router"]
