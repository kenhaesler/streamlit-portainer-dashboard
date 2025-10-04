"""Configuration helpers for managing saved Portainer environments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "portainer_environments.json"


def _ensure_config_dir() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _coerce_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def load_environments() -> list[dict[str, Any]]:
    """Load saved Portainer environments from disk."""

    if not CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    environments: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        environments.append(
            {
                "name": str(item.get("name", "")).strip(),
                "api_url": str(item.get("api_url", "")).strip(),
                "api_key": str(item.get("api_key", "")).strip(),
                "verify_ssl": _coerce_bool(item.get("verify_ssl"), default=True),
            }
        )
    return environments


def save_environments(environments: Iterable[dict[str, Any]]) -> None:
    """Persist the provided environments to disk."""

    serialisable: list[dict[str, Any]] = []
    for env in environments:
        if not isinstance(env, dict):
            continue
        serialisable.append(
            {
                "name": str(env.get("name", "")).strip(),
                "api_url": str(env.get("api_url", "")).strip(),
                "api_key": str(env.get("api_key", "")).strip(),
                "verify_ssl": _coerce_bool(env.get("verify_ssl"), default=True),
            }
        )
    _ensure_config_dir()
    CONFIG_PATH.write_text(json.dumps(serialisable, indent=2), "utf-8")
