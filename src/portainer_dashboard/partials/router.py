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
                endpoints = await client.list_all_endpoints()
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
                endpoints = await client.list_all_endpoints()
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
                endpoints = await client.list_all_endpoints()
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
                endpoints = await client.list_all_endpoints()
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
                endpoints = await client.list_all_endpoints()
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
                endpoints = await client.list_all_endpoints()
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


# Health page partials


@router.get("/health-summary", response_class=HTMLResponse)
async def health_summary_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render health summary cards."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    total_containers = 0
    healthy_containers = 0
    unhealthy_containers = 0
    no_healthcheck = 0

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        for container in containers:
                            if container.get("State") != "running":
                                continue
                            total_containers += 1
                            # Check health status from State field or inspect
                            status = container.get("Status", "")
                            if "(healthy)" in status.lower():
                                healthy_containers += 1
                            elif "(unhealthy)" in status.lower():
                                unhealthy_containers += 1
                            else:
                                no_healthcheck += 1
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    template = jinja.get_template("partials/health_summary.html")
    content = await template.render_async(
        request=request,
        total_containers=total_containers,
        healthy_containers=healthy_containers,
        unhealthy_containers=unhealthy_containers,
        no_healthcheck=no_healthcheck,
    )
    return HTMLResponse(content=content)


@router.get("/health-alerts", response_class=HTMLResponse)
async def health_alerts_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render health alerts."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    alerts: list[dict] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()

                # Check for offline endpoints
                for ep in endpoints:
                    if ep.get("Status") != 1:
                        alerts.append({
                            "type": "error",
                            "title": "Endpoint Offline",
                            "message": f"Endpoint '{ep.get('Name')}' is offline",
                            "endpoint": ep.get("Name"),
                        })

                for ep in endpoints:
                    if ep.get("Status") != 1:
                        continue
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    ep_name = ep.get("Name", "Unknown")
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        for container in containers:
                            names = container.get("Names", [])
                            name = names[0].lstrip("/") if names else "Unknown"
                            status = container.get("Status", "")
                            state = container.get("State", "")

                            if "(unhealthy)" in status.lower():
                                alerts.append({
                                    "type": "warning",
                                    "title": "Unhealthy Container",
                                    "message": f"Container '{name}' on {ep_name} is unhealthy",
                                    "endpoint": ep_name,
                                    "container": name,
                                })
                            elif state != "running":
                                alerts.append({
                                    "type": "info",
                                    "title": "Stopped Container",
                                    "message": f"Container '{name}' on {ep_name} is {state}",
                                    "endpoint": ep_name,
                                    "container": name,
                                })
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    template = jinja.get_template("partials/health_alerts.html")
    content = await template.render_async(
        request=request,
        alerts=alerts[:20],  # Limit to 20 alerts
    )
    return HTMLResponse(content=content)


