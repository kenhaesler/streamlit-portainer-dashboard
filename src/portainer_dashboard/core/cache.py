"""Persistent caching utilities for Portainer environment data."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

from portainer_dashboard.config import CacheSettings, get_settings

LOGGER = logging.getLogger(__name__)

_CACHE_FILE_SUFFIX = ".json"
_CACHE_LOCK_SUFFIX = ".lock"
_CACHE_KEY_DERIVATION_SALT = b"portainer-environment-cache"
_CACHE_KEY_DERIVATION_ROUNDS = 200_000
_CACHE_LOCK_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CacheEntry:
    """Representation of a cached Portainer payload."""

    payload: dict[str, Any]
    refreshed_at: float | None
    expires_at: float | None

    @property
    def is_expired(self) -> bool:
        """Return True when the cache entry has passed its TTL."""
        if self.expires_at is None:
            return False
        return self.expires_at <= time.time()


def _resolve_cache_config(config: CacheSettings | None = None) -> CacheSettings:
    """Return a cache configuration, defaulting to the global settings."""
    if config is not None:
        return config
    return get_settings().cache


def is_cache_enabled(config: CacheSettings | None = None) -> bool:
    """Return True when persistent caching is enabled."""
    return _resolve_cache_config(config).enabled


def cache_ttl_seconds(config: CacheSettings | None = None) -> int:
    """Return the configured cache TTL in seconds."""
    return _resolve_cache_config(config).ttl_seconds


def _cache_directory(config: CacheSettings | None = None) -> Path:
    return _resolve_cache_config(config).directory


def _cache_path(config: CacheSettings | None, key: str) -> Path:
    safe_key = f"{key}{_CACHE_FILE_SUFFIX}"
    return _cache_directory(config) / safe_key


def _cache_lock_path(path: Path) -> Path:
    return path.with_suffix(f"{_CACHE_FILE_SUFFIX}{_CACHE_LOCK_SUFFIX}")


@contextmanager
def _acquire_cache_lock(path: Path) -> Iterator[None]:
    lock_path = _cache_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path))
    acquired = False
    try:
        lock.acquire(timeout=_CACHE_LOCK_TIMEOUT_SECONDS)
        acquired = True
        yield
    except Timeout:
        LOGGER.warning("Timeout waiting for cache lock on %s", path)
        raise
    finally:
        if acquired:
            try:
                lock.release()
            except RuntimeError:
                LOGGER.debug("Cache lock already released for %s", path)


def _ensure_cache_directory(config: CacheSettings | None = None) -> Path:
    directory = _cache_directory(config)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
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
    environments: list[dict[str, Any]],
    *,
    include_stopped: bool,
    include_container_details: bool,
    include_resource_utilisation: bool,
) -> str:
    """Build a deterministic cache key for the provided environments."""
    signature: list[dict[str, Any]] = []
    sorted_envs = sorted(
        environments, key=lambda env: (env.get("name", ""), env.get("api_url", ""))
    )
    for environment in sorted_envs:
        signature.append(
            {
                "name": environment.get("name", ""),
                "api_url": environment.get("api_url", ""),
                "api_key": _hash_api_key(environment.get("api_key", "")),
                "verify_ssl": environment.get("verify_ssl", True),
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


def load_cache_entry(
    key: str,
    config: CacheSettings | None = None,
) -> CacheEntry | None:
    """Load a cached payload for key when available."""
    resolved = _resolve_cache_config(config)
    if not is_cache_enabled(resolved):
        return None
    path = _cache_path(resolved, key)
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    try:
        with _acquire_cache_lock(path):
            return _read_payload(path)
    except Timeout:
        LOGGER.warning("Skipping cache read for %s due to lock contention", path)
        return None


def store_cache_entry(
    key: str,
    payload: dict[str, Any],
    config: CacheSettings | None = None,
) -> float | None:
    """Persist payload under key respecting the configured TTL.

    Returns
    -------
    float | None
        Unix timestamp representing when the payload was refreshed.
        Returns None when caching is disabled or persistence fails.
    """
    resolved = _resolve_cache_config(config)
    if not is_cache_enabled(resolved):
        return None
    try:
        _ensure_cache_directory(resolved)
    except OSError:
        return None
    ttl = cache_ttl_seconds(resolved)
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
    path = _cache_path(resolved, key)
    try:
        with _acquire_cache_lock(path):
            path.write_text(json.dumps(data), "utf-8")
    except Timeout:
        LOGGER.warning("Unable to persist cache entry %s due to lock contention", path)
        return None
    except OSError:
        LOGGER.warning("Unable to persist cache entry %s", path)
        return None
    return refreshed_at


def clear_cache(config: CacheSettings | None = None, key: str | None = None) -> None:
    """Remove cached payloads."""
    resolved = _resolve_cache_config(config)
    if key is not None:
        path = _cache_path(resolved, key)
        try:
            path.unlink()
        except OSError:
            pass
        return

    directory = _cache_directory(resolved)
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


__all__ = [
    "CacheEntry",
    "build_cache_key",
    "cache_ttl_seconds",
    "clear_cache",
    "is_cache_enabled",
    "load_cache_entry",
    "store_cache_entry",
]
