"""Utilities for interacting with the Portainer API."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning

LOGGER = logging.getLogger(__name__)


class PortainerAPIError(RuntimeError):
    """Raised when a Portainer API request fails."""


def _coerce_int(value: object) -> int | None:
    """Return ``value`` as an integer when possible."""

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


def _stack_targets_endpoint(stack: Dict[str, object], endpoint_id: int) -> bool:
    """Return ``True`` when a stack is assigned to the provided endpoint."""

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


@dataclass
class PortainerClient:
    """Lightweight Portainer API client."""

    base_url: str
    api_key: str
    timeout: tuple[float, float] = (5.0, 30.0)
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.lower().endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        if not self.api_key:
            raise ValueError("Portainer API key is required")
        if not self.verify_ssl:
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _request(self, path: str, *, params: Optional[Dict[str, object]] = None) -> object:
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers,
                params=params,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - defensive
            raise PortainerAPIError(str(exc)) from exc
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise PortainerAPIError("Invalid JSON response from Portainer") from exc

    def list_edge_endpoints(self) -> List[Dict[str, object]]:
        params = {"edge": "true", "status": "true"}
        data = self._request("/endpoints", params=params)
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected endpoints payload from Portainer")
        return data

    def list_stacks_for_endpoint(self, endpoint_id: int) -> List[Dict[str, object]]:
        """Fetch stacks for a given endpoint.

        Portainer's API supports both `/stacks` (with an `endpointId` query)
        and `/edge/stacks`. We try both to maintain compatibility across
        different Portainer versions.
        """

        paths = (
            ("/stacks", {"endpointId": endpoint_id}),
            ("/edge/stacks", {"endpointId": endpoint_id}),
        )
        for path, params in paths:
            try:
                data = self._request(path, params=params)
            except PortainerAPIError as exc:
                LOGGER.debug("Failed fetching %s for endpoint %s: %s", path, endpoint_id, exc)
                continue
            if isinstance(data, list):
                return data
        return []

    def list_containers_for_endpoint(
        self,
        endpoint_id: int,
        *,
        include_stopped: bool = False,
    ) -> List[Dict[str, object]]:
        """Return containers for an endpoint via the Docker API."""

        params = {"all": "1" if include_stopped else "0"}
        data = self._request(
            f"/endpoints/{endpoint_id}/docker/containers/json",
            params=params,
        )
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected containers payload from Portainer")
        return data


def _extract_endpoint_status(endpoint: Dict[str, object]) -> object:
    """Return the most useful status value for an endpoint."""

    status_keys = ("Status", "status", "EdgeAgentStatus", "EdgeAgentState")
    for key in status_keys:
        if key not in endpoint:
            continue
        value = endpoint.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None


def normalise_endpoint_stacks(
    endpoints: Iterable[Dict[str, object]],
    stacks_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to stacks."""

    records: List[Dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        endpoint_status = _extract_endpoint_status(endpoint)
        stacks = stacks_by_endpoint.get(endpoint_id) or []
        targeted_stacks = [
            stack
            for stack in stacks
            if _stack_targets_endpoint(stack, endpoint_id)
        ]
        if targeted_stacks:
            for stack in targeted_stacks:
                records.append(
                    {
                        "endpoint_id": endpoint_id,
                        "endpoint_name": endpoint_name,
                        "endpoint_status": endpoint_status,
                        "stack_id": stack.get("Id") or stack.get("id"),
                        "stack_name": stack.get("Name") or stack.get("name"),
                        "stack_status": stack.get("Status") or stack.get("status"),
                        "stack_type": stack.get("Type") or stack.get("type"),
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
    endpoints: Iterable[Dict[str, object]],
    containers_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to containers."""

    records: List[Dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        containers = containers_by_endpoint.get(endpoint_id) or []
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
            created_at: Optional[str]
            created_at = None
            if isinstance(created_raw, (int, float)):
                created_at = pd.to_datetime(created_raw, unit="s", utc=True).isoformat()
            elif isinstance(created_raw, str):
                try:
                    created_at_ts = pd.to_datetime(created_raw, utc=True)
                except (TypeError, ValueError):
                    created_at_ts = pd.NaT
                created_at = (
                    created_at_ts.isoformat() if isinstance(created_at_ts, pd.Timestamp) else created_raw
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
                        summaries.append(f"{public_port}->{private_port}/{type_}" if type_ else f"{public_port}->{private_port}")
                    else:
                        summaries.append(f"{private_port}/{type_}" if type_ else str(private_port))
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


def _parse_bool_env(value: str, *, default: bool = True) -> bool:
    """Return a boolean from an environment variable string."""

    if value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def load_client_from_env() -> PortainerClient:
    """Create a :class:`PortainerClient` from environment variables."""

    api_url = os.getenv("PORTAINER_API_URL", "").strip()
    api_key = os.getenv("PORTAINER_API_KEY", "").strip()
    verify_ssl = _parse_bool_env(os.getenv("PORTAINER_VERIFY_SSL", ""), default=True)
    if not api_url:
        raise ValueError("PORTAINER_API_URL environment variable is required")
    if not api_key:
        raise ValueError("PORTAINER_API_KEY environment variable is required")
    return PortainerClient(base_url=api_url, api_key=api_key, verify_ssl=verify_ssl)
