"""Tests for the Portainer client utilities."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import portainer_client
from app.portainer_client import PortainerAPIError, PortainerClient


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


def test_create_backup_posts_to_backup_endpoint(monkeypatch):
    client = PortainerClient(base_url="https://portainer.example", api_key="token")

    captured: dict[str, object] = {}

    class DummyResponse:
        headers = {"Content-Disposition": "attachment; filename*=UTF-8''portainer.tar.gz"}
        content = b"backup-data"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_post(url, headers, json, timeout, verify):  # type: ignore[override]
        captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
                "verify": verify,
            }
        )
        return DummyResponse()

    monkeypatch.setattr(portainer_client.requests, "post", fake_post)

    payload, filename = client.create_backup(password="secret")

    assert captured["url"] == "https://portainer.example/api/backup"
    assert captured["json"] == {"password": "secret"}
    assert payload == b"backup-data"
    assert filename == "portainer.tar.gz"


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

    monkeypatch.setattr(portainer_client.requests, "post", fake_post)

    with pytest.raises(PortainerAPIError):
        client.create_backup()
