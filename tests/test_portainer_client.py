"""Tests for the Portainer client utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.portainer_client import PortainerClient, normalise_endpoint_stacks


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


def test_normalise_endpoint_stacks_preserves_zero_status():
    """Agent status should keep zero values rather than dropping them."""

    endpoints = [{"Id": 1, "Name": "edge-one", "Status": 0}]
    result = normalise_endpoint_stacks(endpoints, {1: []})

    assert result.loc[0, "endpoint_status"] == 0


def test_normalise_endpoint_stacks_uses_edge_agent_status():
    """Edge-specific status fields should be used when present."""

    endpoints = [
        {
            "Id": 2,
            "Name": "edge-two",
            "Status": None,
            "EdgeAgentStatus": 2,
        }
    ]
    result = normalise_endpoint_stacks(endpoints, {2: []})

    assert result.loc[0, "endpoint_status"] == 2
