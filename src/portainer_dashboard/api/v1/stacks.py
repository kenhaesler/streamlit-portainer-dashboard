"""Stacks API for Portainer stack data."""

from __future__ import annotations

import logging
import math
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import Stack
from portainer_dashboard.services.cache_service import get_cache_service
from portainer_dashboard.services.portainer_client import (
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_stacks,
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


@router.get("/", response_model=list[Stack])
async def list_stacks(
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Filter by environment name")] = None,
    endpoint_id: Annotated[int | None, Query(description="Filter by endpoint ID")] = None,
    refresh: Annotated[bool, Query(description="Force cache refresh")] = False,
) -> list[Stack]:
    """List all stacks across endpoints."""
    cache_service = get_cache_service()

    # Use cache service for fetching stacks
    cached_data = await cache_service.get_stacks(force_refresh=refresh)
    stacks_data = cached_data.data

    if cached_data.from_cache:
        LOGGER.debug("Serving stacks from cache (refreshed_at: %s)", cached_data.refreshed_at)

    if not stacks_data:
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()
        if not environments:
            raise HTTPException(status_code=503, detail="No Portainer environments configured")

    # Filter by endpoint_id if specified
    if endpoint_id is not None:
        stacks_data = [
            s for s in stacks_data
            if s.get("endpoint_id") == endpoint_id
        ]

    return [Stack(**_sanitize_record(row)) for row in stacks_data]


@router.get("/{stack_id}/image-status")
async def get_stack_image_status(
    stack_id: int,
    user: CurrentUserDep,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> dict:
    """Get image update status for a specific stack."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if environment:
        environments = [e for e in environments if e.name == environment]

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                status = await client.get_stack_image_status(stack_id)
                return {"stack_id": stack_id, "status": status}
        except PortainerAPIError:
            continue

    raise HTTPException(status_code=404, detail="Stack not found")


__all__ = ["router"]
