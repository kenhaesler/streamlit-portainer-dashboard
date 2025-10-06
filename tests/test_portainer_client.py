"""Tests for the Portainer client utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.portainer_client import PortainerClient


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
