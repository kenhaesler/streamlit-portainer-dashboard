"""Helpers for creating and storing Portainer backups."""

from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path
from typing import Mapping, Optional

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.portainer_client import PortainerClient  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from portainer_client import PortainerClient  # type: ignore[no-redef]

__all__ = ["backup_directory", "create_environment_backup"]

_BACKUP_DIR_ENV_VAR = "PORTAINER_BACKUP_DIR"


def backup_directory() -> Path:
    """Return the directory used to persist Portainer backups."""

    override = os.getenv(_BACKUP_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / ".streamlit" / "backups"


def _ensure_backup_directory() -> Path:
    directory = backup_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sanitise_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip("-_") or "portainer"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = "".join(path.suffixes)
    if suffix:
        stem = path.name[: -len(suffix)]
    else:
        stem = path.name
    counter = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{stem.rstrip('_')}_{counter}{suffix}")
        counter += 1
    return candidate


def create_environment_backup(
    environment: Mapping[str, object], *, password: Optional[str] = None
) -> Path:
    """Create a backup for ``environment`` and store it on disk."""

    api_url = str(environment.get("api_url", "")).strip()
    api_key = str(environment.get("api_key", "")).strip()
    if not api_url or not api_key:
        raise ValueError("Environment is missing an API URL or API key")
    verify_ssl = bool(environment.get("verify_ssl", True))
    client = PortainerClient(base_url=api_url, api_key=api_key, verify_ssl=verify_ssl)
    payload, filename = client.create_backup(password=password)
    directory = _ensure_backup_directory()
    env_name = str(environment.get("name", "portainer")) or "portainer"
    prefix = _sanitise_component(env_name)
    timestamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if filename:
        base_name = Path(filename).name
    else:
        base_name = f"portainer-backup-{timestamp}.tar.gz"
    backup_name = f"{prefix}_{base_name}" if prefix else base_name
    destination = directory / backup_name
    destination = _unique_path(destination)
    destination.write_bytes(payload)
    return destination
