"""WebSocket endpoint for LLM chat streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from portainer_dashboard.config import get_settings
from portainer_dashboard.services.llm_client import (
    AsyncLLMClient,
    LLMClientError,
    create_llm_client,
)
from portainer_dashboard.services.log_sanitizer import sanitize_logs
from portainer_dashboard.services.portainer_client import (
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_containers,
    normalise_endpoint_metadata,
    normalise_endpoint_stacks,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()

# Infrastructure context cache
_CONTEXT_CACHE_TTL_SECONDS = 30.0


@dataclass
class _ContextCache:
    """Cache for infrastructure context to avoid rebuilding on every query."""

    context: str = ""
    timestamp: float = 0.0
    lock: asyncio.Lock | None = None

    def is_valid(self) -> bool:
        """Check if cached context is still valid."""
        return (
            self.context
            and (time.monotonic() - self.timestamp) < _CONTEXT_CACHE_TTL_SECONDS
        )


_context_cache = _ContextCache()


async def _get_context_cache_lock() -> asyncio.Lock:
    """Get or create the cache lock (must be created in async context)."""
    if _context_cache.lock is None:
        _context_cache.lock = asyncio.Lock()
    return _context_cache.lock


def _calculate_cpu_percent(stats: dict) -> float | None:
    """Calculate CPU usage percentage from Docker stats."""
    try:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        cpu_usage = cpu_stats.get("cpu_usage", {})
        precpu_usage = precpu_stats.get("cpu_usage", {})

        cpu_delta = cpu_usage.get("total_usage", 0) - precpu_usage.get("total_usage", 0)
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
            "system_cpu_usage", 0
        )

        if system_delta > 0 and cpu_delta > 0:
            # Get number of CPUs
            online_cpus = cpu_stats.get("online_cpus")
            if not online_cpus:
                percpu = cpu_usage.get("percpu_usage", [])
                online_cpus = len(percpu) if percpu else 1

            cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
            return round(cpu_percent, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return None


def _calculate_memory_usage(stats: dict) -> tuple[float | None, float | None, float | None]:
    """Calculate memory usage from Docker stats.

    Returns: (used_mb, limit_mb, percent)
    """
    try:
        mem_stats = stats.get("memory_stats", {})
        usage = mem_stats.get("usage", 0)
        limit = mem_stats.get("limit", 0)

        # Subtract cache if available (for more accurate "used" memory)
        cache = mem_stats.get("stats", {}).get("cache", 0)
        used = usage - cache

        if limit > 0:
            used_mb = round(used / (1024 * 1024), 1)
            limit_mb = round(limit / (1024 * 1024), 1)
            percent = round((used / limit) * 100, 1)
            return used_mb, limit_mb, percent
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return None, None, None


async def _fetch_container_stats(
    client, endpoint_id: int, container_id: str
) -> dict | None:
    """Fetch stats for a single container, with timeout."""
    try:
        return await asyncio.wait_for(
            client.get_container_stats(endpoint_id, container_id),
            timeout=5.0,
        )
    except (PortainerAPIError, asyncio.TimeoutError) as exc:
        LOGGER.debug("Failed to get stats for container %s: %s", container_id, exc)
        return None


async def _fetch_container_logs(
    client, endpoint_id: int, container_id: str, tail: int = 50
) -> str | None:
    """Fetch recent logs for a container, with timeout."""
    try:
        logs = await asyncio.wait_for(
            client.get_container_logs(
                endpoint_id,
                container_id,
                tail=tail,
                timestamps=True,
            ),
            timeout=10.0,
        )
        return logs if logs and logs.strip() else None
    except (PortainerAPIError, asyncio.TimeoutError) as exc:
        LOGGER.debug("Failed to get logs for container %s: %s", container_id, exc)
        return None


async def _build_context_uncached() -> str:
    """Build a context string with current infrastructure data (no caching)."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    context_parts: list[str] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                # Get ALL endpoints (not just edge endpoints)
                endpoints = await client.list_all_endpoints()
                df_endpoints = normalise_endpoint_metadata(endpoints)

                online_count = len(df_endpoints[df_endpoints["endpoint_status"] == 1])
                offline_count = len(df_endpoints[df_endpoints["endpoint_status"] != 1])

                context_parts.append(
                    f"## Environment '{env.name}'"
                )
                context_parts.append(
                    f"Total endpoints: {len(endpoints)} ({online_count} online, {offline_count} offline)"
                )

                # Get containers and stacks for each endpoint in parallel
                all_endpoints: list[dict] = list(endpoints[:10])  # Limit to first 10 endpoints for context
                containers_by_endpoint: dict[int, list[dict]] = {}
                stacks_by_endpoint: dict[int, list[dict]] = {}

                async def fetch_endpoint_data(ep: dict) -> tuple[int, list[dict], list[dict]]:
                    """Fetch containers and stacks for a single endpoint."""
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    containers: list[dict] = []
                    stacks: list[dict] = []

                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                    except PortainerAPIError:
                        pass

                    try:
                        stacks = await client.list_stacks_for_endpoint(ep_id)
                    except PortainerAPIError:
                        pass

                    return ep_id, containers, stacks

                # Fetch all endpoint data in parallel
                results = await asyncio.gather(
                    *[fetch_endpoint_data(ep) for ep in all_endpoints],
                    return_exceptions=True
                )

                for result in results:
                    if isinstance(result, Exception):
                        LOGGER.debug("Endpoint data fetch error: %s", result)
                        continue
                    ep_id, containers, stacks = result
                    containers_by_endpoint[ep_id] = containers
                    stacks_by_endpoint[ep_id] = stacks

                df_containers = normalise_endpoint_containers(
                    all_endpoints, containers_by_endpoint
                )
                df_stacks = normalise_endpoint_stacks(all_endpoints, stacks_by_endpoint)

                running_containers = len(
                    df_containers[df_containers["state"] == "running"]
                )
                stopped_containers = len(
                    df_containers[df_containers["state"] != "running"]
                )
                total_containers = len(df_containers)
                unique_stacks = df_stacks[df_stacks["stack_name"].notna()][
                    "stack_name"
                ].nunique()

                context_parts.append(
                    f"Total containers: {total_containers} ({running_containers} running, {stopped_containers} stopped)"
                )
                context_parts.append(f"Total stacks: {unique_stacks}")

                # Add endpoint details
                if not df_endpoints.empty:
                    context_parts.append("\n### Endpoints:")
                    for _, row in df_endpoints.iterrows():
                        status = "online" if row["endpoint_status"] == 1 else "offline"
                        context_parts.append(
                            f"- **{row['endpoint_name']}**: {status}"
                        )

                # Fetch container stats for running containers
                container_stats: dict[str, dict] = {}
                running_container_ids = []
                for _, row in df_containers.iterrows():
                    if row.get("state") == "running":
                        cid = row.get("container_id")
                        ep_id = row.get("endpoint_id")
                        if cid and ep_id:
                            running_container_ids.append((ep_id, cid))

                # Fetch stats in parallel (with timeout)
                if running_container_ids:
                    stats_tasks = [
                        _fetch_container_stats(client, ep_id, cid)
                        for ep_id, cid in running_container_ids
                    ]
                    stats_results = await asyncio.gather(*stats_tasks)
                    for (_, cid), stats in zip(running_container_ids, stats_results):
                        if stats:
                            container_stats[cid] = stats

                # Identify stopped/unhealthy/restarting containers that need logs
                stopped_container_ids: list[tuple[int, str, str]] = []
                for _, row in df_containers.iterrows():
                    state = row.get("state", "")
                    status = row.get("status", "")
                    cid = row.get("container_id")
                    ep_id = row.get("endpoint_id")
                    name = row.get("container_name", "unknown")

                    # Fetch logs for stopped, exited, restarting, or unhealthy containers
                    if cid and ep_id and state in ("exited", "dead", "created", "restarting"):
                        stopped_container_ids.append((ep_id, cid, name))
                    elif cid and ep_id and "unhealthy" in status.lower():
                        stopped_container_ids.append((ep_id, cid, name))

                # Fetch logs for stopped/unhealthy/restarting containers (limit to 5 to avoid timeout)
                container_logs: dict[str, str] = {}
                if stopped_container_ids:
                    logs_tasks = [
                        _fetch_container_logs(client, ep_id, cid, tail=50)
                        for ep_id, cid, _ in stopped_container_ids[:5]
                    ]
                    logs_results = await asyncio.gather(*logs_tasks)
                    for (_, cid, _), logs in zip(stopped_container_ids[:5], logs_results):
                        if logs:
                            container_logs[cid] = logs

                # Add container details
                if not df_containers.empty:
                    context_parts.append("\n### Containers:")
                    for _, row in df_containers.iterrows():
                        name = row.get("container_name", "unknown")
                        image = row.get("image", "unknown")
                        state = row.get("state", "unknown")
                        status = row.get("status", "")
                        endpoint = row.get("endpoint_name", "unknown")
                        cid = row.get("container_id")

                        context_parts.append(
                            f"- **{name}** (endpoint: {endpoint})"
                        )
                        context_parts.append(
                            f"  - Image: {image}"
                        )
                        context_parts.append(
                            f"  - State: {state} ({status})"
                        )

                        # Add resource stats if available
                        if cid and cid in container_stats:
                            stats = container_stats[cid]
                            cpu_percent = _calculate_cpu_percent(stats)
                            mem_used, mem_limit, mem_percent = _calculate_memory_usage(stats)

                            if cpu_percent is not None:
                                context_parts.append(f"  - CPU: {cpu_percent}%")
                            if mem_used is not None and mem_limit is not None:
                                context_parts.append(
                                    f"  - Memory: {mem_used}MB / {mem_limit}MB ({mem_percent}%)"
                                )

                        # Add logs for stopped/unhealthy containers
                        if cid and cid in container_logs:
                            logs = container_logs[cid]
                            # Sanitize logs to remove potential secrets
                            logs = sanitize_logs(logs)
                            # Truncate logs to last 20 lines for context
                            log_lines = logs.strip().split("\n")[-20:]
                            truncated_logs = "\n".join(log_lines)
                            context_parts.append(f"  - **Recent Logs:**")
                            context_parts.append(f"```\n{truncated_logs}\n```")

                # Add stack details
                if not df_stacks.empty and unique_stacks > 0:
                    context_parts.append("\n### Stacks:")
                    seen_stacks = set()
                    for _, row in df_stacks.iterrows():
                        stack_name = row.get("stack_name")
                        if stack_name and stack_name not in seen_stacks:
                            seen_stacks.add(stack_name)
                            stack_status = row.get("stack_status", "unknown")
                            context_parts.append(
                                f"- **{stack_name}**: {stack_status}"
                            )

        except PortainerAPIError as exc:
            context_parts.append(
                f"Environment '{env.name}': Unable to fetch data ({exc})"
            )
            LOGGER.error("Failed to fetch Portainer data: %s", exc)
            continue

    return "\n".join(context_parts) if context_parts else "No infrastructure data available."


