"""Tests for the Kibana / Elasticsearch log client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
import pytest

from app.services.kibana_client import (
    KibanaClient,
    KibanaClientError,
    build_logs_query,
    load_kibana_client_from_env,
)


def test_build_logs_query_includes_expected_filters():
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    later = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)

    query = build_logs_query(
        hostname="edge-agent-1",
        start_time=now,
        end_time=later,
        container_name="web",
        search_term="error",
        size=123,
    )

    assert query["size"] == 123
    must = query["query"]["bool"]["must"]
    assert {"exists": {"field": "container.name"}} in must
    assert {"term": {"data_stream.dataset": "docker-container_logs"}} in must
    assert {"term": {"host.hostname.keyword": "edge-agent-1"}} in must
    assert {"term": {"container.name.keyword": "web"}} in must
    assert {"match_phrase": {"message": "error"}} in must

    time_filter = query["query"]["bool"]["filter"][0]["range"]["@timestamp"]
    assert time_filter["gte"].startswith("2024-01-01T00:00:00")
    assert time_filter["lte"].startswith("2024-01-01T01:00:00")


def test_fetch_logs_returns_dataframe(monkeypatch):
    captured_payload: Dict[str, Any] = {}

    def fake_post(url, headers, json, timeout, verify):  # type: ignore[override]
        captured_payload.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
                "verify": verify,
            }
        )

        class DummyResponse:
            status_code = 200

            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> Dict[str, Any]:
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "@timestamp": "2024-01-01T01:23:45.000Z",
                                    "message": "container log line",
                                    "container": {"name": "web"},
                                    "host": {"hostname": "edge-agent-1"},
                                    "log": {"level": "info"},
                                }
                            }
                        ]
                    }
                }

        return DummyResponse()

    monkeypatch.setattr("app.services.kibana_client.requests.post", fake_post)

    client = KibanaClient(endpoint="https://elastic.example.com/_search", api_key="secret")
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    later = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    result = client.fetch_logs(hostname="edge-agent-1", start_time=now, end_time=later)

    assert captured_payload["url"] == "https://elastic.example.com/_search"
    assert captured_payload["headers"]["Authorization"] == "ApiKey secret"
    assert captured_payload["headers"]["kbn-xsrf"] == "streamlit-portainer-dashboard"
    assert isinstance(result, pd.DataFrame)
    assert not result.empty
    assert list(result.columns) == [
        "timestamp",
        "agent_hostname",
        "container_name",
        "log_level",
        "message",
    ]


def test_load_kibana_client_from_env(monkeypatch):
    monkeypatch.setenv("KIBANA_LOGS_ENDPOINT", "https://elastic.example.com/_search")
    monkeypatch.setenv("KIBANA_API_KEY", "abc123")
    monkeypatch.setenv("KIBANA_VERIFY_SSL", "false")
    monkeypatch.setenv("KIBANA_TIMEOUT_SECONDS", "15")

    client = load_kibana_client_from_env()
    assert isinstance(client, KibanaClient)

    # Ensure the helper returns ``None`` when configuration is incomplete.
    monkeypatch.delenv("KIBANA_LOGS_ENDPOINT", raising=False)
    monkeypatch.delenv("KIBANA_API_KEY", raising=False)
    assert load_kibana_client_from_env() is None


def test_fetch_logs_raises_on_error_payload(monkeypatch):
    def fake_post(url, headers, json, timeout, verify):  # type: ignore[override]
        class DummyResponse:
            status_code = 200

            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> Dict[str, Any]:
                return {
                    "statusCode": 400,
                    "error": "Bad Request",
                    "message": "kbn-xsrf header is required",
                }

        return DummyResponse()

    monkeypatch.setattr("app.services.kibana_client.requests.post", fake_post)

    client = KibanaClient(endpoint="https://elastic.example.com/_search", api_key="secret")
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    later = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(KibanaClientError) as excinfo:
        client.fetch_logs(hostname="edge-agent-1", start_time=now, end_time=later)

    assert "kbn-xsrf header is required" in str(excinfo.value)
