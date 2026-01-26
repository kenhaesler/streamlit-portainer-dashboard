"""Container security scanner for detecting elevated privileges."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.monitoring import ContainerCapabilities
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
)

LOGGER = logging.getLogger(__name__)

# Default elevated capabilities that pose security risks
DEFAULT_ELEVATED_CAPS = frozenset([
    "NET_ADMIN",
    "SYS_ADMIN",
    "SYS_PTRACE",
    "SYS_RAWIO",
    "SYS_MODULE",
    "DAC_OVERRIDE",
    "SETUID",
    "SETGID",
    "NET_RAW",
    "MKNOD",
    "AUDIT_WRITE",
    "CHOWN",
    "FOWNER",
    "FSETID",
    "KILL",
    "SYS_CHROOT",
    "SYS_BOOT",
    "SYS_TIME",
    "LINUX_IMMUTABLE",
])


def _is_excluded_container(container_name: str, excluded_patterns: frozenset[str]) -> bool:
    """Check if a container name matches any exclusion pattern.

    Uses case-insensitive substring matching to identify infrastructure
    containers that should be excluded from monitoring.
    """
    if not excluded_patterns:
        return False
    name_lower = container_name.lower()
    for pattern in excluded_patterns:
        if pattern.lower() in name_lower:
            return True
    return False


@dataclass
class SecurityScanner:
    """Scanner for container security configurations."""

    elevated_capabilities: frozenset[str] = field(
        default_factory=lambda: DEFAULT_ELEVATED_CAPS
    )
    excluded_containers: frozenset[str] = field(default_factory=frozenset)
    scan_timeout: float = 10.0

    async def scan_container(
        self,
        client: AsyncPortainerClient,
        endpoint_id: int,
        endpoint_name: str | None,
        container_id: str,
        container_name: str,
    ) -> ContainerCapabilities | None:
        """Scan a single container for security configuration.

        Returns ContainerCapabilities if container has elevated privileges,
        or None if container is running with default/restricted capabilities.
        """
        try:
            inspect_data = await asyncio.wait_for(
                client.inspect_container(endpoint_id, container_id),
                timeout=self.scan_timeout,
            )
        except asyncio.TimeoutError:
            LOGGER.debug(
                "Timeout inspecting container %s on endpoint %d",
                container_id[:12],
                endpoint_id,
            )
            return None
        except PortainerAPIError as exc:
            LOGGER.debug(
                "Failed to inspect container %s: %s",
                container_id[:12],
                exc,
            )
            return None

        host_config = inspect_data.get("HostConfig", {})
        if not isinstance(host_config, dict):
            return None

        cap_add = host_config.get("CapAdd") or []
        cap_drop = host_config.get("CapDrop") or []
        privileged = host_config.get("Privileged", False)
        security_opt = host_config.get("SecurityOpt") or []

        if not isinstance(cap_add, list):
            cap_add = []
        if not isinstance(cap_drop, list):
            cap_drop = []
        if not isinstance(security_opt, list):
            security_opt = []

        elevated_risks: list[str] = []

        if privileged:
            elevated_risks.append("Container running in privileged mode")

        for cap in cap_add:
            if cap in self.elevated_capabilities:
                elevated_risks.append(f"Elevated capability: {cap}")

        for opt in security_opt:
            if isinstance(opt, str):
                opt_lower = opt.lower()
                if "apparmor=unconfined" in opt_lower:
                    elevated_risks.append("AppArmor disabled (unconfined)")
                if "seccomp=unconfined" in opt_lower:
                    elevated_risks.append("Seccomp disabled (unconfined)")
                if "no-new-privileges=false" in opt_lower:
                    elevated_risks.append("No-new-privileges not enforced")

        if not elevated_risks:
            return None

        return ContainerCapabilities(
            endpoint_id=endpoint_id,
            endpoint_name=endpoint_name,
            container_id=container_id,
            container_name=container_name,
            cap_add=cap_add,
            cap_drop=cap_drop,
            privileged=privileged,
            security_opt=security_opt,
            elevated_risks=elevated_risks,
        )

    async def scan_endpoint_containers(
        self,
        client: AsyncPortainerClient,
        endpoint_id: int,
        endpoint_name: str | None,
        containers: list[dict],
    ) -> list[ContainerCapabilities]:
        """Scan all containers on an endpoint for security issues.

        Only returns containers with elevated privileges or security issues.
        """
        results: list[ContainerCapabilities] = []
        tasks = []

        for container in containers:
            container_id = (
                container.get("Id")
                or container.get("ID")
                or container.get("id")
            )
            if not container_id:
                continue

            names = container.get("Names") or []
            if isinstance(names, list) and names:
                container_name = str(names[0]).lstrip("/")
            else:
                container_name = container.get("Name") or container.get("name") or "unknown"

            state = container.get("State")
            if state != "running":
                continue

            # Skip excluded infrastructure containers
            if _is_excluded_container(container_name, self.excluded_containers):
                LOGGER.debug(
                    "Skipping excluded container %s from security scan",
                    container_name,
                )
                continue

            tasks.append(
                self.scan_container(
                    client,
                    endpoint_id,
                    endpoint_name,
                    container_id,
                    container_name,
                )
            )

        if tasks:
            scan_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in scan_results:
                if isinstance(result, ContainerCapabilities):
                    results.append(result)
                elif isinstance(result, Exception):
                    LOGGER.debug("Container scan failed: %s", result)

        return results


def create_security_scanner() -> SecurityScanner:
    """Create a security scanner with settings from configuration."""
    settings = get_settings()
    elevated_caps = frozenset(settings.monitoring.elevated_capabilities)
    excluded = frozenset(settings.monitoring.excluded_containers)
    return SecurityScanner(
        elevated_capabilities=elevated_caps,
        excluded_containers=excluded,
    )


__all__ = [
    "DEFAULT_ELEVATED_CAPS",
    "SecurityScanner",
    "_is_excluded_container",
    "create_security_scanner",
]
