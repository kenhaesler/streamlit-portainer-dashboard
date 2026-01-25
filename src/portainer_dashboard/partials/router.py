"""HTMX partial routes for dynamic content loading."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.dependencies import JinjaEnvDep
from portainer_dashboard.services.portainer_client import (
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_containers,
    normalise_endpoint_images,
    normalise_endpoint_metadata,
    normalise_endpoint_stacks,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
    environment: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Render metrics cards."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if environment:
        environments = [e for e in environments if e.name == environment]

    total_endpoints = 0
    online_endpoints = 0
    total_containers = 0
    running_containers = 0

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                total_endpoints += len(endpoints)
                online_endpoints += sum(
                    1 for e in endpoints if e.get("Status") == 1
                )

                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        total_containers += len(containers)
                        running_containers += sum(
                            1 for c in containers if c.get("State") == "running"
                        )
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    template = jinja.get_template("partials/metrics.html")
    content = await template.render_async(
        request=request,
        total_endpoints=total_endpoints,
        online_endpoints=online_endpoints,
        total_containers=total_containers,
        running_containers=running_containers,
    )
    return HTMLResponse(content=content)


@router.get("/tables/endpoints", response_class=HTMLResponse)
async def endpoints_table_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
    search: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status-filter")] = None,
) -> HTMLResponse:
    """Render endpoints table."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    all_endpoints: list[dict] = []
    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                all_endpoints.extend(endpoints)
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_metadata(all_endpoints)

    # Apply filters
    if search:
        search_lower = search.lower()
        df = df[
            df["endpoint_name"].str.lower().str.contains(search_lower, na=False)
            | df["agent_hostname"].str.lower().str.contains(search_lower, na=False)
        ]

    if status_filter:
        df = df[df["endpoint_status"] == int(status_filter)]

    endpoints = df.to_dict("records")

    template = jinja.get_template("partials/tables/endpoints.html")
    content = await template.render_async(
        request=request,
        endpoints=endpoints,
    )
    return HTMLResponse(content=content)


@router.get("/tables/stacks", response_class=HTMLResponse)
async def stacks_table_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render stacks table."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    all_endpoints: list[dict] = []
    stacks_by_endpoint: dict[int, list[dict]] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    all_endpoints.append(ep)
                    try:
                        stacks = await client.list_stacks_for_endpoint(ep_id)
                        stacks_by_endpoint[ep_id] = stacks
                    except PortainerAPIError:
                        stacks_by_endpoint[ep_id] = []
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_stacks(all_endpoints, stacks_by_endpoint)
    stacks = df.to_dict("records")

    template = jinja.get_template("partials/tables/stacks.html")
    content = await template.render_async(
        request=request,
        stacks=stacks,
    )
    return HTMLResponse(content=content)


@router.get("/tables/containers", response_class=HTMLResponse)
async def containers_table_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
    search: Annotated[str | None, Query()] = None,
    state_filter: Annotated[str | None, Query(alias="state-filter")] = None,
    endpoint_filter: Annotated[int | None, Query(alias="endpoint-filter")] = None,
    include_stopped: Annotated[bool, Query(alias="include-stopped")] = False,
) -> HTMLResponse:
    """Render containers table."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    all_endpoints: list[dict] = []
    containers_by_endpoint: dict[int, list[dict]] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    if endpoint_filter is not None and ep_id != endpoint_filter:
                        continue
                    all_endpoints.append(ep)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=include_stopped
                        )
                        containers_by_endpoint[ep_id] = containers
                    except PortainerAPIError:
                        containers_by_endpoint[ep_id] = []
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_containers(all_endpoints, containers_by_endpoint)

    # Apply filters
    if search:
        search_lower = search.lower()
        df = df[
            df["container_name"].str.lower().str.contains(search_lower, na=False)
            | df["image"].str.lower().str.contains(search_lower, na=False)
        ]

    if state_filter:
        df = df[df["state"].str.lower() == state_filter.lower()]

    containers = df.to_dict("records")

    template = jinja.get_template("partials/tables/containers.html")
    content = await template.render_async(
        request=request,
        containers=containers,
    )
    return HTMLResponse(content=content)


@router.get("/tables/images", response_class=HTMLResponse)
async def images_table_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
    search: Annotated[str | None, Query()] = None,
    show_dangling: Annotated[bool, Query(alias="show-dangling")] = False,
) -> HTMLResponse:
    """Render images table."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    all_endpoints: list[dict] = []
    images_by_endpoint: dict[int, list[dict]] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    all_endpoints.append(ep)
                    try:
                        images = await client.list_images_for_endpoint(ep_id)
                        images_by_endpoint[ep_id] = images
                    except PortainerAPIError:
                        images_by_endpoint[ep_id] = []
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    df = normalise_endpoint_images(all_endpoints, images_by_endpoint)

    # Apply filters
    if search:
        search_lower = search.lower()
        df = df[df["reference"].str.lower().str.contains(search_lower, na=False)]

    if show_dangling:
        df = df[df["dangling"] == True]

    images = df.to_dict("records")

    template = jinja.get_template("partials/tables/images.html")
    content = await template.render_async(
        request=request,
        images=images,
    )
    return HTMLResponse(content=content)


@router.get("/tables/recent-containers", response_class=HTMLResponse)
async def recent_containers_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render recent containers table for home page."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    all_endpoints: list[dict] = []
    containers_by_endpoint: dict[int, list[dict]] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_edge_endpoints()
                for ep in endpoints[:5]:  # Limit to first 5 endpoints
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    all_endpoints.append(ep)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=False
                        )
                        containers_by_endpoint[ep_id] = containers[:10]  # Limit
                    except PortainerAPIError:
                        containers_by_endpoint[ep_id] = []
        except PortainerAPIError:
            continue

    df = normalise_endpoint_containers(all_endpoints, containers_by_endpoint)
    containers = df.head(10).to_dict("records")

    template = jinja.get_template("partials/tables/recent_containers.html")
    content = await template.render_async(
        request=request,
        containers=containers,
    )
    return HTMLResponse(content=content)


@router.get("/backup-list", response_class=HTMLResponse)
async def backup_list_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render backup list."""
    from portainer_dashboard.services.backup_service import create_backup_service

    backup_service = create_backup_service()
    backups = backup_service.list_backups()

    template = jinja.get_template("partials/backup_list.html")
    content = await template.render_async(
        request=request,
        backups=backups,
    )
    return HTMLResponse(content=content)


__all__ = ["router"]