@router.get("/tables/container-health", response_class=HTMLResponse)
async def container_health_table_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
    health_filter: Annotated[str | None, Query(alias="health-filter")] = None,
) -> HTMLResponse:
    """Render container health table."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    containers_data: list[dict] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    if ep.get("Status") != 1:
                        continue
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    ep_name = ep.get("Name", "Unknown")
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        for container in containers:
                            names = container.get("Names", [])
                            name = names[0].lstrip("/") if names else "Unknown"
                            status = container.get("Status", "")
                            state = container.get("State", "")
                            image = container.get("Image", "Unknown")

                            # Determine health status
                            if "(healthy)" in status.lower():
                                health = "healthy"
                            elif "(unhealthy)" in status.lower():
                                health = "unhealthy"
                            else:
                                health = "none"

                            containers_data.append({
                                "name": name,
                                "endpoint": ep_name,
                                "image": image,
                                "state": state,
                                "status": status,
                                "health": health,
                            })
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    # Apply health filter
    if health_filter:
        containers_data = [c for c in containers_data if c["health"] == health_filter]

    template = jinja.get_template("partials/tables/container_health.html")
    content = await template.render_async(
        request=request,
        containers=containers_data,
    )
    return HTMLResponse(content=content)


# Fleet page chart partials


@router.get("/charts/endpoint-status", response_class=HTMLResponse)
async def endpoint_status_chart_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render endpoint status pie chart."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    online_count = 0
    offline_count = 0

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    if ep.get("Status") == 1:
                        online_count += 1
                    else:
                        offline_count += 1
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    template = jinja.get_template("partials/charts/endpoint_status.html")
    content = await template.render_async(
        request=request,
        online_count=online_count,
        offline_count=offline_count,
    )
    return HTMLResponse(content=content)


@router.get("/charts/agent-versions", response_class=HTMLResponse)
async def agent_versions_chart_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render agent versions bar chart."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    version_counts: dict[str, int] = {}

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    agent = ep.get("Agent") or ep.get("agent") or {}
                    version = agent.get("Version") or agent.get("version") or "Unknown"
                    version_counts[version] = version_counts.get(version, 0) + 1
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    # Sort by version
    sorted_versions = sorted(version_counts.items(), key=lambda x: x[0], reverse=True)

    template = jinja.get_template("partials/charts/agent_versions.html")
    content = await template.render_async(
        request=request,
        versions=sorted_versions,
    )
    return HTMLResponse(content=content)


# Images page partials


@router.get("/image-summary", response_class=HTMLResponse)
async def image_summary_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render image summary cards."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    total_images = 0
    total_size = 0
    dangling_count = 0
    unique_repos: set[str] = set()

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    if ep.get("Status") != 1:
                        continue
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    try:
                        images = await client.list_images_for_endpoint(ep_id)
                        for image in images:
                            total_images += 1
                            size = image.get("Size") or image.get("VirtualSize") or 0
                            total_size += size

                            repo_tags = image.get("RepoTags") or []
                            if repo_tags and repo_tags != ["<none>:<none>"]:
                                for tag in repo_tags:
                                    if ":" in tag:
                                        repo = tag.split(":")[0]
                                        unique_repos.add(repo)
                            else:
                                dangling_count += 1
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    # Convert size to GB
    total_size_gb = round(total_size / (1024 * 1024 * 1024), 2)

    template = jinja.get_template("partials/image_summary.html")
    content = await template.render_async(
        request=request,
        total_images=total_images,
        total_size_gb=total_size_gb,
        dangling_count=dangling_count,
        unique_repos=len(unique_repos),
    )
    return HTMLResponse(content=content)


@router.get("/workload-summary", response_class=HTMLResponse)
async def workload_summary_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render workload summary KPI cards."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    total_containers = 0
    running_containers = 0
    unique_images: set[str] = set()
    total_endpoints = 0

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                total_endpoints += len(endpoints)

                for ep in endpoints:
                    if ep.get("Status") != 1:
                        continue
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    try:
                        containers = await client.list_containers_for_endpoint(
                            ep_id, include_stopped=True
                        )
                        for container in containers:
                            total_containers += 1
                            if container.get("State") == "running":
                                running_containers += 1
                            image = container.get("Image")
                            if image:
                                unique_images.add(image)
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    stopped_containers = total_containers - running_containers

    template = jinja.get_template("partials/workload_summary.html")
    content = await template.render_async(
        request=request,
        total_containers=total_containers,
        running_containers=running_containers,
        stopped_containers=stopped_containers,
        unique_images=len(unique_images),
        total_endpoints=total_endpoints,
    )
    return HTMLResponse(content=content)


@router.get("/charts/workload-distribution", response_class=HTMLResponse)
async def workload_distribution_chart_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render workload distribution chart showing containers per endpoint."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    endpoint_data: list[dict] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()

                for ep in endpoints:
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    ep_name = ep.get("Name") or f"Endpoint {ep_id}"
                    ep_status = ep.get("Status")

                    running_count = 0
                    stopped_count = 0

                    if ep_status == 1:  # Online
                        try:
                            containers = await client.list_containers_for_endpoint(
                                ep_id, include_stopped=True
                            )
                            for container in containers:
                                if container.get("State") == "running":
                                    running_count += 1
                                else:
                                    stopped_count += 1
                        except PortainerAPIError:
                            pass

                    endpoint_data.append({
                        "id": ep_id,
                        "name": ep_name,
                        "running": running_count,
                        "stopped": stopped_count,
                        "total": running_count + stopped_count,
                        "online": ep_status == 1,
                    })
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    # Sort by total containers descending
    endpoint_data.sort(key=lambda x: x["total"], reverse=True)

    template = jinja.get_template("partials/charts/workload_distribution.html")
    content = await template.render_async(
        request=request,
        endpoints=endpoint_data,
    )
    return HTMLResponse(content=content)


@router.get("/charts/image-sizes", response_class=HTMLResponse)
async def image_sizes_chart_partial(
    request: Request,
    jinja: JinjaEnvDep,
    user: CurrentUserDep,
) -> HTMLResponse:
    """Render image size distribution chart."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    image_sizes: list[dict] = []

    for env in environments:
        client = create_portainer_client(env)
        try:
            async with client:
                endpoints = await client.list_all_endpoints()
                for ep in endpoints:
                    if ep.get("Status") != 1:
                        continue
                    ep_id = int(ep.get("Id") or ep.get("id") or 0)
                    try:
                        images = await client.list_images_for_endpoint(ep_id)
                        for image in images:
                            repo_tags = image.get("RepoTags") or []
                            if repo_tags and repo_tags[0] != "<none>:<none>":
                                name = repo_tags[0]
                            else:
                                image_id = image.get("Id") or ""
                                name = image_id[:12] if image_id else "Unknown"

                            size = image.get("Size") or image.get("VirtualSize") or 0
                            size_mb = round(size / (1024 * 1024), 1)

                            image_sizes.append({
                                "name": name,
                                "size_mb": size_mb,
                            })
                    except PortainerAPIError:
                        continue
        except PortainerAPIError as exc:
            LOGGER.debug("Failed to fetch from %s: %s", env.name, exc)
            continue

    # Sort by size descending and take top 10
    image_sizes.sort(key=lambda x: x["size_mb"], reverse=True)
    top_images = image_sizes[:10]

    template = jinja.get_template("partials/charts/image_sizes.html")
    content = await template.render_async(
        request=request,
        images=top_images,
    )
    return HTMLResponse(content=content)


__all__ = ["router"]
