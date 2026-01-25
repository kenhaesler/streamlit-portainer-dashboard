"""Containers API for Docker container data."""

from __future__ import annotations

import logging
import math
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import Container, ContainerDetails
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


@router.get("/", response_model=list[Container])
async def list_containers(
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Filter by environment name")] = None,
    endpoint_id: Annotated[int | None, Query(description="Filter by endpoint ID")] = None,
    include_stopped: Annotated[bool, Query(description="Include stopped containers")] = False,
) -> list[Container]:
    """List all containers across endpoints."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if not environments:
        raise HTTPException(status_code=503, detail="No Portainer environments configured")

    if environment:
        environments = [e for e in environments if e.name == environment]
        if not environments:
            raise HTTPException(status_code=404, detail=f"Environment '{environment}' not found")

    all_endpoints: list[dict] = []
    containers_by_endpoint: dict[int, list[dict]] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()

                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    if endpoint_id is not None and ep_id != endpoint_id:
                        continue

                    all_endpoints.append(ep)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=include_stopped
                        )
                        containers_by_endpoint[ep_id] = containers
                    except PortainerAPIError as exc:
                        LOGGER.debug("Failed to fetch containers for endpoint %d: %s", ep_id, exc)
                        containers_by_endpoint[ep_id] = []
        except PortainerAPIError as exc:
            LOGGER.error("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_containers(all_endpoints, containers_by_endpoint)
    return [Container(**_sanitize_record(row)) for row in df.to_dict("records")]


@router.get("/{endpoint_id}/{container_id}", response_model=ContainerDetails)
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
                    mounts=None,
                    networks=None,
                    labels=None,
                )
        except PortainerAPIError:
            continue

    raise HTTPException(status_code=404, detail="Container not found")


__all__ = ["router"]
