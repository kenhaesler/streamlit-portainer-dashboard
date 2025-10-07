"""Helpers for querying Kibana / Elasticsearch log streams."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd
import requests

__all__ = [
    "KibanaClient",
    "KibanaClientError",
    "KibanaLogEntry",
    "build_logs_query",
    "load_kibana_client_from_env",
]


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


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    cleaned = value.strip().lower()
    if not cleaned:
        return default
    return cleaned not in {"0", "false", "no", "off"}


def build_logs_query(
    *,
    hostname: str,
    start_time: datetime,
    end_time: datetime,
    container_name: str | None = None,
    search_term: str | None = None,
    size: int = 200,
) -> Dict[str, Any]:
    """Return the Elasticsearch DSL query used to fetch logs."""

    must_clauses: List[Dict[str, Any]] = [
        {"exists": {"field": "container.name"}},
        {"term": {"data_stream.dataset": "docker-container_logs"}},
        {"term": {"host.hostname.keyword": hostname}},
    ]

    if container_name:
        must_clauses.append({"term": {"container.name.keyword": container_name}})

    if search_term:
        must_clauses.append({"match_phrase": {"message": search_term}})

    query: Dict[str, Any] = {
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


class KibanaClient:
    """Lightweight client for querying Kibana / Elasticsearch APIs."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        verify_ssl: bool = True,
        timeout: int = 30,
    ) -> None:
        if not endpoint:
            raise ValueError("endpoint is required")
        if not api_key:
            raise ValueError("api_key is required")
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._verify_ssl = verify_ssl
        self._timeout = timeout

    def _request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"ApiKey {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = requests.post(
                self._endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network errors
            raise KibanaClientError(f"Failed to query Kibana logs: {exc}") from exc
        try:
            return response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - invalid server response
            raise KibanaClientError("Kibana response was not valid JSON") from exc

    def fetch_logs(
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
        payload = self._request(query)
        hits = payload.get("hits", {})
        records_raw: Iterable[Mapping[str, Any]] = hits.get("hits", [])  # type: ignore[assignment]

        entries: List[KibanaLogEntry] = []
        for record in records_raw:
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
                    raw=source,
                )
            )

        if not entries:
            return pd.DataFrame(
                columns=["timestamp", "agent_hostname", "container_name", "log_level", "message"]
            )

        return pd.DataFrame.from_records(
            (
                {
                    "timestamp": entry.timestamp,
                    "agent_hostname": entry.agent_hostname,
                    "container_name": entry.container_name,
                    "log_level": entry.log_level,
                    "message": entry.message,
                }
                for entry in entries
            )
        )


def load_kibana_client_from_env() -> KibanaClient | None:
    """Create a :class:`KibanaClient` from environment variables when available."""

    endpoint = os.getenv("KIBANA_LOGS_ENDPOINT", "").strip()
    api_key = os.getenv("KIBANA_API_KEY", "").strip()
    if not endpoint or not api_key:
        return None

    verify_ssl = _parse_bool(os.getenv("KIBANA_VERIFY_SSL"), default=True)
    timeout_raw = os.getenv("KIBANA_TIMEOUT_SECONDS", "").strip()
    timeout = 30
    if timeout_raw:
        try:
            timeout = max(1, int(float(timeout_raw)))
        except ValueError:
            timeout = 30

    return KibanaClient(
        endpoint=endpoint,
        api_key=api_key,
        verify_ssl=verify_ssl,
        timeout=timeout,
    )
