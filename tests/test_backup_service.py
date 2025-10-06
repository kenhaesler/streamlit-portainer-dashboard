"""Tests for the Portainer backup service helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import backup as backup_service


def test_create_environment_backup_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))

    environment = {
        "name": "Production Cluster",
        "api_url": "https://portainer.example/api",
        "api_key": "token",
        "verify_ssl": False,
    }

    class DummyClient:
        def __init__(self, *, base_url, api_key, verify_ssl):
            self.base_url = base_url
            self.api_key = api_key
            self.verify_ssl = verify_ssl

        def create_backup(self, *, password=None):
            assert password == "s3cret"
            return b"archive-bytes", "portainer-backup.tar.gz"

    monkeypatch.setattr(backup_service, "PortainerClient", DummyClient)

    backup_path = backup_service.create_environment_backup(
        environment, password="s3cret"
    )

    assert backup_path.parent == tmp_path
    assert backup_path.read_bytes() == b"archive-bytes"
    assert backup_path.name.startswith("Production-Cluster_")


def test_create_environment_backup_requires_credentials():
    with pytest.raises(ValueError):
        backup_service.create_environment_backup({"name": "Broken"})


def test_create_environment_backup_generates_unique_names(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))

    environment = {
        "name": "Edge",
        "api_url": "https://portainer.example/api",
        "api_key": "token",
    }

    class DummyClient:
        call_count = 0

        def __init__(self, *, base_url, api_key, verify_ssl=True):
            self.base_url = base_url
            self.api_key = api_key
            self.verify_ssl = verify_ssl

        def create_backup(self, *, password=None):
            DummyClient.call_count += 1
            return b"payload", "portainer-backup.tar.gz"

    monkeypatch.setattr(backup_service, "PortainerClient", DummyClient)

    first = backup_service.create_environment_backup(environment)
    second = backup_service.create_environment_backup(environment)

    assert first != second
    assert first.exists() and second.exists()
    assert second.name != first.name
