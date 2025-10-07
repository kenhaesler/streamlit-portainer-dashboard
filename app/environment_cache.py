"""Persistent caching utilities for Portainer environment data."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

try:  # pragma: no cover - import shim for Streamlit runtime
    from .file_locking import FileLock, Timeout  # type: ignore[import-not-found]
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from file_locking import FileLock, Timeout  # type: ignore[no-redef]

from .config import (
    CACHE_DIR_ENV_VAR,
    CACHE_ENABLED_ENV_VAR,
    CACHE_TTL_ENV_VAR,
    CacheConfig,
    get_config,
    reload_config,
)

try:  # pragma: no cover - import shim for Streamlit runtime
    from .settings import PortainerEnvironment  # type: ignore[import-not-found]
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from settings import PortainerEnvironment  # type: ignore[no-redef]

LOGGER = logging.getLogger(__name__)
_CACHE_FILE_SUFFIX = ".json"
_CACHE_LOCK_SUFFIX = ".lock"
_CACHE_KEY_DERIVATION_SALT = b"portainer-environment-cache"
_CACHE_KEY_DERIVATION_ROUNDS = 200_000
_CACHE_LOCK_TIMEOUT_SECONDS = 5.0
_CACHE_ENV_SIGNATURE: tuple[str | None, str | None, str | None] | None = None


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


def _current_cache_env_signature() -> tuple[str | None, str | None, str | None]:
    return (
        os.getenv(CACHE_ENABLED_ENV_VAR),
        os.getenv(CACHE_TTL_ENV_VAR),
        os.getenv(CACHE_DIR_ENV_VAR),
    )


def _resolve_cache_config(config: CacheConfig | None = None) -> CacheConfig:
    """Return a cache configuration, defaulting to the global settings."""

    if config is not None:
        return config

    global _CACHE_ENV_SIGNATURE
    signature = _current_cache_env_signature()
    if signature != _CACHE_ENV_SIGNATURE:
        _CACHE_ENV_SIGNATURE = signature
        return reload_config().cache
    return get_config().cache


def is_cache_enabled(config: CacheConfig | None = None) -> bool:
    """Return ``True`` when persistent caching is enabled."""

    return _resolve_cache_config(config).enabled


def cache_ttl_seconds(config: CacheConfig | None = None) -> int:
    """Return the configured cache TTL in seconds."""

    return _resolve_cache_config(config).ttl_seconds


def _cache_directory(config: CacheConfig | None = None) -> Path:
    return _resolve_cache_config(config).directory


def _cache_path(config: CacheConfig | None, key: str) -> Path:
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


def _ensure_cache_directory(config: CacheConfig | None = None) -> Path:
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


def _load_cache_entry(config: CacheConfig, key: str) -> CacheEntry | None:
    if not is_cache_enabled(config):
        return None
    path = _cache_path(config, key)
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


def load_cache_entry(*args: Any, **kwargs: Any) -> CacheEntry | None:
    """Load a cached payload for ``key`` when available.

    This helper accepts both the legacy ``load_cache_entry(key)`` signature and
    the newer ``load_cache_entry(config, key)`` form. The optional ``config``
    keyword argument takes precedence when provided.
    """

    config: CacheConfig | None
    key: str

    if "config" in kwargs:
        config = kwargs.pop("config")
        if kwargs:
            raise TypeError("Unexpected keyword arguments: " + ", ".join(kwargs))
        if len(args) != 1:
            raise TypeError("load_cache_entry() missing required key argument")
        key = args[0]
    elif len(args) == 2:
        if not (isinstance(args[0], CacheConfig) or args[0] is None):
            raise TypeError("First argument must be a CacheConfig or None")
        if not isinstance(args[1], str):
            raise TypeError("Second argument must be a string key")
        config, key = args
    elif len(args) == 1:
        (key,) = args
        config = None
    else:
        raise TypeError("load_cache_entry() accepts either (key) or (config, key)")

    if not isinstance(key, str):
        raise TypeError("load_cache_entry() requires key to be a string")

    resolved = _resolve_cache_config(config)
    return _load_cache_entry(resolved, key)


def store_cache_entry(*args: Any, **kwargs: Any) -> float | None:
    """Persist ``payload`` under ``key`` respecting the configured TTL.

    Returns
    -------
    float | None
        Unix timestamp representing when the payload was refreshed. Returns
        ``None`` when caching is disabled or persistence fails.
    """

    if "config" in kwargs:
        config = kwargs.pop("config")
        if kwargs:
            raise TypeError("Unexpected keyword arguments: " + ", ".join(kwargs))
        if len(args) != 2:
            raise TypeError("store_cache_entry() missing required key/payload arguments")
        key, payload = args
    elif len(args) == 3:
        config_candidate, key_candidate, payload_candidate = args
        if not (isinstance(key_candidate, str) and isinstance(payload_candidate, dict)):
            raise TypeError("store_cache_entry() requires key to be a string and payload to be a dictionary")
        config = config_candidate
        key = key_candidate
        payload = payload_candidate
    elif len(args) == 2:
        config = None
        key, payload = args
    else:
        raise TypeError(
            "store_cache_entry() accepts either (key, payload) or (config, key, payload)"
        )

    if not isinstance(key, str):
        raise TypeError("store_cache_entry() requires key to be a string")
    if not isinstance(payload, dict):
        raise TypeError("store_cache_entry() requires payload to be a dictionary")

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
