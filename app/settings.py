"""Application settings helpers for Portainer environments."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class PortainerEnvironment:
    """Configuration for a single Portainer environment."""

    name: str
    api_url: str
    api_key: str
    verify_ssl: bool = True


_FALSEY_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    """Parse a boolean value from an environment variable string."""

    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned.lower() not in _FALSEY_VALUES


def _normalise_key(name: str) -> str:
    return name.upper().replace(" ", "_")


def _build_environment(name: str, *, prefix: str | None = None) -> PortainerEnvironment:
    key_prefix = prefix or _normalise_key(name)
    api_url = os.getenv(f"PORTAINER_{key_prefix}_API_URL", "").strip()
    api_key = os.getenv(f"PORTAINER_{key_prefix}_API_KEY", "").strip()
    verify_ssl = _parse_bool(
        os.getenv(f"PORTAINER_{key_prefix}_VERIFY_SSL"),
        default=True,
    )
    if not api_url or not api_key:
        raise ValueError(
            f"Configuration for environment '{name}' is incomplete: "
            "missing API URL or API key."
        )
    return PortainerEnvironment(name=name, api_url=api_url, api_key=api_key, verify_ssl=verify_ssl)


def get_configured_environments() -> List[PortainerEnvironment]:
    """Return all configured Portainer environments from environment variables."""

    configured: List[PortainerEnvironment] = []
    raw_environments = os.getenv("PORTAINER_ENVIRONMENTS", "").strip()
    if raw_environments:
        names: Iterable[str] = (
            name.strip() for name in raw_environments.split(",") if name.strip()
        )
        for name in names:
            key_prefix = _normalise_key(name)
            configured.append(_build_environment(name, prefix=key_prefix))
        return configured

    api_url = os.getenv("PORTAINER_API_URL", "").strip()
    api_key = os.getenv("PORTAINER_API_KEY", "").strip()
    if api_url and api_key:
        default_name = os.getenv("PORTAINER_ENVIRONMENT_NAME", "Default")
        verify_ssl = _parse_bool(os.getenv("PORTAINER_VERIFY_SSL"), default=True)
        configured.append(
            PortainerEnvironment(
                name=default_name,
                api_url=api_url,
                api_key=api_key,
                verify_ssl=verify_ssl,
            )
        )
    return configured


__all__ = ["PortainerEnvironment", "get_configured_environments"]
