"""Portainer data normalisation functions for DataFrames and dicts."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from portainer_dashboard.services.portainer_utils import (
    _coerce_int,
    _first_present,
    _stack_has_endpoint_metadata,
    _stack_targets_endpoint,
)

LOGGER = logging.getLogger(__name__)


def _determine_edge_agent_status(
    endpoint: dict[str, object],
    raw_status: object,
) -> int:
    """Determine the actual status for an edge agent.

    Edge agents may report status differently than regular Docker endpoints.
    This function checks multiple indicators to determine if an edge agent
    is actually online or offline.

    Returns:
        1 for Online, 2 for Offline
    """
    import time

    # Check endpoint type - Type 4 is Edge Agent, Type 7 is Edge Agent (async)
    endpoint_type = _coerce_int(_first_present(endpoint, "Type", "type"))
    is_edge_agent = endpoint_type in (4, 7)

    # If raw status is valid and it's not an edge agent, trust it
    if not is_edge_agent:
        if raw_status == 1:
            return 1
        if raw_status == 2:
            return 2
        # For non-edge, unknown status defaults to offline
        return 2

    # For edge agents, check the heartbeat/check-in time
    # EdgeCheckinInterval is in seconds
    checkin_interval = _coerce_int(
        _first_present(endpoint, "EdgeCheckinInterval", "edgeCheckinInterval")
    )

    # Get the last check-in timestamp
    last_checkin = _first_present(
        endpoint,
        "LastCheckInDate",
        "EdgeLastCheckInDate",
        "LastCheckIn",
        "lastCheckInDate",
    )

    # Convert to Unix timestamp if possible
    last_checkin_ts: float | None = None
    if isinstance(last_checkin, (int, float)) and last_checkin > 0:
        last_checkin_ts = float(last_checkin)
    elif isinstance(last_checkin, str) and last_checkin:
        try:
            parsed = pd.to_datetime(last_checkin, utc=True)
            if not pd.isna(parsed):
                last_checkin_ts = parsed.timestamp()
        except (ValueError, TypeError):
            pass

    # If we have a last check-in time, use it to determine status
    if last_checkin_ts is not None:
        now = time.time()
        time_since_checkin = now - last_checkin_ts

        # Default check-in interval for edge agents is typically 5 seconds
        # Consider offline if no check-in for 3x the interval (or 60 seconds if unknown)
        expected_interval = checkin_interval if checkin_interval and checkin_interval > 0 else 5
        offline_threshold = max(expected_interval * 3, 60)

        if time_since_checkin <= offline_threshold:
            return 1  # Online
        else:
            return 2  # Offline

    # Check the Heartbeat field if available
    heartbeat = _first_present(endpoint, "Heartbeat", "heartbeat")
    if heartbeat is True or heartbeat == 1:
        return 1

    # Fall back to raw status
    if raw_status == 1:
        return 1
    if raw_status == 2:
        return 2

    # Edge agents with no status info default to offline
    return 2


def normalise_endpoint_metadata(
    endpoints: list[dict[str, object]]
) -> pd.DataFrame:
    """Return a dataframe with enriched endpoint metadata."""
    records: list[dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        raw_status = _first_present(endpoint, "Status", "status")

        # Use enhanced status detection for edge agents
        endpoint_status = _determine_edge_agent_status(endpoint, raw_status)

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


def normalise_endpoint_metadata_dict(
    endpoints: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Return a list of dicts with enriched endpoint metadata.

    This is a dict-based alternative to normalise_endpoint_metadata() that
    avoids pandas DataFrame overhead when the data will be serialized to
    dicts anyway (e.g., for caching).
    """
    records: list[dict[str, object]] = []
    for endpoint in endpoints:
        endpoint_id = int(_first_present(endpoint, "Id", "id") or 0)
        endpoint_name = endpoint.get("Name") or endpoint.get("name")
        raw_status = _first_present(endpoint, "Status", "status")

        # Use enhanced status detection for edge agents
        endpoint_status = _determine_edge_agent_status(endpoint, raw_status)

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
            "EdgeLastCheckInDate",
            "LastCheckIn",
        )
        last_check_iso: str | None = None
        if isinstance(last_check_in, (int, float)):
            try:
                from datetime import datetime, timezone
                last_check_iso = datetime.fromtimestamp(
                    last_check_in, tz=timezone.utc
                ).isoformat()
            except (ValueError, OverflowError, OSError):
                last_check_iso = None
        elif isinstance(last_check_in, str) and last_check_in:
            # Keep string as-is if already formatted
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
    return records


def normalise_endpoint_stacks_dict(
    endpoints: list[dict[str, object]],
    stacks_by_endpoint: dict[int, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Return a list of dicts mapping endpoints to stacks.

    This is a dict-based alternative to normalise_endpoint_stacks() that
    avoids pandas DataFrame overhead when the data will be serialized to
    dicts anyway (e.g., for caching).
    """
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
    return records


def normalise_endpoint_containers_dict(
    endpoints: list[dict[str, object]],
    containers_by_endpoint: dict[int, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Return a list of dicts mapping endpoints to containers.

    This is a dict-based alternative to normalise_endpoint_containers() that
    avoids pandas DataFrame overhead when the data will be serialized to
    dicts anyway (e.g., for caching).
    """
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
                try:
                    from datetime import datetime, timezone
                    created_at = datetime.fromtimestamp(
                        created_raw, tz=timezone.utc
                    ).isoformat()
                except (ValueError, OverflowError, OSError):
                    created_at = None
            elif isinstance(created_raw, str):
                created_at = created_raw
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
    return records


__all__ = [
    "_determine_edge_agent_status",
    "normalise_endpoint_containers",
    "normalise_endpoint_containers_dict",
    "normalise_endpoint_images",
    "normalise_endpoint_metadata",
    "normalise_endpoint_metadata_dict",
    "normalise_endpoint_stacks",
    "normalise_endpoint_stacks_dict",
]
