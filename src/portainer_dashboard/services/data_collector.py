"""Infrastructure data collector for monitoring."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.monitoring import (
    ContainerCapabilities,
    ContainerLogs,
    ImageStatus,
    InfrastructureSnapshot,
)
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    _determine_edge_agent_status,
    create_portainer_client,
    normalise_endpoint_containers,
    normalise_endpoint_metadata,
)
from portainer_dashboard.services.security_scanner import (
    SecurityScanner,
    _is_excluded_container,
    create_security_scanner,
)

LOGGER = logging.getLogger(__name__)


def _is_problematic_container(container: dict) -> tuple[bool, str, int | None]:
    """Check if a container should have its logs analyzed.

    Returns:
        Tuple of (is_problematic, state_category, exit_code).
        state_category is one of: "unhealthy", "exited_error", "restarting", "dead"
    """
    state = container.get("State", "").lower()
    status = container.get("Status", "")
    if isinstance(status, str):
        status = status.lower()
    else:
        status = ""

    # Check for unhealthy containers
    if "unhealthy" in status:
        return True, "unhealthy", None

    # Check for restarting containers
    if state == "restarting" or "restarting" in status:
        return True, "restarting", None

    # Check for dead containers
    if state == "dead":
        return True, "dead", None

    # Check for exited containers with non-zero exit code
    if state == "exited":
        # Try to extract exit code from status like "Exited (1) 5 minutes ago"
        exit_code = None
        if "(" in status and ")" in status:
            try:
                code_str = status.split("(")[1].split(")")[0]
                exit_code = int(code_str)
            except (IndexError, ValueError):
                pass

        # Also check the container's detailed exit code if available
        if exit_code is None:
            exit_code = container.get("ExitCode")

        if exit_code is not None and exit_code != 0:
            return True, "exited_error", exit_code

    return False, "", None


@dataclass
class DataCollector:
    """Collects infrastructure data from Portainer for monitoring analysis."""

    security_scanner: SecurityScanner
    include_security_scan: bool = True
    include_image_check: bool = True
    include_log_analysis: bool = True
    log_tail_lines: int = 100
    max_containers_for_logs: int = 10
    log_fetch_timeout: float = 10.0
    max_endpoints_per_env: int = 50
    container_fetch_timeout: float = 60.0  # Increased from 30s to handle slow API responses
    excluded_containers: frozenset[str] = frozenset()

    async def collect_endpoint_data(
        self,
        client: AsyncPortainerClient,
        endpoint: dict,
    ) -> tuple[list[dict], list[ContainerCapabilities]]:
        """Collect container data and security issues for a single endpoint."""
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        # Use _determine_edge_agent_status for proper edge agent detection
        raw_status = endpoint.get("Status") or endpoint.get("status")
        endpoint_status = _determine_edge_agent_status(endpoint, raw_status)

        if endpoint_status != 1:
            LOGGER.debug(
                "Skipping offline endpoint %s (status=%s)",
                endpoint_name,
                endpoint_status,
            )
            return [], []

        try:
            containers = await asyncio.wait_for(
                client.list_containers_for_endpoint(endpoint_id, include_stopped=True),
                timeout=self.container_fetch_timeout,
            )
        except (asyncio.TimeoutError, PortainerAPIError) as exc:
            LOGGER.debug(
                "Failed to fetch containers for endpoint %s: %s",
                endpoint_name,
                exc,
            )
            return [], []

        security_issues: list[ContainerCapabilities] = []
        if self.include_security_scan:
            security_issues = await self.security_scanner.scan_endpoint_containers(
                client, endpoint_id, endpoint_name, containers
            )

        return containers, security_issues

    async def collect_container_logs(
        self,
        client: AsyncPortainerClient,
        endpoint_id: int,
        endpoint_name: str | None,
        container: dict,
        state_category: str,
        exit_code: int | None,
    ) -> ContainerLogs | None:
        """Fetch logs for a single problematic container."""
        container_id = container.get("Id") or container.get("id") or ""
        names = container.get("Names") or []
        if isinstance(names, list) and names:
            container_name = names[0].lstrip("/")
        else:
            container_name = container.get("Name") or container_id[:12]

        try:
            logs = await asyncio.wait_for(
                client.get_container_logs(
                    endpoint_id,
                    container_id,
                    tail=self.log_tail_lines,
                    timestamps=True,
                ),
                timeout=self.log_fetch_timeout,
            )
        except (asyncio.TimeoutError, PortainerAPIError) as exc:
            LOGGER.debug(
                "Failed to fetch logs for container %s on endpoint %s: %s",
                container_name,
                endpoint_name,
                exc,
            )
            return None

        if not logs or not logs.strip():
            return None

        log_lines = logs.count("\n") + 1
        truncated = log_lines >= self.log_tail_lines

        return ContainerLogs(
            endpoint_id=endpoint_id,
            endpoint_name=endpoint_name,
            container_id=container_id,
            container_name=container_name,
            state=state_category,
            exit_code=exit_code,
            logs=logs,
            log_lines=log_lines,
            truncated=truncated,
        )

    async def collect_endpoint_logs(
        self,
        client: AsyncPortainerClient,
        endpoint: dict,
        containers: list[dict],
    ) -> list[ContainerLogs]:
        """Collect logs from problematic containers on an endpoint."""
        if not self.include_log_analysis:
            return []

        endpoint_id = int(endpoint.get("Id") or endpoint.get("id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")

        # Find problematic containers (excluding infrastructure containers)
        problematic: list[tuple[dict, str, int | None]] = []
        for container in containers:
            # Get container name for exclusion check
            names = container.get("Names") or []
            if isinstance(names, list) and names:
                container_name = names[0].lstrip("/")
            else:
                container_name = container.get("Name") or ""

            # Skip excluded infrastructure containers
            if _is_excluded_container(container_name, self.excluded_containers):
                continue

            is_problem, state_category, exit_code = _is_problematic_container(container)
            if is_problem:
                problematic.append((container, state_category, exit_code))

        # Limit the number of containers we fetch logs for
        problematic = problematic[: self.max_containers_for_logs]

        if not problematic:
            return []

        LOGGER.debug(
            "Collecting logs for %d problematic containers on endpoint %s",
            len(problematic),
            endpoint_name,
        )

        # Fetch logs concurrently
        tasks = [
            self.collect_container_logs(
                client, endpoint_id, endpoint_name, container, state_cat, exit_code
            )
            for container, state_cat, exit_code in problematic
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        collected_logs: list[ContainerLogs] = []
        for result in results:
            if isinstance(result, ContainerLogs):
                collected_logs.append(result)
            elif isinstance(result, Exception):
                LOGGER.debug("Log collection task failed: %s", result)

        return collected_logs

    async def collect_image_status(
        self,
        client: AsyncPortainerClient,
        endpoints: list[dict],
        stacks_by_endpoint: dict[int, list[dict]],
    ) -> list[ImageStatus]:
        """Collect image update status for all stacks."""
        if not self.include_image_check:
            return []

        outdated_images: list[ImageStatus] = []
        seen_stacks: set[int] = set()

        for endpoint in endpoints:
            endpoint_id = int(endpoint.get("Id") or endpoint.get("id") or 0)
            endpoint_name = endpoint.get("Name") or endpoint.get("name")
            stacks = stacks_by_endpoint.get(endpoint_id, [])

            for stack in stacks:
                stack_id = stack.get("Id") or stack.get("id")
                if not stack_id or stack_id in seen_stacks:
                    continue
                seen_stacks.add(stack_id)

                stack_name = stack.get("Name") or stack.get("name")

                try:
                    image_status = await client.get_stack_image_status(stack_id)
                except PortainerAPIError as exc:
                    LOGGER.debug(
                        "Failed to get image status for stack %s: %s",
                        stack_name,
                        exc,
                    )
                    continue

                if isinstance(image_status, dict):
                    status_items = image_status.get("Status") or image_status.get("status") or []
                    if isinstance(status_items, list):
                        for item in status_items:
                            if not isinstance(item, dict):
                                continue
                            outdated = item.get("Outdated", False) or item.get("outdated", False)
                            if outdated:
                                outdated_images.append(
                                    ImageStatus(
                                        stack_id=stack_id,
                                        stack_name=stack_name,
                                        endpoint_id=endpoint_id,
                                        endpoint_name=endpoint_name,
                                        image_name=item.get("Image") or item.get("image") or "unknown",
                                        current_digest=item.get("CurrentDigest") or item.get("currentDigest"),
                                        latest_digest=item.get("LatestDigest") or item.get("latestDigest"),
                                        outdated=True,
                                    )
                                )
                elif isinstance(image_status, list):
                    for item in image_status:
                        if not isinstance(item, dict):
                            continue
                        outdated = item.get("Outdated", False) or item.get("outdated", False)
                        if outdated:
                            outdated_images.append(
                                ImageStatus(
                                    stack_id=stack_id,
                                    stack_name=stack_name,
                                    endpoint_id=endpoint_id,
                                    endpoint_name=endpoint_name,
                                    image_name=item.get("Image") or item.get("image") or "unknown",
                                    current_digest=item.get("CurrentDigest") or item.get("currentDigest"),
                                    latest_digest=item.get("LatestDigest") or item.get("latestDigest"),
                                    outdated=True,
                                )
                            )

        return outdated_images

    async def collect_snapshot(self) -> InfrastructureSnapshot:
        """Collect a complete infrastructure snapshot from all configured environments."""
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()

        snapshot = InfrastructureSnapshot(timestamp=datetime.now(timezone.utc))

        all_containers: list[dict] = []
        all_security_issues: list[ContainerCapabilities] = []
        all_outdated_images: list[ImageStatus] = []
        all_container_logs: list[ContainerLogs] = []
        all_endpoints: list[dict] = []

        for env in environments:
            client = create_portainer_client(env)
            try:
                async with client:
                    endpoints = await client.list_all_endpoints()
                    endpoints = endpoints[: self.max_endpoints_per_env]

                    df_endpoints = normalise_endpoint_metadata(endpoints)
                    online_count = len(df_endpoints[df_endpoints["endpoint_status"] == 1])
                    offline_count = len(df_endpoints[df_endpoints["endpoint_status"] != 1])

                    snapshot.endpoints_online += online_count
                    snapshot.endpoints_offline += offline_count

                    stacks_by_endpoint: dict[int, list[dict]] = {}
                    containers_by_endpoint: dict[int, list[dict]] = {}

                    tasks = []
                    for ep in endpoints:
                        tasks.append(self.collect_endpoint_data(client, ep))

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for ep, result in zip(endpoints, results):
                        ep_id = int(ep.get("Id") or ep.get("id") or 0)
                        if isinstance(result, Exception):
                            LOGGER.debug("Failed to collect endpoint data: %s", result)
                            containers_by_endpoint[ep_id] = []
                            continue

                        containers, security_issues = result
                        containers_by_endpoint[ep_id] = containers
                        all_containers.extend(containers)
                        all_security_issues.extend(security_issues)

                        try:
                            stacks = await client.list_stacks_for_endpoint(ep_id)
                            stacks_by_endpoint[ep_id] = stacks
                        except PortainerAPIError:
                            stacks_by_endpoint[ep_id] = []

                    if self.include_image_check:
                        outdated_images = await self.collect_image_status(
                            client, endpoints, stacks_by_endpoint
                        )
                        all_outdated_images.extend(outdated_images)

                    # Collect logs from problematic containers
                    if self.include_log_analysis:
                        log_tasks = []
                        for ep in endpoints:
                            ep_id = int(ep.get("Id") or ep.get("id") or 0)
                            containers = containers_by_endpoint.get(ep_id, [])
                            log_tasks.append(
                                self.collect_endpoint_logs(client, ep, containers)
                            )

                        log_results = await asyncio.gather(*log_tasks, return_exceptions=True)
                        for result in log_results:
                            if isinstance(result, list):
                                all_container_logs.extend(result)
                            elif isinstance(result, Exception):
                                LOGGER.debug("Log collection failed: %s", result)

                    df_containers = normalise_endpoint_containers(
                        endpoints, containers_by_endpoint
                    )

                    for ep in endpoints:
                        ep_id = int(ep.get("Id") or ep.get("id") or 0)
                        ep_name = ep.get("Name") or ep.get("name")
                        ep_data = {
                            "endpoint_id": ep_id,
                            "endpoint_name": ep_name,
                            "endpoint_status": ep.get("Status") or ep.get("status"),
                            "environment": env.name,
                        }
                        all_endpoints.append(ep_data)

                        # Add endpoint info to containers for remediation lookup
                        for c in containers_by_endpoint.get(ep_id, []):
                            c["_endpoint_id"] = ep_id
                            c["_endpoint_name"] = ep_name

            except PortainerAPIError as exc:
                LOGGER.error(
                    "Failed to collect data from environment %s: %s",
                    env.name,
                    exc,
                )
                continue

        running = sum(1 for c in all_containers if c.get("State") == "running")
        stopped = sum(1 for c in all_containers if c.get("State") != "running")

        unhealthy = 0
        for c in all_containers:
            status = c.get("Status") or ""
            if isinstance(status, str) and "unhealthy" in status.lower():
                unhealthy += 1

        snapshot.containers_running = running
        snapshot.containers_stopped = stopped
        snapshot.containers_unhealthy = unhealthy
        snapshot.security_issues = all_security_issues
        snapshot.outdated_images = all_outdated_images
        snapshot.container_logs = all_container_logs
        snapshot.endpoint_details = all_endpoints
        snapshot.container_details = [
            {
                "container_id": c.get("Id") or c.get("id"),
                "container_name": (
                    (c.get("Names") or ["unknown"])[0].lstrip("/")
                    if isinstance(c.get("Names"), list)
                    else c.get("Name") or "unknown"
                ),
                "image": c.get("Image"),
                "state": c.get("State"),
                "status": c.get("Status"),
                "endpoint_id": c.get("_endpoint_id"),
                "endpoint_name": c.get("_endpoint_name"),
            }
            for c in all_containers
        ]

        LOGGER.info(
            "Collected snapshot: %d endpoints (%d online), %d containers (%d running), "
            "%d security issues, %d outdated images, %d container logs",
            len(all_endpoints),
            snapshot.endpoints_online,
            len(all_containers),
            running,
            len(all_security_issues),
            len(all_outdated_images),
            len(all_container_logs),
        )

        return snapshot


def create_data_collector() -> DataCollector:
    """Create a data collector with settings from configuration."""
    settings = get_settings()
    scanner = create_security_scanner()
    excluded = frozenset(settings.monitoring.excluded_containers)
    return DataCollector(
        security_scanner=scanner,
        include_security_scan=settings.monitoring.include_security_scan,
        include_image_check=settings.monitoring.include_image_check,
        include_log_analysis=settings.monitoring.include_log_analysis,
        log_tail_lines=settings.monitoring.log_tail_lines,
        max_containers_for_logs=settings.monitoring.max_containers_for_logs,
        log_fetch_timeout=settings.monitoring.log_fetch_timeout,
        excluded_containers=excluded,
    )


__all__ = [
    "DataCollector",
    "create_data_collector",
]
