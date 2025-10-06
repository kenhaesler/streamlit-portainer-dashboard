"""Persistent caching utilities for Portainer environment data."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable

try:  # pragma: no cover - import shim for Streamlit runtime
    from .settings import PortainerEnvironment  # type: ignore[import-not-found]
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from settings import PortainerEnvironment  # type: ignore[no-redef]

LOGGER = logging.getLogger(__name__)

_CACHE_ENABLED_ENV_VAR = "PORTAINER_CACHE_ENABLED"
_CACHE_TTL_ENV_VAR = "PORTAINER_CACHE_TTL_SECONDS"
_CACHE_DIR_ENV_VAR = "PORTAINER_CACHE_DIR"
_DEFAULT_CACHE_TTL_SECONDS = 900
_FALSEY_VALUES = {"0", "false", "no", "off"}
_CACHE_FILE_SUFFIX = ".json"


__all__ = [
    "build_cache_key",
    "cache_ttl_seconds",
    "clear_cache",
    "is_cache_enabled",
    "load_cache_entry",
    "store_cache_entry",
]


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned.lower() not in _FALSEY_VALUES


def is_cache_enabled() -> bool:
    """Return ``True`` when persistent caching is enabled."""

    return _parse_bool(os.getenv(_CACHE_ENABLED_ENV_VAR), default=True)


def cache_ttl_seconds() -> int:
    """Return the configured cache TTL in seconds."""

    raw_value = os.getenv(_CACHE_TTL_ENV_VAR)
    if raw_value is None or not raw_value.strip():
        return _DEFAULT_CACHE_TTL_SECONDS
    try:
        ttl = int(raw_value)
    except ValueError:
        LOGGER.warning(
            "Invalid value for %s: %s. Falling back to default TTL (%s seconds).",
            _CACHE_TTL_ENV_VAR,
            raw_value,
            _DEFAULT_CACHE_TTL_SECONDS,
        )
        return _DEFAULT_CACHE_TTL_SECONDS
    return ttl


def _cache_directory() -> Path:
    override = os.getenv(_CACHE_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / ".streamlit" / "cache"


def _cache_path(key: str) -> Path:
    safe_key = f"{key}{_CACHE_FILE_SUFFIX}"
    return _cache_directory() / safe_key


def _ensure_cache_directory() -> Path:
    directory = _cache_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        LOGGER.warning("Unable to create cache directory %s: %s", directory, exc)
        raise
    return directory


def _hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_cache_key(
    environments: Iterable[PortainerEnvironment], *, include_stopped: bool
) -> str:
    """Build a deterministic cache key for the provided environments."""

    signature: list[dict[str, Any]] = []
    for environment in sorted(
        environments, key=lambda env: (env.name, env.api_url, env.verify_ssl)
    ):
        signature.append(
            {
                "name": environment.name,
                "api_url": environment.api_url,
                "api_key": _hash_api_key(environment.api_key),
                "verify_ssl": environment.verify_ssl,
            }
        )
    payload = {
        "include_stopped": include_stopped,
        "environments": signature,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_payload(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    expires_at = data.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at <= time.time():
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return data.get("payload") if "payload" in data else None


def load_cache_entry(key: str) -> dict[str, Any] | None:
    """Load a cached payload for ``key`` when available."""

    if not is_cache_enabled():
        return None
    path = _cache_path(key)
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    payload = _read_payload(path)
    if payload is None:
        return None
    return payload


def store_cache_entry(key: str, payload: dict[str, Any]) -> None:
    """Persist ``payload`` under ``key`` respecting the configured TTL."""

    if not is_cache_enabled():
        return
    try:
        _ensure_cache_directory()
    except OSError:
        return
    ttl = cache_ttl_seconds()
    expires_at: float | None
    if ttl <= 0:
        expires_at = None
    else:
        expires_at = time.time() + ttl
    data = {
        "expires_at": expires_at,
        "payload": payload,
    }
    path = _cache_path(key)
    try:
        path.write_text(json.dumps(data), "utf-8")
    except OSError:
        LOGGER.warning("Unable to persist cache entry %s", path)


def clear_cache(key: str | None = None) -> None:
    """Remove cached payloads."""

    if key is not None:
        path = _cache_path(key)
        try:
            path.unlink()
        except OSError:
            pass
        return

    directory = _cache_directory()
    try:
        if not directory.exists():
            return
    except OSError:
        return
    for entry in directory.glob(f"*{_CACHE_FILE_SUFFIX}"):
        try:
            entry.unlink()
        except OSError:
            continue
