"""Tests for the Portainer client utilities."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import portainer_client
from app.portainer_client import (
    PortainerAPIError,
    PortainerClient,
    normalise_container_details,
    normalise_endpoint_metadata,
    normalise_endpoint_host_metrics,
    normalise_endpoint_volumes,
    normalise_endpoint_images,
    normalise_endpoint_stacks,
)


def test_list_edge_endpoints_requests_status(monkeypatch):
    """The edge endpoint request should include status information."""

    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        captured["path"] = path
        captured["params"] = params
        return []

    monkeypatch.setattr(client, "_request", fake_request)

    client.list_edge_endpoints()

    assert captured["path"] == "/endpoints"
    assert captured["params"] == {"edge": "true", "status": "true"}


def test_list_stacks_for_endpoint_merges_edge_payloads(monkeypatch):
    """Stacks fetched from both endpoints should be combined."""

    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        assert params == {"endpointId": 9}
        if path == "/stacks":
            return [{"Id": 101, "Name": "compose"}]
        if path == "/edge/stacks":
            return [
                {"Id": 101, "Name": "compose"},
                {"Id": 202, "Name": "edge-app"},
            ]
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(client, "_request", fake_request)

    stacks = client.list_stacks_for_endpoint(9)

    assert stacks == [
        {"Id": 101, "Name": "compose"},
        {"Id": 202, "Name": "edge-app"},
    ]


def test_create_backup_posts_to_backup_endpoint(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    class DummyResponse:
        headers = {"Content-Disposition": "attachment; filename*=UTF-8''portainer.tar.gz"}
        content = b"backup-data"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, *, json=None, timeout=None):  # type: ignore[override]
        captured.update(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        return DummyResponse()

    monkeypatch.setattr(client._session, "post", fake_post)

    payload, filename = client.create_backup(password="secret")

    assert captured["url"] == "https://portainer.example/api/backup"
    assert captured["json"] == {"password": "secret"}
    assert payload == b"backup-data"
    assert filename == "portainer.tar.gz"
    assert client._session.headers["X-API-Key"] == "token"


def test_get_stack_image_status(monkeypatch):
    """Stack image status requests should hit the expected endpoint."""

    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        captured["path"] = path
        captured["params"] = params
        return {"Status": "updated"}

    monkeypatch.setattr(client, "_request", fake_request)

    payload = client.get_stack_image_status(42)

    assert captured["path"] == "/stacks/42/images_status"
    assert captured["params"] is None
    assert payload == {"Status": "updated"}


def test_create_backup_raises_on_request_errors(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    def fake_post(*args, **kwargs):  # type: ignore[override]
        raise requests.RequestException("boom")

    monkeypatch.setattr(client._session, "post", fake_post)

    with pytest.raises(PortainerAPIError):
        client.create_backup()


def test_normalise_endpoint_stacks_keeps_zero_status():
    """A status of ``0`` should not be treated as missing."""

    endpoints = [
        {
            "Id": 7,
            "Name": "edge-0",
            "Status": 0,
        }
    ]
    result = normalise_endpoint_stacks(endpoints, {7: []})

    assert result.loc[0, "endpoint_status"] == 0


def test_normalise_endpoint_stacks_handles_endpoint_scoped_payload():
    """Stacks lacking endpoint metadata should still be associated."""

    endpoints = [
        {
            "Id": 12,
            "Name": "edge-a",
            "Status": 1,
        }
    ]
    stacks = {
        12: [
            {
                "Id": 99,
                "Name": "demo",
                "Status": 1,
                "Type": 2,
            }
        ]
    }

    result = normalise_endpoint_stacks(endpoints, stacks)

    assert result.loc[0, "stack_id"] == 99
    assert result.loc[0, "stack_name"] == "demo"
    assert result.loc[0, "stack_status"] == 1
    assert result.loc[0, "stack_type"] == 2


def test_normalise_endpoint_stacks_ignores_foreign_metadata():
    """Stacks with explicit endpoint metadata should not leak to other rows."""

    endpoints = [
        {"Id": 3, "Name": "local", "Status": 1},
        {"Id": 4, "Name": "edge-remote", "Status": 0},
    ]
    stacks = {
        3: [
            {
                "Id": 10,
                "Name": "local-only",
                "Status": 1,
            },
            {
                "Id": 42,
                "Name": "remote-app",
                "Status": 1,
                "EndpointId": 4,
            },
        ],
        4: [
            {
                "Id": 42,
                "Name": "remote-app",
                "Status": 1,
                "EndpointId": 4,
            }
        ],
    }

    result = normalise_endpoint_stacks(endpoints, stacks)

    local_rows = result[result["endpoint_id"] == 3]
    assert list(local_rows["stack_id"]) == [10]

    remote_rows = result[result["endpoint_id"] == 4]
    assert list(remote_rows["stack_id"]) == [42]


def test_inspect_container_hits_expected_endpoint(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        captured["path"] = path
        captured["params"] = params
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    client.inspect_container(2, "abc123")

    assert captured["path"] == "/endpoints/2/docker/containers/abc123/json"
    assert captured["params"] is None


def test_container_stats_request_streams_once(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        captured["path"] = path
        captured["params"] = params
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    client.get_container_stats(5, "deadbeef")

    assert captured["path"] == "/endpoints/5/docker/containers/deadbeef/stats"
    assert captured["params"] == {"stream": "false"}


def test_list_volumes_handles_dict_payload(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    def fake_request(path: str, *, params=None):  # type: ignore[override]
        assert path == "/endpoints/3/docker/volumes"
        return {
            "Volumes": [
                {"Name": "data", "Driver": "local", "Mountpoint": "/var/lib/data"},
                "unexpected",
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)

    volumes = client.list_volumes_for_endpoint(3)

    assert volumes == [
        {"Name": "data", "Driver": "local", "Mountpoint": "/var/lib/data"}
    ]


def test_normalise_endpoint_metadata_extracts_agent_details():
    endpoints = [
        {
            "Id": 9,
            "Name": "edge-a",
            "Status": 1,
            "Agent": {"Version": "2.18.1", "Platform": "linux", "Os": "debian"},
            "GroupId": 12,
            "Tags": ["prod", "site-a"],
            "LastCheckInDate": 1_700_000_000,
            "URL": "tcp://127.0.0.1:9001",
        }
    ]

    df = normalise_endpoint_metadata(endpoints)

    assert df.loc[0, "agent_version"] == "2.18.1"
    assert df.loc[0, "tags"] == "prod, site-a"
    assert df.loc[0, "last_check_in"].startswith("2023-")
    assert df.loc[0, "agent_hostname"] == "127.0.0.1"


def test_normalise_container_details_combines_inspect_and_stats():
    endpoints = [{"Id": 4, "Name": "edge-4"}]
    containers = {
        4: [
            {
                "Id": "abcdef",
                "Names": ["/web"],
            }
        ]
    }
    inspect = {
        4: {
            "abcdef": {
                "State": {
                    "Health": {"Status": "healthy"},
                    "ExitCode": 0,
                    "FinishedAt": "2024-01-01T00:00:00Z",
                },
                "Mounts": [
                    {"Destination": "/data", "Source": "/srv/data"},
                ],
                "NetworkSettings": {"Networks": {"bridge": {}}},
                "Config": {"Labels": {"app": "demo"}},
            }
        }
    }
    stats = {
        4: {
            "abcdef": {
                "cpu_stats": {
                    "cpu_usage": {
                        "total_usage": 200.0,
                        "percpu_usage": [1, 2],
                    },
                    "system_cpu_usage": 400.0,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 100.0},
                    "system_cpu_usage": 300.0,
                },
                "memory_stats": {"usage": 50.0, "limit": 100.0},
            }
        }
    }

    df = normalise_container_details(endpoints, containers, inspect, stats)

    assert df.loc[0, "health_status"] == "healthy"
    assert df.loc[0, "mounts"] == "/data ← /srv/data"
    assert df.loc[0, "labels"] == "app=demo"
    assert pytest.approx(df.loc[0, "cpu_percent"], rel=1e-6) == 200.0
    assert pytest.approx(df.loc[0, "memory_percent"], rel=1e-6) == 50.0


def test_normalise_endpoint_host_metrics_combines_sources():
    endpoints = [{"Id": 2, "Name": "edge-2"}]
    info = {2: {"ServerVersion": "24.0", "NCPU": 4, "MemTotal": 1024}}
    usage = {
        2: {
            "Containers": {"Total": 10, "Running": 7, "Stopped": 3},
            "Volumes": {"TotalCount": 6},
            "ImagesTotal": 9,
            "LayersSize": 12345,
        }
    }

    df = normalise_endpoint_host_metrics(endpoints, info, usage)

    assert df.loc[0, "containers_running"] == 7
    assert df.loc[0, "volumes_total"] == 6
    assert df.loc[0, "images_total"] == 9


def test_normalise_endpoint_host_metrics_falls_back_to_host_info():
    endpoints = [{"Id": 3, "Name": "edge-3"}]
    info = {
        3: {
            "ServerVersion": "25.0",
            "NCPU": 8,
            "MemTotal": 2048,
            "Containers": 12,
            "ContainersRunning": 5,
            "ContainersStopped": 7,
        }
    }
    usage = {3: {"Containers": [object(), object()], "Volumes": [{}, {}, {}]}}

    df = normalise_endpoint_host_metrics(endpoints, info, usage)

    assert df.loc[0, "containers_total"] == 2
    assert df.loc[0, "containers_running"] == 5
    assert df.loc[0, "containers_stopped"] == 7
    assert df.loc[0, "volumes_total"] == 3


def test_normalise_endpoint_volumes_preserves_labels():
    endpoints = [{"Id": 1, "Name": "edge-1"}]
    volumes = {1: [{"Name": "data", "Driver": "local", "Labels": {"managed": "true"}}]}

    df = normalise_endpoint_volumes(endpoints, volumes)

    assert df.loc[0, "volume_name"] == "data"
    assert df.loc[0, "labels"] == "managed=true"


def test_normalise_endpoint_images_serialises_reference():
    endpoints = [{"Id": 5, "Name": "edge-5"}]
    images = {
        5: [
            {
                "Id": "sha256:123",
                "RepoTags": ["demo:latest"],
                "Size": 2048,
                "Created": 1_700_000_000,
                "Dangling": False,
            }
        ]
    }

    df = normalise_endpoint_images(endpoints, images)

    assert df.loc[0, "reference"] == "demo:latest"
    assert df.loc[0, "size"] == 2048
    assert bool(df.loc[0, "dangling"]) is False
