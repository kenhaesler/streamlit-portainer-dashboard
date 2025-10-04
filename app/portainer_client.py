"""Utilities for interacting with the Portainer API."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)


class PortainerAPIError(RuntimeError):
    """Raised when a Portainer API request fails."""


@dataclass
class PortainerClient:
    """Lightweight Portainer API client."""

    base_url: str
    api_key: str
    timeout: tuple[float, float] = (5.0, 30.0)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.lower().endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        if not self.api_key:
            raise ValueError("Portainer API key is required")

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _request(self, path: str, *, params: Optional[Dict[str, object]] = None) -> object:
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(url, headers=self._headers, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - defensive
            raise PortainerAPIError(str(exc)) from exc
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise PortainerAPIError("Invalid JSON response from Portainer") from exc

    def list_edge_endpoints(self) -> List[Dict[str, object]]:
        data = self._request("/endpoints", params={"edge": "true"})
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


def normalise_endpoint_stacks(
    endpoints: Iterable[Dict[str, object]],
    stacks_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to stacks."""

    records: List[Dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(endpoint.get("Id") or endpoint.get("id", 0))
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        endpoint_status = endpoint.get("Status") or endpoint.get("status")
        stacks = stacks_by_endpoint.get(endpoint_id) or []
        if stacks:
            for stack in stacks:
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


def load_client_from_env() -> PortainerClient:
    """Create a :class:`PortainerClient` from environment variables."""

    api_url = os.getenv("PORTAINER_API_URL", "").strip()
    api_key = os.getenv("PORTAINER_API_KEY", "").strip()
    if not api_url:
        raise ValueError("PORTAINER_API_URL environment variable is required")
    if not api_key:
        raise ValueError("PORTAINER_API_KEY environment variable is required")
    return PortainerClient(base_url=api_url, api_key=api_key)
