"""Dashboard API endpoints for aggregated data fetching.

Provides batch endpoints to reduce frontend round-trips by fetching
multiple data types in a single request using parallel operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from portainer_dashboard.auth.dependencies import require_authenticated
from portainer_dashboard.services.cache_service import get_cache_service

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "/overview",
    summary="Get dashboard overview data",
    dependencies=[Depends(require_authenticated)],
)
async def get_dashboard_overview() -> dict[str, Any]:
    """Get all dashboard data in a single request.

    Fetches endpoints, containers, and stacks in parallel for optimal
    performance. This reduces frontend round-trips from 3 to 1.

    Returns:
        Dictionary containing:
        - endpoints: List of endpoint data
        - containers: List of container data (including stopped)
        - stacks: List of stack data
        - metadata: Timing and cache information
    """
    start_time = time.time()
    cache_service = get_cache_service()

    # Fetch all data in parallel
    endpoints_task = cache_service.get_endpoints()
    containers_task = cache_service.get_containers(include_stopped=True)
    stacks_task = cache_service.get_stacks()

    endpoints_result, containers_result, stacks_result = await asyncio.gather(
        endpoints_task,
        containers_task,
        stacks_task,
    )

    elapsed = time.time() - start_time
    LOGGER.debug("Dashboard overview fetched in %.2f seconds", elapsed)

    return {
        "endpoints": endpoints_result.data,
        "containers": containers_result.data,
        "stacks": stacks_result.data,
        "metadata": {
            "fetch_time_ms": round(elapsed * 1000, 2),
            "endpoints_from_cache": endpoints_result.from_cache,
            "containers_from_cache": containers_result.from_cache,
            "stacks_from_cache": stacks_result.from_cache,
            "endpoints_refreshed_at": endpoints_result.refreshed_at,
            "containers_refreshed_at": containers_result.refreshed_at,
            "stacks_refreshed_at": stacks_result.refreshed_at,
        },
    }


@router.get(
    "/summary",
    summary="Get dashboard summary statistics",
    dependencies=[Depends(require_authenticated)],
)
async def get_dashboard_summary() -> dict[str, Any]:
    """Get summary statistics for the dashboard.

    Returns high-level counts and status information without full data payloads.
    Useful for quick status checks and header displays.

    Returns:
        Dictionary containing:
        - endpoint_count: Total number of endpoints
        - endpoints_online: Number of online endpoints
        - endpoints_offline: Number of offline endpoints
        - container_count: Total number of containers
        - containers_running: Number of running containers
        - containers_stopped: Number of stopped containers
        - stack_count: Number of unique stacks
    """
    start_time = time.time()
    cache_service = get_cache_service()

    # Fetch all data in parallel
    endpoints_result, containers_result, stacks_result = await asyncio.gather(
        cache_service.get_endpoints(),
        cache_service.get_containers(include_stopped=True),
        cache_service.get_stacks(),
    )

    # Calculate statistics
    endpoints = endpoints_result.data
    containers = containers_result.data
    stacks = stacks_result.data

    endpoints_online = sum(1 for e in endpoints if e.get("endpoint_status") == 1)
    endpoints_offline = len(endpoints) - endpoints_online

    containers_running = sum(1 for c in containers if c.get("state") == "running")
    containers_stopped = len(containers) - containers_running

    # Count unique stacks
    unique_stacks = set()
    for s in stacks:
        stack_name = s.get("stack_name")
        if stack_name:
            unique_stacks.add(stack_name)

    elapsed = time.time() - start_time

    return {
        "endpoint_count": len(endpoints),
        "endpoints_online": endpoints_online,
        "endpoints_offline": endpoints_offline,
        "container_count": len(containers),
        "containers_running": containers_running,
        "containers_stopped": containers_stopped,
        "stack_count": len(unique_stacks),
        "metadata": {
            "fetch_time_ms": round(elapsed * 1000, 2),
            "from_cache": all([
                endpoints_result.from_cache,
                containers_result.from_cache,
                stacks_result.from_cache,
            ]),
        },
    }


__all__ = ["router"]
