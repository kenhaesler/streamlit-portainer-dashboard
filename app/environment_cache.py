"""Persistent caching utilities for Portainer environment data."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import CacheConfig

try:  # pragma: no cover - import shim for Streamlit runtime
    from .settings import PortainerEnvironment  # type: ignore[import-not-found]
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from settings import PortainerEnvironment  # type: ignore[no-redef]

LOGGER = logging.getLogger(__name__)
_CACHE_FILE_SUFFIX = ".json"
_CACHE_KEY_DERIVATION_SALT = b"portainer-environment-cache"
_CACHE_KEY_DERIVATION_ROUNDS = 200_000


__all__ = [
    "CacheEntry",
    "build_cache_key",
    "cache_ttl_seconds",
    "clear_cache",
    "is_cache_enabled",
    "load_cache_entry",
    "store_cache_entry",
]


@dataclass(frozen=True)
class CacheEntry:
    """Representation of a cached Portainer payload."""

    payload: dict[str, Any]
    refreshed_at: float | None
    expires_at: float | None

    @property
    def is_expired(self) -> bool:
        """Return ``True`` when the cache entry has passed its TTL."""

        if self.expires_at is None:
            return False
        return self.expires_at <= time.time()
def is_cache_enabled(config: CacheConfig) -> bool:
    """Return ``True`` when persistent caching is enabled."""

    return config.enabled


def cache_ttl_seconds(config: CacheConfig) -> int:
    """Return the configured cache TTL in seconds."""

    return config.ttl_seconds


def _cache_directory(config: CacheConfig) -> Path:
    return config.directory


def _cache_path(config: CacheConfig, key: str) -> Path:
    safe_key = f"{key}{_CACHE_FILE_SUFFIX}"
    return _cache_directory(config) / safe_key


def _ensure_cache_directory(config: CacheConfig) -> Path:
    directory = _cache_directory(config)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        LOGGER.warning("Unable to create cache directory %s: %s", directory, exc)
        raise
    return directory


def _hash_api_key(value: str) -> str:
    """Return a deterministic hash for an API key using PBKDF2."""

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        _CACHE_KEY_DERIVATION_SALT,
        _CACHE_KEY_DERIVATION_ROUNDS,
    )
    return derived.hex()


def build_cache_key(
    environments: Iterable[PortainerEnvironment],
    *,
    include_stopped: bool,
    include_container_details: bool,
    include_resource_utilisation: bool,
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
        "include_container_details": include_container_details,
        "include_resource_utilisation": include_resource_utilisation,
        "environments": signature,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_payload(path: Path) -> CacheEntry | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    payload = data.get("payload") if "payload" in data else None
    if not isinstance(payload, dict):
        return None
    expires_at = data.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        expires_at = None
    refreshed_at = data.get("refreshed_at")
    if not isinstance(refreshed_at, (int, float)):
        refreshed_at = None
    return CacheEntry(payload=payload, refreshed_at=refreshed_at, expires_at=expires_at)


def load_cache_entry(config: CacheConfig, key: str) -> CacheEntry | None:
    """Load a cached payload for ``key`` when available."""

    if not is_cache_enabled(config):
        return None
    path = _cache_path(config, key)
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    return _read_payload(path)


def store_cache_entry(
    config: CacheConfig, key: str, payload: dict[str, Any]
) -> float | None:
    """Persist ``payload`` under ``key`` respecting the configured TTL.

    Returns
    -------
    float | None
        Unix timestamp representing when the payload was refreshed. Returns
        ``None`` when caching is disabled or persistence fails.
    """

    if not is_cache_enabled(config):
        return None
    try:
        _ensure_cache_directory(config)
    except OSError:
        return None
    ttl = cache_ttl_seconds(config)
    expires_at: float | None
    if ttl <= 0:
        expires_at = None
    else:
        expires_at = time.time() + ttl
    refreshed_at = time.time()
    data = {
        "expires_at": expires_at,
        "refreshed_at": refreshed_at,
        "payload": payload,
    }
    path = _cache_path(config, key)
    try:
        path.write_text(json.dumps(data), "utf-8")
    except OSError:
        LOGGER.warning("Unable to persist cache entry %s", path)
        return None
    return refreshed_at


def clear_cache(config: CacheConfig, key: str | None = None) -> None:
    """Remove cached payloads."""

    if key is not None:
        path = _cache_path(config, key)
        try:
            path.unlink()
        except OSError:
            pass
        return

    directory = _cache_directory(config)
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
