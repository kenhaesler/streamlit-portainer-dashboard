"""Async Kibana/Elasticsearch client for log retrieval."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from portainer_dashboard.config import KibanaSettings, get_settings

LOGGER = logging.getLogger(__name__)


class KibanaClientError(RuntimeError):
    """Raised when log retrieval from Kibana fails."""


@dataclass(slots=True)
class KibanaLogEntry:
    """A normalised representation of a single log entry."""

    timestamp: str
    message: str
    container_name: str | None = None
    agent_hostname: str | None = None
    log_level: str | None = None
    raw: Mapping[str, Any] | None = None


def build_logs_query(
    *,
    hostname: str,
    start_time: datetime,
    end_time: datetime,
    container_name: str | None = None,
    search_term: str | None = None,
    size: int = 200,
) -> dict[str, Any]:
    """Return the Elasticsearch DSL query used to fetch logs."""
    must_clauses: list[dict[str, Any]] = [
        {"exists": {"field": "container.name"}},
        {"term": {"data_stream.dataset": "docker-container_logs"}},
        {"term": {"host.hostname.keyword": hostname}},
    ]

    if container_name:
        must_clauses.append({"term": {"container.name.keyword": container_name}})

    if search_term:
        must_clauses.append({"match_phrase": {"message": search_term}})

    query: dict[str, Any] = {
        "size": max(1, min(size, 1000)),
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": start_time.isoformat(),
                                "lte": end_time.isoformat(),
                            }
                        }
                    }
                ],
            }
        },
    }

    return query


@dataclass
class AsyncKibanaClient:
    """Async client for querying Kibana / Elasticsearch APIs."""

    endpoint: str
    api_key: str
    verify_ssl: bool = True
    timeout: int = 30

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("endpoint is required")
        if not self.api_key:
            raise ValueError("api_key is required")
        self.endpoint = self.endpoint.rstrip("/")

    async def _request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"ApiKey {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "kbn-xsrf": "portainer-dashboard",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, verify=self.verify_ssl
        ) as client:
            try:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=dict(payload),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise KibanaClientError(f"Failed to query Kibana logs: {exc}") from exc
            try:
                payload_json = response.json()
            except ValueError as exc:
                raise KibanaClientError("Kibana response was not valid JSON") from exc
            if not isinstance(payload_json, Mapping):
                raise KibanaClientError("Kibana response was not a JSON object")
            status_code = payload_json.get("statusCode")
            try:
                status_code_int = int(status_code) if status_code is not None else None
            except (TypeError, ValueError):
                status_code_int = None
            if status_code_int is not None and status_code_int >= 400:
                message = payload_json.get("message") or payload_json.get("error")
                raise KibanaClientError(
                    f"Kibana returned an error response: {message or status_code_int}"
                )
            if payload_json.get("error") and payload_json.get("message"):
                raise KibanaClientError(
                    f"Kibana returned an error response: {payload_json['message']}"
                )
            return payload_json

    async def fetch_logs(
        self,
        *,
        hostname: str,
        start_time: datetime,
        end_time: datetime,
        container_name: str | None = None,
        search_term: str | None = None,
        size: int = 200,
    ) -> pd.DataFrame:
        """Fetch log entries for an edge agent within the provided time window."""
        if not hostname.strip():
            raise ValueError("hostname is required")

        query = build_logs_query(
            hostname=hostname.strip(),
            start_time=start_time,
            end_time=end_time,
            container_name=container_name.strip() if container_name else None,
            search_term=search_term.strip() if search_term else None,
            size=size,
        )
        payload = await self._request(query)
        hits = payload.get("hits", {})
        if not isinstance(hits, Mapping):
            hits = {}
        records_raw = hits.get("hits", [])
        if not isinstance(records_raw, list):
            records_raw = []

        entries: list[KibanaLogEntry] = []
        for record in records_raw:
            if not isinstance(record, Mapping):
                continue
            source = record.get("_source", {})
            if not isinstance(source, Mapping):
                continue
            timestamp = str(source.get("@timestamp", ""))
            message = str(source.get("message", ""))
            container_name_value: str | None = None
            container_source = source.get("container")
            if isinstance(container_source, Mapping):
                container_name_value = (
                    container_source.get("name")
                    or container_source.get("id")
                    or container_source.get("image")
                )
                if container_name_value:
                    container_name_value = str(container_name_value)
            elif "container.name" in source:
                container_name_value = str(source.get("container.name"))

            host_value: str | None = None
            host_source = source.get("host")
            if isinstance(host_source, Mapping):
                host_value = host_source.get("hostname") or host_source.get("name")
                if host_value:
                    host_value = str(host_value)
            elif "host.hostname" in source:
                host_value = str(source.get("host.hostname"))

            log_level_value: str | None = None
            log_source = source.get("log")
            if isinstance(log_source, Mapping):
                log_level_value = log_source.get("level")
                if log_level_value:
                    log_level_value = str(log_level_value)
            elif "log.level" in source:
                log_level_value = str(source.get("log.level"))

            entries.append(
                KibanaLogEntry(
                    timestamp=timestamp,
                    message=message,
                    container_name=container_name_value,
                    agent_hostname=host_value,
                    log_level=log_level_value,
                    raw=dict(source),
                )
            )

        if not entries:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "agent_hostname",
                    "container_name",
                    "log_level",
                    "message",
                ]
            )

        return pd.DataFrame.from_records(
            [
                {
                    "timestamp": entry.timestamp,
                    "agent_hostname": entry.agent_hostname,
                    "container_name": entry.container_name,
                    "log_level": entry.log_level,
                    "message": entry.message,
                }
                for entry in entries
            ]
        )


def create_kibana_client(settings: KibanaSettings | None = None) -> AsyncKibanaClient | None:
    """Create an async Kibana client from settings when configured."""
    if settings is None:
        settings = get_settings().kibana
    if not settings.is_configured:
        return None
    return AsyncKibanaClient(
        endpoint=settings.logs_endpoint or "",
        api_key=settings.api_key or "",
        verify_ssl=settings.verify_ssl,
        timeout=settings.timeout,
    )


__all__ = [
    "AsyncKibanaClient",
    "KibanaClientError",
    "KibanaLogEntry",
    "build_logs_query",
    "create_kibana_client",
]
