"""Async Portainer API client using httpx."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from portainer_dashboard.config import PortainerEnvironmentSettings, get_settings

LOGGER = logging.getLogger(__name__)


class PortainerAPIError(RuntimeError):
    """Raised when a Portainer API request fails."""


def _coerce_int(value: object) -> int | None:
    """Return value as an integer when possible."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _first_present(mapping: dict[str, object], *keys: str) -> object:
    """Return the first value present for keys in mapping."""
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _stack_targets_endpoint(stack: dict[str, object], endpoint_id: int) -> bool:
    """Return True when a stack is assigned to the provided endpoint."""
    endpoint_keys = ("EndpointId", "EndpointID", "endpointId", "endpointID")
    for key in endpoint_keys:
        if key not in stack:
            continue
        coerced = _coerce_int(stack.get(key))
        if coerced is None:
            continue
        if coerced == endpoint_id:
            return True

    deployment_info = stack.get("DeploymentInfo") or stack.get("deploymentInfo")
    if isinstance(deployment_info, dict):
        str_endpoint_id = str(endpoint_id)
        if str_endpoint_id in {str(key) for key in deployment_info.keys()}:
            return True
        for info in deployment_info.values():
            if not isinstance(info, dict):
                continue
            for key in endpoint_keys:
                if key not in info:
                    continue
                coerced = _coerce_int(info.get(key))
                if coerced is None:
                    continue
                if coerced == endpoint_id:
                    return True

    return False


def _stack_has_endpoint_metadata(stack: dict[str, object]) -> bool:
    """Return True when the stack embeds any endpoint assignment metadata."""
    endpoint_keys = ("EndpointId", "EndpointID", "endpointId", "endpointID")
    for key in endpoint_keys:
        if key not in stack:
            continue
        coerced = _coerce_int(stack.get(key))
        if coerced is None:
            continue
        return True

    deployment_info = stack.get("DeploymentInfo") or stack.get("deploymentInfo")
    if isinstance(deployment_info, dict):
        if any(_coerce_int(key) is not None for key in deployment_info.keys()):
            return True
        for info in deployment_info.values():
            if not isinstance(info, dict):
                continue
            for key in endpoint_keys:
                if key not in info:
                    continue
                coerced = _coerce_int(info.get(key))
                if coerced is None:
                    continue
                return True

    return False


@dataclass
class AsyncPortainerClient:
    """Async Portainer API client using httpx."""

    base_url: str
    api_key: str
    timeout: float = 30.0
    verify_ssl: bool = True
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.lower().endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        if not self.api_key:
            raise ValueError("Portainer API key is required")

    async def __aenter__(self) -> "AsyncPortainerClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
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
    )


# Data normalizers (kept from original implementation)