async def _build_context() -> str:
    """Build context with caching to avoid rebuilding on every query.

    Uses a 30-second TTL cache to reduce Portainer API load while keeping
    data reasonably fresh for interactive chat.
    """
    global _context_cache

    # Check if cache is valid
    if _context_cache.is_valid():
        LOGGER.debug("Using cached infrastructure context (age: %.1fs)",
                     time.monotonic() - _context_cache.timestamp)
        return _context_cache.context

    # Acquire lock to prevent concurrent rebuilds
    lock = await _get_context_cache_lock()
    async with lock:
        # Double-check after acquiring lock
        if _context_cache.is_valid():
            return _context_cache.context

        LOGGER.debug("Building fresh infrastructure context")
        context = await _build_context_uncached()

        # Update cache
        _context_cache.context = context
        _context_cache.timestamp = time.monotonic()

        return context


def _build_system_prompt(context: str) -> str:
    """Build the system prompt with infrastructure context and few-shot examples."""
    return f"""You are a helpful assistant for managing Portainer infrastructure. You have access to the current state of the infrastructure, including container logs for stopped, unhealthy, or restarting containers:

{context}

When answering questions:
1. Be concise and direct
2. Use the provided infrastructure context to answer questions
3. When a container is stopped, unhealthy, or restarting (crash loop), check the "Recent Logs" section for that container to diagnose the issue
4. Analyze log output to identify errors, exceptions, or failure reasons
5. If you don't have enough information, say so
6. Format responses with markdown when helpful
7. For lists of containers or endpoints, use tables when appropriate
8. When diagnosing container failures, look for: error messages, stack traces, exit codes, permission issues, missing files, connection failures, or OOM kills

## Example Interactions

**User:** How many containers are running?
**Assistant:** Based on the current infrastructure data, there are **12 containers running** across 3 endpoints. Here's the breakdown:

| Endpoint | Running | Stopped |
|----------|---------|---------|
| prod-server-1 | 5 | 1 |
| prod-server-2 | 4 | 0 |
| dev-server | 3 | 2 |

---

**User:** Why is my-app container stopped?
**Assistant:** The **my-app** container on endpoint **prod-server-1** exited with an error. Looking at the recent logs:

**Root Cause:** The container failed to connect to the database.
```
Error: Connection refused to postgres:5432
```

**Recommended Actions:**
1. Verify the postgres container is running
2. Check network connectivity between containers
3. Ensure database credentials are correct

---

**User:** Show me unhealthy containers
**Assistant:** Found **2 unhealthy containers**:

| Container | Endpoint | Status | Issue |
|-----------|----------|--------|-------|
| api-gateway | prod-server-1 | unhealthy | Health check timeout |
| worker-queue | prod-server-2 | unhealthy | Port 8080 not responding |

Check the health check configuration and container logs for more details."""


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
