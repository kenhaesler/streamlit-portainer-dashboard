"""Containers API for Docker container data."""

from __future__ import annotations

import logging
import math
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import Container, ContainerDetails, ContainerLogsResponse
from portainer_dashboard.services.cache_service import get_cache_service
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_containers,
)

LOGGER = logging.getLogger(__name__)


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN/inf values with None for Pydantic compatibility."""
    sanitized = {}
    for key, value in record.items():
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            sanitized[key] = None
        else:
            sanitized[key] = value
    return sanitized

router = APIRouter()


@router.get(
    "/",
    response_model=list[Container],
    summary="List all containers",
    description="Retrieve all Docker containers across all Portainer endpoints. "
    "Includes container name, image, state, health status, ports, and resource usage. "
    "Results are cached for performance; use refresh=true to force a cache update.",
)
async def list_containers(
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Filter by environment name")] = None,
    endpoint_id: Annotated[int | None, Query(description="Filter by endpoint ID")] = None,
    include_stopped: Annotated[bool, Query(description="Include stopped containers")] = False,
    refresh: Annotated[bool, Query(description="Force cache refresh")] = False,
) -> list[Container]:
    """List all containers across endpoints."""
    cache_service = get_cache_service()

    # Use cache service for fetching containers
    cached_data = await cache_service.get_containers(
        include_stopped=include_stopped,
        force_refresh=refresh,
    )
    containers_data = cached_data.data

    if cached_data.from_cache:
        LOGGER.debug("Serving containers from cache (refreshed_at: %s)", cached_data.refreshed_at)

    if not containers_data:
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()
        if not environments:
            raise HTTPException(status_code=503, detail="No Portainer environments configured")

    # Filter by endpoint_id if specified
    if endpoint_id is not None:
        containers_data = [
            c for c in containers_data
            if c.get("endpoint_id") == endpoint_id
        ]

    return [Container(**_sanitize_record(row)) for row in containers_data]


@router.get(
    "/{endpoint_id}/{container_id}",
    response_model=ContainerDetails,
    summary="Get container details",
    description="Retrieve detailed information for a specific container including "
    "environment variables, network configuration, volume mounts, labels, "
    "health status, and real-time CPU/memory usage.",
)
async def get_container_details(
    endpoint_id: int,
    container_id: str,
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> ContainerDetails:
    """Get detailed information for a specific container."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if environment:
        environments = [e for e in environments if e.name == environment]

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                inspect_data = await client.inspect_container(endpoint_id, container_id)
                stats_data = await client.get_container_stats(endpoint_id, container_id)

                # Extract data from inspect
                state = inspect_data.get("State") or {}
                if not isinstance(state, dict):
                    state = {}
                health = state.get("Health") or {}
                if not isinstance(health, dict):
                    health = {}

                config = inspect_data.get("Config") or {}
                if not isinstance(config, dict):
                    config = {}
                host_config = inspect_data.get("HostConfig") or {}
                if not isinstance(host_config, dict):
                    host_config = {}
                network_settings = inspect_data.get("NetworkSettings") or {}
                if not isinstance(network_settings, dict):
                    network_settings = {}

                # Calculate CPU percentage
                cpu_stats = stats_data.get("cpu_stats") or {}
                precpu_stats = stats_data.get("precpu_stats") or {}
                cpu_percent = None
                if cpu_stats and precpu_stats:
                    total_usage = cpu_stats.get("cpu_usage", {}).get("total_usage")
                    pre_total = precpu_stats.get("cpu_usage", {}).get("total_usage")
                    system_usage = cpu_stats.get("system_cpu_usage")
                    pre_system = precpu_stats.get("system_cpu_usage")
                    if all(v is not None for v in [total_usage, pre_total, system_usage, pre_system]):
                        cpu_delta = float(total_usage) - float(pre_total)
                        system_delta = float(system_usage) - float(pre_system)
                        if system_delta > 0:
                            percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage")
                            cpu_count = len(percpu) if isinstance(percpu, list) and percpu else 1
                            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

                # Calculate memory percentage
                memory_stats = stats_data.get("memory_stats") or {}
                memory_usage = memory_stats.get("usage")
                memory_limit = memory_stats.get("limit")
                memory_percent = None
                if memory_usage and memory_limit:
                    memory_percent = (float(memory_usage) / float(memory_limit)) * 100.0

                # Extract restart policy
                restart_policy = host_config.get("RestartPolicy", {})
                restart_policy_name = restart_policy.get("Name") if isinstance(restart_policy, dict) else None

                return ContainerDetails(
                    endpoint_id=endpoint_id,
                    endpoint_name=None,
                    container_id=container_id,
                    container_name=inspect_data.get("Name", "").lstrip("/"),
                    health_status=health.get("Status"),
                    last_exit_code=state.get("ExitCode"),
                    last_finished_at=state.get("FinishedAt"),
                    cpu_percent=cpu_percent,
                    memory_usage=memory_usage,
                    memory_limit=memory_limit,
                    memory_percent=memory_percent,
                    environment=config.get("Env"),
                    networks=network_settings.get("Networks"),
                    mounts=inspect_data.get("Mounts"),
                    labels=config.get("Labels"),
                    restart_policy=restart_policy_name,
                    privileged=host_config.get("Privileged"),
                    image=config.get("Image"),
                    state=state.get("Status"),
                    status=state.get("Status"),
                )
        except PortainerAPIError:
            continue

    raise HTTPException(status_code=404, detail="Container not found")


@router.get(
    "/{endpoint_id}/{container_id}/logs",
    response_model=ContainerLogsResponse,
    summary="Get container logs",
    description="Retrieve container logs directly from Docker via Portainer API. "
    "Supports tail (last N lines), timestamps, and time-based filtering (since N minutes ago).",
)
async def get_container_logs(
    endpoint_id: int,
    container_id: str,
    user: CurrentUserDep,
    tail: Annotated[int, Query(ge=1, le=10000, description="Number of lines to return")] = 500,
    timestamps: Annotated[bool, Query(description="Include timestamps")] = True,
    since_minutes: Annotated[int | None, Query(ge=1, le=1440, description="Return logs since N minutes ago")] = None,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> ContainerLogsResponse:
    """Get container logs directly from Docker API via Portainer."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if environment:
        environments = [e for e in environments if e.name == environment]

    since_timestamp = None
    if since_minutes is not None:
        since_timestamp = int(time.time()) - (since_minutes * 60)

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                # Get container name for the response
                try:
                    inspect_data = await client.inspect_container(endpoint_id, container_id)
                    container_name = inspect_data.get("Name", "").lstrip("/")
                except PortainerAPIError:
                    container_name = None

                logs = await client.get_container_logs(
                    endpoint_id,
                    container_id,
                    tail=tail,
                    timestamps=timestamps,
                    since=since_timestamp,
                )

                return ContainerLogsResponse(
                    endpoint_id=endpoint_id,
                    container_id=container_id,
                    container_name=container_name,
                    logs=logs,
                    tail=tail,
                    timestamps=timestamps,
                )
        except PortainerAPIError:
            continue

    raise HTTPException(status_code=404, detail="Container not found")


__all__ = ["router"]
