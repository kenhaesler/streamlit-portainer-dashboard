"""Helpers for resolving TLS certificate bundle configuration."""
from __future__ import annotations

import os
from pathlib import Path

CA_BUNDLE_ENV_VAR = "DASHBOARD_CA_BUNDLE"


def resolve_ca_bundle_path(raw_path: str | None) -> str | None:
    """Return a verified path to a CA bundle if the input points at a file."""

    if not raw_path:
        return None
    try:
        candidate = Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return str(candidate) if candidate.is_file() else None


def get_ca_bundle_path() -> str | None:
    """Return the CA bundle path configured for the dashboard, if any."""

    raw_path = os.getenv(CA_BUNDLE_ENV_VAR, "").strip()
    return resolve_ca_bundle_path(raw_path)
