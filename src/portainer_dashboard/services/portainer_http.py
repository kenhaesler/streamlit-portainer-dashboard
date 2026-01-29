"""Async Portainer API client using httpx with connection pooling."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from portainer_dashboard.config import PortainerEnvironmentSettings, get_settings
from portainer_dashboard.services.portainer_utils import _coerce_int

LOGGER = logging.getLogger(__name__)


def _get_pool_settings() -> tuple[int, int, float]:
    """Return (max_connections, max_keepalive_connections, keepalive_expiry) from config."""
    try:
        settings = get_settings()
        return (
            settings.portainer.max_connections,
            settings.portainer.max_keepalive_connections,
            settings.portainer.keepalive_expiry,
        )
    except Exception:
        return 20, 10, 30.0


class PortainerClientPool:
    """Connection pool manager for Portainer API clients.

    Maintains a pool of httpx.AsyncClient instances for connection reuse,
    significantly reducing TCP/TLS handshake overhead for repeated requests.
    """

    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        verify_ssl: bool = True,
    ) -> httpx.AsyncClient:
        """Get or create a pooled client for the given base URL."""
        # Use base_url as key (API key might change, but URL identifies the server)
        key = base_url

        async with self._lock:
            if key not in self._clients:
                max_conn, max_keep, keep_exp = _get_pool_settings()
                limits = httpx.Limits(
                    max_connections=max_conn,
                    max_keepalive_connections=max_keep,
                    keepalive_expiry=keep_exp,
                )
                self._clients[key] = httpx.AsyncClient(
                    base_url=base_url,
                    headers={"X-API-Key": api_key},
                    timeout=timeout,
                    verify=verify_ssl,
                    limits=limits,
                )
                LOGGER.debug("Created pooled client for %s", base_url)

            return self._clients[key]

    async def close_all(self) -> None:
        """Close all pooled clients."""
        async with self._lock:
            for url, client in self._clients.items():
                try:
                    await client.aclose()
                    LOGGER.debug("Closed pooled client for %s", url)
                except Exception as exc:
                    LOGGER.warning("Error closing client for %s: %s", url, exc)
            self._clients.clear()

    async def close_client(self, base_url: str) -> None:
        """Close a specific client."""
        async with self._lock:
            if base_url in self._clients:
                try:
                    await self._clients[base_url].aclose()
                except Exception as exc:
                    LOGGER.warning("Error closing client for %s: %s", base_url, exc)
                del self._clients[base_url]


# Global client pool singleton
_client_pool: PortainerClientPool | None = None


def get_client_pool() -> PortainerClientPool:
    """Get or create the global client pool."""
    global _client_pool
    if _client_pool is None:
        _client_pool = PortainerClientPool()
    return _client_pool


async def shutdown_client_pool() -> None:
    """Shutdown the global client pool. Call during application shutdown."""
    global _client_pool
    if _client_pool is not None:
        await _client_pool.close_all()
        _client_pool = None


class PortainerAPIError(RuntimeError):
    """Raised when a Portainer API request fails."""


@dataclass
class AsyncPortainerClient:
    """Async Portainer API client using httpx with connection pooling.

    When use_pool=True (default), uses shared connection pool for better performance.
    When use_pool=False, creates a new client per context (legacy behavior).
    """

    base_url: str
    api_key: str
    timeout: float = 60.0  # Increased from 30s to handle slow API responses
    verify_ssl: bool = True
    use_pool: bool = True  # Use connection pooling by default
    _client: httpx.AsyncClient = field(init=False, repr=False)
    _owns_client: bool = field(init=False, repr=False, default=True)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.lower().endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        if not self.api_key:
            raise ValueError("Portainer API key is required")

    async def __aenter__(self) -> "AsyncPortainerClient":
        if self.use_pool:
            # Use pooled client - don't close on exit
            pool = get_client_pool()
            self._client = await pool.get_client(
                self.base_url,
                self.api_key,
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )
            self._owns_client = False
        else:
            # Create a new client (legacy behavior)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            self._owns_client = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # Only close if we own the client (not pooled)
        if self._owns_client:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        reraise=True,
    )
    async def _request(
        self, path: str, *, params: dict[str, object] | None = None
    ) -> object:
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(str(exc)) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise PortainerAPIError("Invalid JSON response from Portainer") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        reraise=True,
    )
    async def _post(
        self,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.post(path, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(str(exc)) from exc
        return response

    @staticmethod
    def _extract_filename(header_value: str | None) -> str | None:
        if not header_value:
            return None
        parts = [part.strip() for part in header_value.split(";")]
        filename: str | None = None
        for part in parts:
            if not part:
                continue
            key, _, value = part.partition("=")
            if not value:
                continue
            lowered_key = key.strip().lower()
            cleaned_value = value.strip().strip('"')
            if lowered_key == "filename*":
                if cleaned_value.lower().startswith("utf-8''"):
                    cleaned_value = cleaned_value[7:]
                import urllib.parse
                filename = urllib.parse.unquote(cleaned_value)
                break
            if lowered_key == "filename":
                filename = cleaned_value
        if filename:
            filename = re.sub(r"[\\/]+", "-", filename).strip()
        return filename or None

    async def create_backup(
        self, *, password: str | None = None
    ) -> tuple[bytes, str | None]:
        payload: dict[str, object] = {}
        if password:
            payload["password"] = password
        response = await self._post("/backup", json=payload or {})
        filename = self._extract_filename(response.headers.get("Content-Disposition"))
        return response.content, filename

    async def list_edge_endpoints(self) -> list[dict[str, object]]:
        """List only edge endpoints."""
        params = {"edge": "true", "status": "true"}
        data = await self._request("/endpoints", params=params)
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected endpoints payload from Portainer")
        return data

    async def list_all_endpoints(self) -> list[dict[str, object]]:
        """List all endpoints (including local Docker environments)."""
        data = await self._request("/endpoints")
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected endpoints payload from Portainer")
        return data

    async def list_stacks_for_endpoint(
        self, endpoint_id: int
    ) -> list[dict[str, object]]:
        """Fetch stacks for a given endpoint."""
        paths = (
            ("/stacks", {"endpointId": endpoint_id}),
            ("/edge/stacks", {"endpointId": endpoint_id}),
        )
        results: list[dict[str, object]] = []
        seen_stack_ids: set[int] = set()

        for path, params in paths:
            try:
                data = await self._request(path, params=params)
            except PortainerAPIError as exc:
                LOGGER.debug(
                    "Failed fetching %s for endpoint %s: %s", path, endpoint_id, exc
                )
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("Id") or item.get("ID") or item.get("id")
                stack_id = _coerce_int(raw_id)
                if stack_id is not None and stack_id in seen_stack_ids:
                    continue
                if stack_id is not None:
                    seen_stack_ids.add(stack_id)
                results.append(item)
        return results

    async def list_containers_for_endpoint(
        self,
        endpoint_id: int,
        *,
        include_stopped: bool = False,
    ) -> list[dict[str, object]]:
        """Return containers for an endpoint via the Docker API."""
        params = {"all": "1" if include_stopped else "0"}
        data = await self._request(
            f"/endpoints/{endpoint_id}/docker/containers/json",
            params=params,
        )
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected containers payload from Portainer")
        return data

    async def inspect_container(
        self, endpoint_id: int, container_id: str
    ) -> dict[str, object]:
        """Return the detailed inspect payload for a container."""
        data = await self._request(
            f"/endpoints/{endpoint_id}/docker/containers/{container_id}/json"
        )
        if not isinstance(data, dict):
            raise PortainerAPIError(
                "Unexpected container inspect payload from Portainer"
            )
        return data

    async def get_container_logs(
        self,
        endpoint_id: int,
        container_id: str,
        *,
        tail: int = 500,
        timestamps: bool = True,
        since: int | None = None,
    ) -> str:
        """Fetch container logs from Docker API via Portainer.

        Args:
            endpoint_id: The Portainer endpoint ID.
            container_id: The container ID or name.
            tail: Number of lines to return from the end of the logs.
            timestamps: Whether to include timestamps in each log line.
            since: Only return logs since this Unix timestamp.

        Returns:
            The container log output as a string.
        """
        params = {
            "stdout": "true",
            "stderr": "true",
            "tail": str(tail),
            "timestamps": "true" if timestamps else "false",
        }
        if since is not None:
            params["since"] = str(since)

        try:
            response = await self._client.get(
                f"/endpoints/{endpoint_id}/docker/containers/{container_id}/logs",
                params=params,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(str(exc)) from exc

        # Docker logs API returns raw text, may include special characters
        # Strip any Docker stream headers (first 8 bytes per frame)
        text = response.text
        # Clean up the output by removing Docker stream header bytes
        lines = []
        for line in text.split("\n"):
            # Docker multiplexed streams have 8-byte headers
            # Check if line starts with binary header and clean it
            if len(line) > 8 and line[0] in "\x00\x01\x02":
                lines.append(line[8:])
            else:
                lines.append(line)
        return "\n".join(lines)

    async def get_container_stats(
        self, endpoint_id: int, container_id: str
    ) -> dict[str, object]:
        """Return a non-streaming stats snapshot for a container."""
        data = await self._request(
            f"/endpoints/{endpoint_id}/docker/containers/{container_id}/stats",
            params={"stream": "false"},
        )
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected container stats payload from Portainer")
        return data

    async def get_endpoint_host_info(self, endpoint_id: int) -> dict[str, object]:
        """Return Docker host metadata for an endpoint."""
        data = await self._request(f"/endpoints/{endpoint_id}/docker/info")
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected host info payload from Portainer")
        return data

    async def get_endpoint_system_df(self, endpoint_id: int) -> dict[str, object]:
        """Return Docker disk usage statistics for an endpoint."""
        data = await self._request(f"/endpoints/{endpoint_id}/docker/system/df")
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected system df payload from Portainer")
        return data

    async def list_volumes_for_endpoint(
        self, endpoint_id: int
    ) -> list[dict[str, object]]:
        """Return all Docker volumes defined on an endpoint."""
        data = await self._request(f"/endpoints/{endpoint_id}/docker/volumes")
        if isinstance(data, dict):
            volumes = data.get("Volumes")
        else:
            volumes = None
        if volumes is None:
            return []
        if not isinstance(volumes, list):
            raise PortainerAPIError("Unexpected volumes payload from Portainer")
        return [item for item in volumes if isinstance(item, dict)]

    async def list_images_for_endpoint(
        self, endpoint_id: int
    ) -> list[dict[str, object]]:
        """Return image metadata for an endpoint."""
        data = await self._request(f"/endpoints/{endpoint_id}/docker/images/json")
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected images payload from Portainer")
        return [item for item in data if isinstance(item, dict)]

    async def get_stack_image_status(self, stack_id: int) -> object:
        """Return the image status payload for the specified stack."""
        data = await self._request(f"/stacks/{stack_id}/images_status")
        if not isinstance(data, (dict, list)):
            raise PortainerAPIError(
                "Unexpected stack image status payload from Portainer"
            )
        return data

    async def restart_container(
        self, endpoint_id: int, container_id: str, *, timeout: int = 10
    ) -> dict[str, object]:
        """Restart a container.

        Args:
            endpoint_id: The Portainer endpoint ID.
            container_id: The container ID or name.
            timeout: Seconds to wait before killing the container.

        Returns:
            A dict with success status.
        """
        try:
            response = await self._client.post(
                f"/endpoints/{endpoint_id}/docker/containers/{container_id}/restart",
                params={"t": str(timeout)},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(f"Failed to restart container: {exc}") from exc
        return {"success": True, "action": "restart", "container_id": container_id}

    async def start_container(
        self, endpoint_id: int, container_id: str
    ) -> dict[str, object]:
        """Start a stopped container.

        Args:
            endpoint_id: The Portainer endpoint ID.
            container_id: The container ID or name.

        Returns:
            A dict with success status.
        """
        try:
            response = await self._client.post(
                f"/endpoints/{endpoint_id}/docker/containers/{container_id}/start",
            )
            # 304 means container is already started
            if response.status_code == 304:
                return {"success": True, "action": "start", "container_id": container_id, "note": "already running"}
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(f"Failed to start container: {exc}") from exc
        return {"success": True, "action": "start", "container_id": container_id}

    async def stop_container(
        self, endpoint_id: int, container_id: str, *, timeout: int = 10
    ) -> dict[str, object]:
        """Stop a running container.

        Args:
            endpoint_id: The Portainer endpoint ID.
            container_id: The container ID or name.
            timeout: Seconds to wait before killing the container.

        Returns:
            A dict with success status.
        """
        try:
            response = await self._client.post(
                f"/endpoints/{endpoint_id}/docker/containers/{container_id}/stop",
                params={"t": str(timeout)},
            )
            # 304 means container is already stopped
            if response.status_code == 304:
                return {"success": True, "action": "stop", "container_id": container_id, "note": "already stopped"}
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerAPIError(f"Failed to stop container: {exc}") from exc
        return {"success": True, "action": "stop", "container_id": container_id}


def create_portainer_client(
    env: PortainerEnvironmentSettings,
) -> AsyncPortainerClient:
    """Create an async Portainer client for the given environment."""
    return AsyncPortainerClient(
        base_url=env.api_url,
        api_key=env.api_key,
        verify_ssl=env.verify_ssl,
        timeout=env.timeout,
    )


__all__ = [
    "AsyncPortainerClient",
    "PortainerAPIError",
    "PortainerClientPool",
    "create_portainer_client",
    "get_client_pool",
    "shutdown_client_pool",
]
