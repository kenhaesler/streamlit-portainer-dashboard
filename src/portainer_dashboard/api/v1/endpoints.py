"""Endpoints API for Portainer environment data."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import Endpoint, HostMetrics
from portainer_dashboard.services.cache_service import get_cache_service
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_metadata,
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


async def _get_endpoints_for_environment(
    env_name: str | None = None,
    force_refresh: bool = False,
) -> list[Endpoint]:
    """Fetch endpoints from Portainer with caching."""
    cache_service = get_cache_service()

    # Use cache service for fetching endpoints
    cached_data = await cache_service.get_endpoints(force_refresh=force_refresh)
    endpoints_data = cached_data.data

    if cached_data.from_cache:
        LOGGER.debug("Serving endpoints from cache (refreshed_at: %s)", cached_data.refreshed_at)

    if not endpoints_data:
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()
        if not environments:
            raise HTTPException(status_code=503, detail="No Portainer environments configured")

    # Filter by environment name if specified
    if env_name:
        # Note: Currently cache doesn't track environment, so we filter post-fetch
        # For multi-environment setups, this might need enhancement
        pass

    return [Endpoint(**_sanitize_record(row)) for row in endpoints_data]


@router.get("/", response_model=list[Endpoint])
async def list_endpoints(
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Filter by environment name")] = None,
    refresh: Annotated[bool, Query(description="Force cache refresh")] = False,
) -> list[Endpoint]:
    """List all Portainer endpoints (edge agents)."""
    return await _get_endpoints_for_environment(environment, force_refresh=refresh)


@router.get("/{endpoint_id}", response_model=Endpoint)
async def get_endpoint(
    endpoint_id: int,
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> Endpoint:
    """Get a specific endpoint by ID."""
    endpoints = await _get_endpoints_for_environment(environment)
    for endpoint in endpoints:
        if endpoint.endpoint_id == endpoint_id:
            return endpoint
    raise HTTPException(status_code=404, detail="Endpoint not found")


@router.get("/{endpoint_id}/host-metrics", response_model=HostMetrics)
async def get_endpoint_host_metrics(
    endpoint_id: int,
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> HostMetrics:
    """Get host metrics for a specific endpoint."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if environment:
        environments = [e for e in environments if e.name == environment]

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                info = await client.get_endpoint_host_info(endpoint_id)
                system_df = await client.get_endpoint_system_df(endpoint_id)

                # Build host metrics
                containers_section = system_df.get("Containers", {})
                return HostMetrics(
                    endpoint_id=endpoint_id,
                    endpoint_name=None,
                    docker_version=info.get("ServerVersion"),
                    architecture=info.get("Architecture"),
                    operating_system=info.get("OperatingSystem"),
                    total_cpus=info.get("NCPU"),
                    total_memory=info.get("MemTotal"),
                    swarm_node=info.get("Swarm", {}).get("ControlAvailable")
                    if isinstance(info.get("Swarm"), dict)
                    else None,
                    containers_total=containers_section.get("Total")
                    if isinstance(containers_section, dict)
                    else None,
                    containers_running=containers_section.get("Running")
                    if isinstance(containers_section, dict)
                    else None,
                    containers_stopped=containers_section.get("Stopped")
                    if isinstance(containers_section, dict)
                    else None,
                    volumes_total=system_df.get("Volumes", {}).get("TotalCount")
                    if isinstance(system_df.get("Volumes"), dict)
                    else None,
                    images_total=system_df.get("ImagesTotal"),
                    layers_size=system_df.get("LayersSize"),
                )
        except PortainerAPIError:
            continue

    raise HTTPException(status_code=404, detail="Endpoint not found or not accessible")


__all__ = ["router"]
