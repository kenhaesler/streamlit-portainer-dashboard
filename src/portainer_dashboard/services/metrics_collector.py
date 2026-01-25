"""Metrics collector for container CPU/memory metrics."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from portainer_dashboard.config import PortainerEnvironmentSettings, get_settings
from portainer_dashboard.models.metrics import ContainerMetric, MetricType
from portainer_dashboard.services.metrics_store import SQLiteMetricsStore, get_metrics_store
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    create_portainer_client,
)

LOGGER = logging.getLogger(__name__)


def _calculate_cpu_percent(stats: dict) -> float | None:
    """Calculate CPU usage percentage from Docker stats.

    Uses the formula from Docker CLI:
    cpu_percent = (cpu_delta / system_delta) * number_of_cpus * 100
    """
    try:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        cpu_usage = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        precpu_usage = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        cpu_delta = cpu_usage - precpu_usage

        system_usage = cpu_stats.get("system_cpu_usage", 0)
        presystem_usage = precpu_stats.get("system_cpu_usage", 0)
        system_delta = system_usage - presystem_usage

        if system_delta <= 0 or cpu_delta < 0:
            return None

        # Get number of CPUs
        online_cpus = cpu_stats.get("online_cpus")
        if online_cpus is None:
            percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
            online_cpus = len(percpu) if percpu else 1

        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
        return min(cpu_percent, 100.0 * online_cpus)  # Cap at max possible

    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _calculate_memory_stats(stats: dict) -> tuple[float | None, int | None]:
    """Calculate memory usage percentage and bytes from Docker stats.

    Returns:
        Tuple of (memory_percent, memory_usage_bytes)
    """
    try:
        memory_stats = stats.get("memory_stats", {})

        usage = memory_stats.get("usage", 0)
        limit = memory_stats.get("limit", 0)

        # Subtract cache if available (more accurate)
        cache = memory_stats.get("stats", {}).get("cache", 0)
        actual_usage = usage - cache

        if limit <= 0:
            return None, actual_usage if actual_usage > 0 else None

        memory_percent = (actual_usage / limit) * 100.0
        return memory_percent, actual_usage

    except (KeyError, TypeError, ZeroDivisionError):
        return None, None


def _calculate_network_stats(stats: dict) -> tuple[int | None, int | None]:
    """Calculate network I/O from Docker stats.

    Returns:
        Tuple of (rx_bytes, tx_bytes)
    """
    try:
        networks = stats.get("networks", {})
        if not networks:
            return None, None

        rx_total = 0
        tx_total = 0
        for net_stats in networks.values():
            rx_total += net_stats.get("rx_bytes", 0)
            tx_total += net_stats.get("tx_bytes", 0)

        return rx_total, tx_total

    except (KeyError, TypeError):
        return None, None


def _calculate_block_stats(stats: dict) -> tuple[int | None, int | None]:
    """Calculate block I/O from Docker stats.

    Returns:
        Tuple of (read_bytes, write_bytes)
    """
    try:
        blkio = stats.get("blkio_stats", {})
        io_service = blkio.get("io_service_bytes_recursive", [])

        if not io_service:
            return None, None

        read_bytes = 0
        write_bytes = 0
        for entry in io_service:
            op = entry.get("op", "").lower()
            value = entry.get("value", 0)
            if op == "read":
                read_bytes += value
            elif op == "write":
                write_bytes += value

        return read_bytes, write_bytes

    except (KeyError, TypeError):
        return None, None


class MetricsCollector:
    """Collects container metrics from Portainer endpoints."""

    def __init__(self, metrics_store: SQLiteMetricsStore) -> None:
        self._metrics_store = metrics_store
        self._settings = get_settings()

    async def collect_metrics_for_container(
        self,
        client: AsyncPortainerClient,
        endpoint_id: int,
        endpoint_name: str | None,
        container_id: str,
        container_name: str,
    ) -> list[ContainerMetric]:
        """Collect all metrics for a single container."""
        metrics: list[ContainerMetric] = []
        now = datetime.now(timezone.utc)

        try:
            stats = await client.get_container_stats(endpoint_id, container_id)
        except PortainerAPIError as exc:
            LOGGER.debug(
                "Failed to get stats for container %s: %s",
                container_name,
                exc,
            )
            return metrics

        # CPU
        cpu_percent = _calculate_cpu_percent(stats)
        if cpu_percent is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.CPU_PERCENT,
                    value=cpu_percent,
                )
            )

        # Memory
        mem_percent, mem_usage = _calculate_memory_stats(stats)
        if mem_percent is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.MEMORY_PERCENT,
                    value=mem_percent,
                )
            )
        if mem_usage is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.MEMORY_USAGE,
                    value=float(mem_usage),
                )
            )

        # Network
        rx_bytes, tx_bytes = _calculate_network_stats(stats)
        if rx_bytes is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.NETWORK_RX_BYTES,
                    value=float(rx_bytes),
                )
            )
        if tx_bytes is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.NETWORK_TX_BYTES,
                    value=float(tx_bytes),
                )
            )

        # Block I/O
        read_bytes, write_bytes = _calculate_block_stats(stats)
        if read_bytes is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.BLOCK_READ_BYTES,
                    value=float(read_bytes),
                )
            )
        if write_bytes is not None:
            metrics.append(
                ContainerMetric(
                    timestamp=now,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint_name,
                    container_id=container_id,
                    container_name=container_name,
                    metric_type=MetricType.BLOCK_WRITE_BYTES,
                    value=float(write_bytes),
                )
            )

        return metrics

    async def collect_metrics_for_endpoint(
        self,
        env: PortainerEnvironmentSettings,
    ) -> list[ContainerMetric]:
        """Collect metrics for all running containers on an endpoint."""
        all_metrics: list[ContainerMetric] = []

        client = create_portainer_client(env)

        try:
            async with client:
                # Get all endpoints
                endpoints = await client.list_all_endpoints()

                for endpoint in endpoints:
                    endpoint_id = endpoint.get("Id") or endpoint.get("id")
                    if endpoint_id is None:
                        continue
                    endpoint_id = int(endpoint_id)
                    endpoint_name = endpoint.get("Name") or endpoint.get("name") or env.name

                    # Only collect from online endpoints
                    status = endpoint.get("Status") or endpoint.get("status")
                    if status != 1:
                        continue

                    try:
                        containers = await client.list_containers_for_endpoint(
                            endpoint_id, include_stopped=False
                        )
                    except PortainerAPIError:
                        continue

                    for container in containers:
                        container_id = (
                            container.get("Id")
                            or container.get("ID")
                            or container.get("id")
                        )
                        if not container_id:
                            continue

                        names = container.get("Names", [])
                        if isinstance(names, list) and names:
                            container_name = str(names[0]).lstrip("/")
                        else:
                            container_name = container.get("Name") or container_id[:12]

                        # Only collect from running containers
                        state = container.get("State", "").lower()
                        if state != "running":
                            continue

                        metrics = await self.collect_metrics_for_container(
                            client,
                            endpoint_id,
                            endpoint_name,
                            container_id,
                            container_name,
                        )
                        all_metrics.extend(metrics)

        except PortainerAPIError as exc:
            LOGGER.warning("Failed to collect metrics from %s: %s", env.name, exc)

        return all_metrics

    async def collect_all_metrics(self) -> int:
        """Collect metrics from all configured Portainer environments."""
        settings = get_settings()

        if not settings.metrics.enabled:
            return 0

        environments = settings.portainer.get_configured_environments()
        if not environments:
            LOGGER.debug("No Portainer environments configured for metrics collection")
            return 0

        all_metrics: list[ContainerMetric] = []

        # Collect from all environments
        tasks = [
            self.collect_metrics_for_endpoint(env)
            for env in environments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_metrics.extend(result)
            elif isinstance(result, Exception):
                LOGGER.warning("Metrics collection error: %s", result)

        # Store all metrics
        if all_metrics:
            self._metrics_store.store_metrics_batch(all_metrics)
            LOGGER.info("Collected and stored %d metrics", len(all_metrics))

        return len(all_metrics)


async def create_metrics_collector() -> MetricsCollector:
    """Create a metrics collector with the configured store."""
    store = await get_metrics_store()
    return MetricsCollector(store)


__all__ = [
    "MetricsCollector",
    "create_metrics_collector",
]
