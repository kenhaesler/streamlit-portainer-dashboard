"""Stacks API for Portainer stack data."""

from __future__ import annotations

import logging
import math
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import Stack
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
) -> list[Stack]:
    """List all stacks across endpoints."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if not environments:
        raise HTTPException(status_code=503, detail="No Portainer environments configured")

    if environment:
        environments = [e for e in environments if e.name == environment]
        if not environments:
            raise HTTPException(status_code=404, detail=f"Environment '{environment}' not found")

    all_endpoints: list[dict] = []
    stacks_by_endpoint: dict[int, list[dict]] = {}

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
                        stacks = await client.list_stacks_for_endpoint(ep_id)
                        stacks_by_endpoint[ep_id] = stacks
                    except PortainerAPIError as exc:
                        LOGGER.debug("Failed to fetch stacks for endpoint %d: %s", ep_id, exc)
                        stacks_by_endpoint[ep_id] = []
        except PortainerAPIError as exc:
            LOGGER.error("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_stacks(all_endpoints, stacks_by_endpoint)
    return [Stack(**_sanitize_record(row)) for row in df.to_dict("records")]


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
