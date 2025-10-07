from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.dashboard_state as dashboard_state
from app.settings import PortainerEnvironment


def test_fetch_portainer_payload_normalises_swagger_fixture(monkeypatch):
    """End-to-end payload parsing should reflect the Swagger contract."""

    environment = PortainerEnvironment(
        name="Demo",
        api_url="https://demo.example/api",
        api_key="token",
        verify_ssl=True,
    )

    endpoints = [
        {
            "Id": 101,
            "Name": "edge-alpha",
            "Status": 1,
            "Agent": {"Version": "2.13.0", "Platform": "linux", "Os": "Ubuntu"},
            "GroupId": 5,
            "Tags": ["prod", "region-a"],
            "LastCheckInDate": 1_700_000_000,
            "URL": "tcp://edge-alpha:9001",
        },
        {
            "Id": 102,
            "Name": "edge-beta",
            "Status": 0,
            "Agent": {"Version": "2.13.0", "Platform": "linux", "Os": "Debian"},
            "GroupId": 5,
            "Tags": ["staging"],
            "LastCheckInDate": "2024-05-01T12:00:00Z",
            "URL": "tcp://edge-beta:9001",
        },
    ]

    stack_payloads = {
        101: [
            {"Id": 201, "Name": "alpha-app", "Status": 1, "Type": 2, "EndpointId": 101},
            {
                "Id": 202,
                "Name": "alpha-db",
                "Status": 0,
                "Type": 1,
                "deploymentInfo": {"101": {"EndpointId": 101}},
            },
        ],
        102: [
            {"Id": 301, "Name": "beta-app", "Status": 2, "Type": 2, "EndpointID": 102},
        ],
    }

    container_payloads = {
        101: [
            {
                "Id": "abc123",
                "Names": ["/alpha-web"],
                "Image": "nginx:latest",
                "State": "running",
                "Status": "Up 5 minutes",
                "RestartCount": 0,
                "Created": 1_700_100_000,
                "Ports": [
                    {"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
                ],
            }
        ],
        102: [
            {
                "Id": "def456",
                "Names": ["/beta-worker"],
                "Image": "busybox:latest",
                "State": "exited",
                "Status": "Exited",
                "RestartCount": 3,
                "Created": "2024-05-01T12:34:00Z",
                "Ports": [],
            }
        ],
    }

    inspect_payloads = {
        101: {
            "abc123": {
                "State": {
                    "Health": {"Status": "healthy"},
                    "ExitCode": 0,
                    "FinishedAt": "2024-05-01T11:00:00Z",
                },
                "Mounts": [{"Destination": "/data", "Source": "/srv/data"}],
                "NetworkSettings": {"Networks": {"bridge": {}}},
                "Config": {"Labels": {"app": "alpha", "tier": "frontend"}},
            }
        },
        102: {
            "def456": {
                "State": {"ExitCode": 1, "FinishedAt": "2024-05-01T10:00:00Z"},
                "Mounts": [],
                "NetworkSettings": {"Networks": {}},
                "Config": {"Labels": {"app": "beta"}},
            }
        },
    }

    stats_payloads = {
        101: {
            "abc123": {
                "cpu_stats": {
                    "cpu_usage": {
                        "total_usage": 400.0,
                        "percpu_usage": [1, 2],
                    },
                    "system_cpu_usage": 1_000.0,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 200.0},
                    "system_cpu_usage": 800.0,
                },
                "memory_stats": {"usage": 256.0, "limit": 1_024.0},
            }
        },
        102: {
            "def456": {
                "cpu_stats": {
                    "cpu_usage": {
                        "total_usage": 50.0,
                        "percpu_usage": [1],
                    },
                    "system_cpu_usage": 200.0,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 40.0},
                    "system_cpu_usage": 150.0,
                },
                "memory_stats": {"usage": 64.0, "limit": 512.0},
            }
        },
    }

    host_info_payloads = {
        101: {
            "ServerVersion": "24.0",
            "Architecture": "x86_64",
            "OperatingSystem": "Ubuntu",
            "NCPU": 8,
            "MemTotal": 16_000_000_000,
            "Swarm": {"ControlAvailable": True},
            "Images": 25,
        },
        102: {
            "ServerVersion": "24.0",
            "Architecture": "arm64",
            "OperatingSystem": "Debian",
            "NCPU": 4,
            "MemTotal": 8_000_000_000,
            "Swarm": {"ControlAvailable": False},
            "Images": 10,
        },
    }

    host_usage_payloads = {
        101: {
            "Containers": {"Total": 10, "Running": 7, "Stopped": 3},
            "Volumes": {"TotalCount": 5},
            "ImagesTotal": 20,
            "LayersSize": 123_456,
        },
        102: {
            "Containers": {"Total": 5, "Running": 2, "Stopped": 3},
            "Volumes": {"Total": 2},
            "ImagesTotal": 8,
            "LayersSize": 654_321,
        },
    }

    volume_payloads = {
        101: [
            {
                "Name": "alpha-data",
                "Driver": "local",
                "Scope": "local",
                "Mountpoint": "/var/lib/docker/volumes/alpha-data",
                "Labels": {"project": "alpha", "env": "prod"},
            }
        ],
        102: [
            {
                "Name": "beta-tmp",
                "Driver": "local",
                "Scope": "local",
                "Mountpoint": "/var/lib/docker/volumes/beta-tmp",
                "Labels": {},
            }
        ],
    }

    image_payloads = {
        101: [
            {
                "Id": "sha256:1",
                "RepoTags": ["alpha/web:1.0"],
                "Size": 2_048,
                "Created": 1_699_999_999,
                "Dangling": False,
            },
            {
                "Id": "sha256:2",
                "RepoDigests": ["alpha/db@sha256:aaa"],
                "Size": 4_096,
                "Created": 1_699_000_000,
                "Dangling": True,
            },
        ],
        102: [
            {
                "Id": "sha256:3",
                "RepoTags": ["beta/worker:2.3"],
                "Size": 1_024,
                "Created": 1_698_000_000,
                "Dangling": False,
            }
        ],
    }

    stack_calls: list[int] = []
    container_calls: list[tuple[int, bool]] = []
    inspect_calls: list[tuple[int, str]] = []
    stats_calls: list[tuple[int, str]] = []
    host_info_calls: list[int] = []
    host_usage_calls: list[int] = []
    volume_calls: list[int] = []
    image_calls: list[int] = []

    class FakePortainerClient:
        def __init__(self, base_url: str, api_key: str, verify_ssl: bool) -> None:
            assert base_url == environment.api_url
            assert api_key == environment.api_key
            assert verify_ssl is True

        def list_edge_endpoints(self) -> list[dict[str, object]]:
            return endpoints

        def list_stacks_for_endpoint(self, endpoint_id: int) -> list[dict[str, object]]:
            stack_calls.append(endpoint_id)
            return list(stack_payloads.get(endpoint_id, []))

        def list_containers_for_endpoint(
            self, endpoint_id: int, *, include_stopped: bool
        ) -> list[dict[str, object]]:
            container_calls.append((endpoint_id, include_stopped))
            return list(container_payloads.get(endpoint_id, []))

        def get_endpoint_host_info(self, endpoint_id: int) -> dict[str, object]:
            host_info_calls.append(endpoint_id)
            return dict(host_info_payloads.get(endpoint_id, {}))

        def get_endpoint_system_df(self, endpoint_id: int) -> dict[str, object]:
            host_usage_calls.append(endpoint_id)
            return dict(host_usage_payloads.get(endpoint_id, {}))

        def list_volumes_for_endpoint(self, endpoint_id: int) -> list[dict[str, object]]:
            volume_calls.append(endpoint_id)
            return list(volume_payloads.get(endpoint_id, []))

        def list_images_for_endpoint(self, endpoint_id: int) -> list[dict[str, object]]:
            image_calls.append(endpoint_id)
            return list(image_payloads.get(endpoint_id, []))

        def inspect_container(self, endpoint_id: int, container_id: str) -> dict[str, object]:
            inspect_calls.append((endpoint_id, container_id))
            return dict(inspect_payloads.get(endpoint_id, {}).get(container_id, {}))

        def get_container_stats(self, endpoint_id: int, container_id: str) -> dict[str, object]:
            stats_calls.append((endpoint_id, container_id))
            return dict(stats_payloads.get(endpoint_id, {}).get(container_id, {}))

    monkeypatch.setattr(dashboard_state, "PortainerClient", FakePortainerClient)

    (
        stack_df_min,
        container_df_min,
        endpoint_df_min,
        container_details_min,
        host_df_min,
        volume_df_min,
        image_df_min,
        warnings_min,
    ) = dashboard_state._fetch_portainer_payload(
        (environment,),
        include_stopped=False,
        include_container_details=False,
        include_resource_utilisation=False,
    )

    assert stack_calls == [101, 102]
    assert container_calls == [(101, False), (102, False)]
    assert inspect_calls == []
    assert stats_calls == []
    assert host_info_calls == []
    assert host_usage_calls == []
    assert volume_calls == []
    assert image_calls == []

    assert warnings_min == []
    assert container_details_min["cpu_percent"].dropna().empty
    assert container_details_min["memory_percent"].dropna().empty
    assert container_details_min["health_status"].dropna().empty
    if not host_df_min.empty:
        assert host_df_min["total_cpus"].dropna().empty
        assert host_df_min["containers_total"].dropna().empty
    assert volume_df_min.empty
    assert image_df_min.empty

    stack_calls.clear()
    container_calls.clear()
    inspect_calls.clear()
    stats_calls.clear()
    host_info_calls.clear()
    host_usage_calls.clear()
    volume_calls.clear()
    image_calls.clear()

    (
        stack_df,
        container_df,
        endpoint_df,
        container_details_df,
        host_df,
        volume_df,
        image_df,
        warnings,
    ) = dashboard_state._fetch_portainer_payload(
        (environment,),
        include_stopped=False,
        include_container_details=True,
        include_resource_utilisation=True,
    )

    assert stack_calls == [101, 102]
    assert container_calls == [(101, False), (102, False)]
    assert inspect_calls == [(101, "abc123"), (102, "def456")]
    assert stats_calls == [(101, "abc123"), (102, "def456")]
    assert host_info_calls == [101, 102]
    assert host_usage_calls == [101, 102]
    assert volume_calls == [101, 102]
    assert image_calls == [101, 102]

    assert warnings == []

    stack_map = stack_df.set_index(["endpoint_id", "stack_id"])  # type: ignore[arg-type]
    assert stack_map.loc[(101, 201), "stack_name"] == "alpha-app"
    assert stack_map.loc[(101, 202), "stack_status"] == 0
    assert stack_map.loc[(102, 301), "stack_type"] == 2
    assert set(stack_df["environment_name"]) == {"Demo"}

    container_map = container_df.set_index("container_id")
    alpha_created = pd.to_datetime(1_700_100_000, unit="s", utc=True).isoformat()
    assert container_map.loc["abc123", "container_name"] == "alpha-web"
    assert container_map.loc["abc123", "ports"] == "8080->80/tcp"
    assert container_map.loc["abc123", "created_at"] == alpha_created
    assert container_map.loc["def456", "container_name"] == "beta-worker"
    assert container_map.loc["def456", "created_at"] == "2024-05-01T12:34:00+00:00"
    assert set(container_df["environment_name"]) == {"Demo"}

    endpoint_map = endpoint_df.set_index("endpoint_id")
    expected_check_in = pd.to_datetime(1_700_000_000, unit="s", utc=True).isoformat()
    assert endpoint_map.loc[101, "agent_version"] == "2.13.0"
    assert endpoint_map.loc[101, "last_check_in"] == expected_check_in
    assert endpoint_map.loc[102, "last_check_in"] == "2024-05-01T12:00:00+00:00"
    assert endpoint_map.loc[101, "tags"] == "prod, region-a"
    assert endpoint_map.loc[102, "tags"] == "staging"

    detail_map = container_details_df.set_index("container_id")
    assert detail_map.loc["abc123", "health_status"] == "healthy"
    assert detail_map.loc["abc123", "mounts"] == "/data ← /srv/data"
    assert detail_map.loc["abc123", "labels"] == "app=alpha, tier=frontend"
    assert pytest.approx(detail_map.loc["abc123", "cpu_percent"], rel=1e-6) == 200.0
    assert pytest.approx(detail_map.loc["abc123", "memory_percent"], rel=1e-6) == 25.0
    assert detail_map.loc["abc123", "last_finished_at"] == "2024-05-01T11:00:00+00:00"
    assert detail_map.loc["def456", "networks"] is None
    assert detail_map.loc["def456", "labels"] == "app=beta"
    assert pytest.approx(detail_map.loc["def456", "cpu_percent"], rel=1e-6) == 20.0
    assert pytest.approx(detail_map.loc["def456", "memory_percent"], rel=1e-6) == 12.5

    host_map = host_df.set_index("endpoint_id")
    assert host_map.loc[101, "docker_version"] == "24.0"
    assert host_map.loc[101, "containers_running"] == 7
    assert host_map.loc[101, "volumes_total"] == 5
    assert host_map.loc[102, "volumes_total"] == 2
    assert bool(host_map.loc[101, "swarm_node"]) is True
    assert bool(host_map.loc[102, "swarm_node"]) is False

    volume_map = volume_df.set_index("volume_name")
    assert volume_map.loc["alpha-data", "labels"] == "env=prod, project=alpha"
    assert volume_map.loc["beta-tmp", "labels"] is None

    image_map = image_df.set_index("image_id")
    assert image_map.loc["sha256:1", "reference"] == "alpha/web:1.0"
    assert image_map.loc["sha256:2", "reference"] == "alpha/db@sha256:aaa"
    assert bool(image_map.loc["sha256:1", "dangling"]) is False
    assert bool(image_map.loc["sha256:2", "dangling"]) is True
    assert image_map.loc["sha256:3", "size"] == 1_024