def normalise_endpoint_metadata(
    endpoints: list[dict[str, object]]
) -> pd.DataFrame:
    """Return a dataframe with enriched endpoint metadata."""
    records: list[dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        endpoint_status = _first_present(endpoint, "Status", "status")
        agent = endpoint.get("Agent") or endpoint.get("agent") or {}
        if not isinstance(agent, dict):
            agent = {}
        agent_version = agent.get("Version") or agent.get("version")
        platform = agent.get("Platform") or agent.get("platform")
        os_name = agent.get("Os") or agent.get("OS") or agent.get("os")
        group_id = _coerce_int(
            _first_present(endpoint, "GroupId", "GroupID", "groupId")
        )
        tags = endpoint.get("Tags") or endpoint.get("tags")
        if isinstance(tags, list):
            tag_summary = ", ".join(str(tag) for tag in tags if tag is not None)
        else:
            tag_summary = str(tags) if tags not in (None, "") else None
        last_check_in = _first_present(
            endpoint,
            "LastCheckInDate",
            "EdgeCheckinInterval",
            "EdgeLastCheckInDate",
            "LastCheckIn",
        )
        last_check_iso: str | None = None
        if isinstance(last_check_in, (int, float)):
            try:
                last_check_iso = pd.to_datetime(
                    last_check_in, unit="s", utc=True
                ).isoformat()
            except (ValueError, OverflowError):
                last_check_iso = None
        elif isinstance(last_check_in, str) and last_check_in:
            try:
                last_check_iso = pd.to_datetime(last_check_in, utc=True).isoformat()
            except (ValueError, TypeError):
                last_check_iso = last_check_in
        url_value = endpoint.get("URL") or endpoint.get("Url") or endpoint.get("url")

        def _parse_hostname(value: object) -> str | None:
            if not isinstance(value, str):
                return None
            candidate = value.strip()
            if not candidate:
                return None
            parsed = urlparse(
                candidate if "://" in candidate else f"tcp://{candidate}"
            )
            hostname = parsed.hostname
            if hostname:
                return hostname
            if ":" in candidate and "//" not in candidate:
                return candidate.split(":", 1)[0]
            return candidate or None

        agent_hostname = _parse_hostname(url_value)
        if not agent_hostname:
            public_url = (
                endpoint.get("PublicURL")
                or endpoint.get("PublicUrl")
                or endpoint.get("publicURL")
                or endpoint.get("publicUrl")
                or endpoint.get("public_url")
            )
            agent_hostname = _parse_hostname(public_url)

        record = {
            "endpoint_id": endpoint_id,
            "endpoint_name": endpoint_name,
            "endpoint_status": endpoint_status,
            "agent_version": agent_version,
            "platform": platform,
            "operating_system": os_name,
            "group_id": group_id,
            "tags": tag_summary,
            "last_check_in": last_check_iso,
            "url": url_value,
            "agent_hostname": agent_hostname,
        }
        records.append(record)
    if not records:
        return pd.DataFrame(
            columns=[
                "endpoint_id",
                "endpoint_name",
                "endpoint_status",
                "agent_version",
                "platform",
                "operating_system",
                "group_id",
                "tags",
                "last_check_in",
                "url",
                "agent_hostname",
            ]
        )
    return pd.DataFrame.from_records(records)


def normalise_endpoint_stacks(
    endpoints: list[dict[str, object]],
    stacks_by_endpoint: dict[int, list[dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to stacks."""
    records: list[dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        endpoint_status = _first_present(endpoint, "Status", "status")
        raw_stacks = stacks_by_endpoint.get(endpoint_id, [])
        targeted_stacks = [
            stack
            for stack in raw_stacks
            if _stack_targets_endpoint(stack, endpoint_id)
        ]
        stacks = targeted_stacks
        if not stacks:
            stacks = [
                stack
                for stack in raw_stacks
                if not _stack_has_endpoint_metadata(stack)
            ]

        if stacks:
            for stack in stacks:
                records.append(
                    {
                        "endpoint_id": endpoint_id,
                        "endpoint_name": endpoint_name,
                        "endpoint_status": endpoint_status,
                        "stack_id": _first_present(stack, "Id", "id"),
                        "stack_name": stack.get("Name") or stack.get("name"),
                        "stack_status": _first_present(stack, "Status", "status"),
                        "stack_type": _first_present(stack, "Type", "type"),
                    }
                )
        else:
            records.append(
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "endpoint_status": endpoint_status,
                    "stack_id": None,
                    "stack_name": None,
                    "stack_status": None,
                    "stack_type": None,
                }
            )
    if not records:
        return pd.DataFrame(
            columns=[
                "endpoint_id",
                "endpoint_name",
                "endpoint_status",
                "stack_id",
                "stack_name",
                "stack_status",
                "stack_type",
            ]
        )
    return pd.DataFrame.from_records(records)


def normalise_endpoint_containers(
    endpoints: list[dict[str, object]],
    containers_by_endpoint: dict[int, list[dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to containers."""
    records: list[dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        containers = containers_by_endpoint.get(endpoint_id, [])
        for container in containers:
            names = container.get("Names") or []
            if isinstance(names, list) and names:
                container_name = str(names[0]).lstrip("/")
            else:
                container_name = container.get("Name") or container.get("name")
            image = container.get("Image") or container.get("ImageID")
            state = container.get("State")
            status = container.get("Status")
            restart_count = container.get("RestartCount")
            created_raw = container.get("Created")
            created_at: str | None = None
            if isinstance(created_raw, (int, float)):
                created_at = pd.to_datetime(
                    created_raw, unit="s", utc=True
                ).isoformat()
            elif isinstance(created_raw, str):
                try:
                    created_at_ts = pd.to_datetime(created_raw, utc=True)
                except (TypeError, ValueError):
                    created_at_ts = pd.NaT
                created_at = (
                    created_at_ts.isoformat()
                    if isinstance(created_at_ts, pd.Timestamp)
                    else created_raw
                )
            ports = container.get("Ports")
            port_summary = None
            if isinstance(ports, list) and ports:
                summaries = []
                for port in ports:
                    private_port = port.get("PrivatePort")
                    public_port = port.get("PublicPort")
                    type_ = port.get("Type")
                    if private_port is None:
                        continue
                    if public_port:
                        summaries.append(
                            f"{public_port}->{private_port}/{type_}"
                            if type_
                            else f"{public_port}->{private_port}"
                        )
                    else:
                        summaries.append(
                            f"{private_port}/{type_}" if type_ else str(private_port)
                        )
                if summaries:
                    port_summary = ", ".join(summaries)
            records.append(
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "container_id": container.get("Id")
                    or container.get("ID")
                    or container.get("id"),
                    "container_name": container_name,
                    "image": image,
                    "state": state,
                    "status": status,
                    "restart_count": restart_count,
                    "created_at": created_at,
                    "ports": port_summary,
                }
            )
    if not records:
        return pd.DataFrame(
            columns=[
                "endpoint_id",
                "endpoint_name",
                "container_id",
                "container_name",
                "image",
                "state",
                "status",
                "restart_count",
                "created_at",
                "ports",
            ]
        )
    return pd.DataFrame.from_records(records)


def normalise_endpoint_images(
    endpoints: list[dict[str, object]],
    images_by_endpoint: dict[int, list[dict[str, object]]],
) -> pd.DataFrame:
    """Return normalised image data for endpoints."""
    records: list[dict[str, object]] = []
    endpoint_lookup = {
        int(_first_present(endpoint, "Id", "id") or 0): endpoint
        for endpoint in endpoints
    }
    for endpoint_id, images in images_by_endpoint.items():
        endpoint = endpoint_lookup.get(endpoint_id, {})
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        for image in images:
            if not isinstance(image, dict):
                continue
            repo_tags = image.get("RepoTags")
            if isinstance(repo_tags, list) and repo_tags:
                reference = repo_tags[0]
            else:
                reference = image.get("RepoDigests")
                if isinstance(reference, list) and reference:
                    reference = reference[0]
            if isinstance(reference, list):
                reference = reference[0] if reference else None
            created_raw = image.get("Created")
            created_at = None
            if isinstance(created_raw, (int, float)):
                try:
                    created_at = pd.to_datetime(
                        created_raw, unit="s", utc=True
                    ).isoformat()
                except (OverflowError, ValueError):
                    created_at = None
            elif isinstance(created_raw, str) and created_raw:
                try:
                    created_at = pd.to_datetime(created_raw, utc=True).isoformat()
                except (ValueError, TypeError):
                    created_at = created_raw
            size = image.get("Size") or image.get("VirtualSize")
            records.append(
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "image_id": image.get("Id") or image.get("ID"),
                    "reference": reference,
                    "size": size,
                    "created_at": created_at,
                    "dangling": image.get("Dangling"),
                }
            )
    if not records:
        return pd.DataFrame(
            columns=[
                "endpoint_id",
                "endpoint_name",
                "image_id",
                "reference",
                "size",
                "created_at",
                "dangling",
            ]
        )
    return pd.DataFrame.from_records(records)


__all__ = [
    "AsyncPortainerClient",
    "PortainerAPIError",
    "create_portainer_client",
    "normalise_endpoint_containers",
    "normalise_endpoint_images",
    "normalise_endpoint_metadata",
    "normalise_endpoint_stacks",
]
