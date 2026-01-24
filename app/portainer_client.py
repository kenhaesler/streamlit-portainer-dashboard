"""Utilities for interacting with the Portainer API."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

from app.tls import get_ca_bundle_path
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


def _first_present(mapping: Dict[str, object], *keys: str) -> object:
    """Return the first value present for ``keys`` in ``mapping``.

    Unlike using ``or`` to coalesce values, this helper treats ``0`` and
    ``False`` as valid values. Only ``None`` is considered missing which keeps
    numeric status codes intact.
    """

    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if value is not None:
            return value
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


def _stack_has_endpoint_metadata(stack: Dict[str, object]) -> bool:
    """Return ``True`` when the stack embeds any endpoint assignment metadata."""

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
class PortainerClient:
    """Lightweight Portainer API client."""

    base_url: str
    api_key: str
    timeout: tuple[float, float] = (5.0, 30.0)
    verify_ssl: bool | str = True
    session_factory: Callable[[], requests.Session] = field(
        default=requests.Session,
        repr=False,
    )
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url.lower().endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        if not self.api_key:
            raise ValueError("Portainer API key is required")
        if self.verify_ssl is True:
            ca_bundle_path = get_ca_bundle_path()
            if ca_bundle_path:
                self.verify_ssl = ca_bundle_path
        if self.verify_ssl is False:
            LOGGER.warning(
                "SSL verification disabled for Portainer client targeting %s",
                self.base_url,
            )
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        self._session = self.session_factory()
        self._configure_session()

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _configure_session(self) -> None:
        self._session.headers.update(self._headers)
        self._session.verify = self.verify_ssl
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
            )
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def close(self) -> None:
        """Release the underlying HTTP session resources."""

        try:
            self._session.close()
        except Exception:  # pragma: no cover - defensive cleanup
            LOGGER.debug("Failed to close Portainer session", exc_info=True)

    def __enter__(self) -> "PortainerClient":  # pragma: no cover - convenience
        return self

    def __exit__(
        self,
        exc_type,  # type: ignore[override]
        exc: BaseException | None,
        traceback,
    ) -> None:
        self.close()

    def _request(self, path: str, *, params: Optional[Dict[str, object]] = None) -> object:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - defensive
            raise PortainerAPIError(str(exc)) from exc
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise PortainerAPIError("Invalid JSON response from Portainer") from exc

    def _post(
        self,
        path: str,
        *,
        json: Optional[Dict[str, object]] = None,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.post(
                url,
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - defensive
            raise PortainerAPIError(str(exc)) from exc
        return response

    @staticmethod
    def _extract_filename(header_value: Optional[str]) -> Optional[str]:
        if not header_value:
            return None
        parts = [part.strip() for part in header_value.split(";")]
        filename: Optional[str] = None
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
                filename = requests.utils.unquote(cleaned_value)
                break
            if lowered_key == "filename":
                filename = cleaned_value
        if filename:
            filename = re.sub(r"[\\/]+", "-", filename).strip()
        return filename or None

    def create_backup(self, *, password: Optional[str] = None) -> Tuple[bytes, Optional[str]]:
        payload: Dict[str, object] = {}
        if password:
            payload["password"] = password
        response = self._post("/backup", json=payload or {})
        filename = self._extract_filename(response.headers.get("Content-Disposition"))
        return response.content, filename

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
        results: list[dict[str, object]] = []
        seen_stack_ids: set[int] = set()

        for path, params in paths:
            try:
                data = self._request(path, params=params)
            except PortainerAPIError as exc:
                LOGGER.debug("Failed fetching %s for endpoint %s: %s", path, endpoint_id, exc)
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

    def inspect_container(
        self, endpoint_id: int, container_id: str
    ) -> Dict[str, object]:
        """Return the detailed inspect payload for a container."""

        data = self._request(
            f"/endpoints/{endpoint_id}/docker/containers/{container_id}/json"
        )
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected container inspect payload from Portainer")
        return data

    def get_container_stats(
        self, endpoint_id: int, container_id: str
    ) -> Dict[str, object]:
        """Return a non-streaming stats snapshot for a container."""

        data = self._request(
            f"/endpoints/{endpoint_id}/docker/containers/{container_id}/stats",
            params={"stream": "false"},
        )
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected container stats payload from Portainer")
        return data

    def get_endpoint_host_info(self, endpoint_id: int) -> Dict[str, object]:
        """Return Docker host metadata for an endpoint."""

        data = self._request(f"/endpoints/{endpoint_id}/docker/info")
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected host info payload from Portainer")
        return data

    def get_endpoint_system_df(self, endpoint_id: int) -> Dict[str, object]:
        """Return Docker disk usage statistics for an endpoint."""

        data = self._request(f"/endpoints/{endpoint_id}/docker/system/df")
        if not isinstance(data, dict):
            raise PortainerAPIError("Unexpected system df payload from Portainer")
        return data

    def list_volumes_for_endpoint(self, endpoint_id: int) -> List[Dict[str, object]]:
        """Return all Docker volumes defined on an endpoint."""

        data = self._request(f"/endpoints/{endpoint_id}/docker/volumes")
        if isinstance(data, dict):
            volumes = data.get("Volumes")
        else:
            volumes = None
        if volumes is None:
            return []
        if not isinstance(volumes, list):
            raise PortainerAPIError("Unexpected volumes payload from Portainer")
        return [item for item in volumes if isinstance(item, dict)]

    def list_images_for_endpoint(self, endpoint_id: int) -> List[Dict[str, object]]:
        """Return image metadata for an endpoint."""

        data = self._request(f"/endpoints/{endpoint_id}/docker/images/json")
        if not isinstance(data, list):
            raise PortainerAPIError("Unexpected images payload from Portainer")
        return [item for item in data if isinstance(item, dict)]

    def get_stack_image_status(self, stack_id: int) -> object:
        """Return the image status payload for the specified stack."""

        data = self._request(f"/stacks/{stack_id}/images_status")
        if not isinstance(data, (dict, list)):
            raise PortainerAPIError("Unexpected stack image status payload from Portainer")
        return data


def normalise_endpoint_stacks(
    endpoints: Iterable[Dict[str, object]],
    stacks_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to stacks."""

    def _normalise_stack_list(value: Iterable[Dict[str, object]] | object) -> List[Dict[str, object]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        return []

    records: List[Dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(
            _first_present(endpoint, "Id", "id") or 0
        )
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        endpoint_status = _first_present(endpoint, "Status", "status")
        raw_stacks = _normalise_stack_list(stacks_by_endpoint.get(endpoint_id))
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


def normalise_endpoint_metadata(
    endpoints: Iterable[Dict[str, object]]
) -> pd.DataFrame:
    """Return a dataframe with enriched endpoint metadata."""

    records: List[Dict[str, object]] = []
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
        group_id = _coerce_int(_first_present(endpoint, "GroupId", "GroupID", "groupId"))
        tags = endpoint.get("Tags") or endpoint.get("tags")
        if isinstance(tags, list):
            tag_summary = ", ".join(str(tag) for tag in tags if tag is not None)
        else:
            tag_summary = str(tags) if tags not in (None, "") else None
        last_check_in = (
            _first_present(
                endpoint,
                "LastCheckInDate",
                "EdgeCheckinInterval",
                "EdgeLastCheckInDate",
                "LastCheckIn",
            )
        )
        last_check_iso: Optional[str]
        last_check_iso = None
        if isinstance(last_check_in, (int, float)):
            try:
                last_check_iso = pd.to_datetime(last_check_in, unit="s", utc=True).isoformat()
            except (ValueError, OverflowError):
                last_check_iso = None
        elif isinstance(last_check_in, str) and last_check_in:
            try:
                last_check_iso = pd.to_datetime(last_check_in, utc=True).isoformat()
            except (ValueError, TypeError):
                last_check_iso = last_check_in
        url_value = endpoint.get("URL") or endpoint.get("Url") or endpoint.get("url")

        def _parse_hostname(value: object) -> Optional[str]:
            if not isinstance(value, str):
                return None
            candidate = value.strip()
            if not candidate:
                return None
            parsed = urlparse(candidate if "://" in candidate else f"tcp://{candidate}")
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
            columns=
            [
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


def normalise_endpoint_containers(
    endpoints: Iterable[Dict[str, object]],
    containers_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    """Return a normalised dataframe mapping endpoints to containers."""

    records: List[Dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
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


def normalise_container_details(
    endpoints: Iterable[Dict[str, object]],
    containers_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
    inspect_payloads: Dict[int, Dict[str, Dict[str, object]]],
    stats_payloads: Dict[int, Dict[str, Dict[str, object]]],
) -> pd.DataFrame:
    """Return enriched container records including inspect/stats data."""

    endpoint_lookup = {
        int(_first_present(endpoint, "Id", "id") or 0): endpoint
        for endpoint in endpoints
    }
    records: List[Dict[str, object]] = []
    for endpoint_id, containers in containers_by_endpoint.items():
        endpoint = endpoint_lookup.get(endpoint_id, {})
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        for container in containers:
            container_id = (
                container.get("Id")
                or container.get("ID")
                or container.get("id")
            )
            if not isinstance(container_id, str) or not container_id:
                continue
            names = container.get("Names") or []
            if isinstance(names, list) and names:
                container_name = str(names[0]).lstrip("/")
            else:
                container_name = container.get("Name") or container.get("name")
            inspect_data = inspect_payloads.get(endpoint_id, {}).get(container_id, {})
            stats_data = stats_payloads.get(endpoint_id, {}).get(container_id, {})
            if not isinstance(inspect_data, dict):
                inspect_data = {}
            if not isinstance(stats_data, dict):
                stats_data = {}
            state = inspect_data.get("State") or {}
            if not isinstance(state, dict):
                state = {}
            health = state.get("Health") or {}
            if not isinstance(health, dict):
                health = {}
            health_status = health.get("Status")
            last_exit_code = state.get("ExitCode")
            finished_at = state.get("FinishedAt")
            if isinstance(finished_at, str) and finished_at:
                try:
                    finished_at_iso = pd.to_datetime(finished_at, utc=True).isoformat()
                except (ValueError, TypeError):
                    finished_at_iso = finished_at
            else:
                finished_at_iso = None
            mounts_raw = inspect_data.get("Mounts")
            mounts_summary = None
            if isinstance(mounts_raw, list):
                mount_entries = []
                for mount in mounts_raw:
                    if not isinstance(mount, dict):
                        continue
                    destination = mount.get("Destination") or mount.get("Target")
                    source = mount.get("Source")
                    if destination and source:
                        mount_entries.append(f"{destination} ← {source}")
                    elif destination:
                        mount_entries.append(str(destination))
                    elif source:
                        mount_entries.append(str(source))
                if mount_entries:
                    mounts_summary = ", ".join(mount_entries)
            networks = inspect_data.get("NetworkSettings")
            network_summary = None
            if isinstance(networks, dict):
                network_settings = networks.get("Networks")
                if isinstance(network_settings, dict):
                    network_summary = ", ".join(sorted(network_settings.keys())) or None
            labels_raw = inspect_data.get("Config")
            labels_summary = None
            if isinstance(labels_raw, dict):
                labels = labels_raw.get("Labels")
                if isinstance(labels, dict):
                    label_entries = [
                        f"{key}={value}"
                        for key, value in sorted(labels.items())
                        if value is not None
                    ]
                    if label_entries:
                        labels_summary = ", ".join(label_entries)
            cpu_stats = stats_data.get("cpu_stats")
            if not isinstance(cpu_stats, dict):
                cpu_stats = {}
            precpu_stats = stats_data.get("precpu_stats")
            if not isinstance(precpu_stats, dict):
                precpu_stats = {}
            cpu_delta: Optional[float] = None
            system_delta: Optional[float] = None
            if cpu_stats and precpu_stats:
                total_usage = cpu_stats.get("cpu_usage", {}).get("total_usage")
                pre_total = precpu_stats.get("cpu_usage", {}).get("total_usage")
                system_usage = cpu_stats.get("system_cpu_usage")
                pre_system = precpu_stats.get("system_cpu_usage")
                try:
                    if total_usage is not None and pre_total is not None:
                        cpu_delta = float(total_usage) - float(pre_total)
                    if system_usage is not None and pre_system is not None:
                        system_delta = float(system_usage) - float(pre_system)
                except (TypeError, ValueError):
                    cpu_delta = None
                    system_delta = None
            cpu_percentage: Optional[float] = None
            if cpu_delta and system_delta and system_delta > 0:
                percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage")
                cpu_count = len(percpu) if isinstance(percpu, list) and percpu else 1
                cpu_percentage = (cpu_delta / system_delta) * cpu_count * 100.0
            memory_stats = stats_data.get("memory_stats")
            if not isinstance(memory_stats, dict):
                memory_stats = {}
            memory_usage = memory_stats.get("usage")
            memory_limit = memory_stats.get("limit")
            memory_percent: Optional[float] = None
            try:
                if memory_usage is not None and memory_limit:
                    memory_percent = (float(memory_usage) / float(memory_limit)) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                memory_percent = None
            records.append(
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "container_id": container_id,
                    "container_name": container_name,
                    "health_status": health_status,
                    "last_exit_code": last_exit_code,
                    "last_finished_at": finished_at_iso,
                    "cpu_percent": cpu_percentage,
                    "memory_usage": memory_usage,
                    "memory_limit": memory_limit,
                    "memory_percent": memory_percent,
                    "mounts": mounts_summary,
                    "networks": network_summary,
                    "labels": labels_summary,
                }
            )
    if not records:
        return pd.DataFrame(
            columns=
            [
                "endpoint_id",
                "endpoint_name",
                "container_id",
                "container_name",
                "health_status",
                "last_exit_code",
                "last_finished_at",
                "cpu_percent",
                "memory_usage",
                "memory_limit",
                "memory_percent",
                "mounts",
                "networks",
                "labels",
            ]
        )

    df = pd.DataFrame.from_records(records)

    for column in ("cpu_percent", "memory_usage", "memory_limit", "memory_percent"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def normalise_endpoint_host_metrics(
    endpoints: Iterable[Dict[str, object]],
    info_payloads: Dict[int, Dict[str, object]],
    system_payloads: Dict[int, Dict[str, object]],
) -> pd.DataFrame:
    """Return host-level capacity information for endpoints."""

    endpoint_lookup = {
        int(_first_present(endpoint, "Id", "id") or 0): endpoint
        for endpoint in endpoints
    }
    records: List[Dict[str, object]] = []
    for endpoint_id, endpoint in endpoint_lookup.items():
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        info = info_payloads.get(endpoint_id, {})
        system_df = system_payloads.get(endpoint_id, {})
        if not isinstance(info, dict):
            info = {}
        if not isinstance(system_df, dict):
            system_df = {}
        containers_section = system_df.get("Containers")
        volumes_section = system_df.get("Volumes")

        containers_total = None
        containers_running = None
        containers_stopped = None
        if isinstance(containers_section, dict):
            containers_total = containers_section.get("Total")
            containers_running = containers_section.get("Running")
            containers_stopped = containers_section.get("Stopped")
        elif isinstance(containers_section, (list, tuple, set)):
            containers_total = len(list(containers_section))
        elif isinstance(containers_section, (int, float)):
            containers_total = containers_section

        volumes_total = None
        if isinstance(volumes_section, dict):
            total_count = volumes_section.get("TotalCount")
            if isinstance(total_count, (int, float)):
                volumes_total = total_count
            else:
                total_raw = volumes_section.get("Total")
                if isinstance(total_raw, (int, float)):
                    volumes_total = total_raw
        elif isinstance(volumes_section, (list, tuple, set)):
            volumes_total = len(list(volumes_section))
        elif isinstance(volumes_section, (int, float)):
            volumes_total = volumes_section

        if not isinstance(info, dict):
            info = {}
        if containers_total is None and isinstance(info.get("Containers"), (int, float)):
            containers_total = info.get("Containers")
        if containers_running is None and isinstance(
            info.get("ContainersRunning"), (int, float)
        ):
            containers_running = info.get("ContainersRunning")
        if containers_stopped is None and isinstance(
            info.get("ContainersStopped"), (int, float)
        ):
            containers_stopped = info.get("ContainersStopped")
        if volumes_total is None and isinstance(info.get("Volumes"), (int, float)):
            volumes_total = info.get("Volumes")

        if not isinstance(containers_total, (int, float)):
            containers_total = None
        if not isinstance(containers_running, (int, float)):
            containers_running = None
        if not isinstance(containers_stopped, (int, float)):
            containers_stopped = None
        if not isinstance(volumes_total, (int, float)):
            volumes_total = None
        builder = {
            "endpoint_id": endpoint_id,
            "endpoint_name": endpoint_name,
            "docker_version": info.get("ServerVersion"),
            "architecture": info.get("Architecture"),
            "operating_system": info.get("OperatingSystem"),
            "total_cpus": info.get("NCPU"),
            "total_memory": info.get("MemTotal"),
            "swarm_node": info.get("Swarm", {}).get("ControlAvailable")
            if isinstance(info.get("Swarm"), dict)
            else None,
            "containers_total": containers_total,
            "containers_running": containers_running,
            "containers_stopped": containers_stopped,
            "volumes_total": volumes_total,
            "images_total": system_df.get("ImagesTotal")
            if "ImagesTotal" in system_df
            else info.get("Images"),
            "layers_size": system_df.get("LayersSize"),
        }
        records.append(builder)
    if not records:
        return pd.DataFrame(
            columns=
            [
                "endpoint_id",
                "endpoint_name",
                "docker_version",
                "architecture",
                "operating_system",
                "total_cpus",
                "total_memory",
                "swarm_node",
                "containers_total",
                "containers_running",
                "containers_stopped",
                "volumes_total",
                "images_total",
                "layers_size",
            ]
        )
    return pd.DataFrame.from_records(records)


def normalise_endpoint_volumes(
    endpoints: Iterable[Dict[str, object]],
    volumes_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    endpoint_lookup = {
        int(_first_present(endpoint, "Id", "id") or 0): endpoint
        for endpoint in endpoints
    }
    for endpoint_id, volumes in volumes_by_endpoint.items():
        endpoint = endpoint_lookup.get(endpoint_id, {})
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            labels = volume.get("Labels")
            label_summary = None
            if isinstance(labels, dict):
                label_entries = [
                    f"{key}={value}"
                    for key, value in sorted(labels.items())
                    if value is not None
                ]
                if label_entries:
                    label_summary = ", ".join(label_entries)
            records.append(
                {
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "volume_name": volume.get("Name") or volume.get("name"),
                    "driver": volume.get("Driver"),
                    "scope": volume.get("Scope"),
                    "mountpoint": volume.get("Mountpoint"),
                    "labels": label_summary,
                }
            )
    if not records:
        return pd.DataFrame(
            columns=
            [
                "endpoint_id",
                "endpoint_name",
                "volume_name",
                "driver",
                "scope",
                "mountpoint",
                "labels",
            ]
        )
    return pd.DataFrame.from_records(records)


def normalise_endpoint_images(
    endpoints: Iterable[Dict[str, object]],
    images_by_endpoint: Dict[int, Iterable[Dict[str, object]]],
) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
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
                    created_at = pd.to_datetime(created_raw, unit="s", utc=True).isoformat()
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
            columns=
            [
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
