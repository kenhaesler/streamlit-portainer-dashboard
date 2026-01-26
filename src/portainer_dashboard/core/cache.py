"""Persistent caching utilities for Portainer environment data.

Provides a two-tier caching strategy:
1. In-memory LRU cache for hot data (fast access, no I/O)
2. File-based cache for persistence across restarts
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
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

# In-memory cache settings
_MEMORY_CACHE_MAX_SIZE = 100
_MEMORY_CACHE_TTL_SECONDS = 60  # Short TTL for memory cache


class MemoryCache:
    """Thread-safe in-memory LRU cache with TTL support.

    Provides fast access for frequently requested data without file I/O.
    """

    def __init__(self, max_size: int = _MEMORY_CACHE_MAX_SIZE, ttl: int = _MEMORY_CACHE_TTL_SECONDS) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.RLock()
        self._access_order: list[str] = []  # Track access order for LRU eviction

    def get(self, key: str) -> Any | None:
        """Get value from cache if present and not expired."""
        with self._lock:
            if key not in self._cache:
                return None

            value, expires_at = self._cache[key]
            if time.time() > expires_at:
                # Expired - remove and return None
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                return None

            # Update access order (move to end for LRU)
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store value in cache with TTL."""
        with self._lock:
            # Evict oldest entries if at capacity
            while len(self._cache) >= self._max_size and self._access_order:
                oldest_key = self._access_order.pop(0)
                self._cache.pop(oldest_key, None)

            expires_at = time.time() + (ttl if ttl is not None else self._ttl)
            self._cache[key] = (value, expires_at)

            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

    def delete(self, key: str) -> None:
        """Remove key from cache."""
        with self._lock:
            self._cache.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()


# Global in-memory cache instance
_memory_cache = MemoryCache()


def get_memory_cache() -> MemoryCache:
    """Get the global memory cache instance."""
    return _memory_cache


@lru_cache(maxsize=32)
def _hash_api_key_cached(value: str) -> str:
    """Return a deterministic hash for an API key using PBKDF2 (cached).

    Uses lru_cache to avoid recomputing the expensive PBKDF2 hash
    (200,000 iterations) for the same API key.
    """
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        _CACHE_KEY_DERIVATION_SALT,
        _CACHE_KEY_DERIVATION_ROUNDS,
    )
    return derived.hex()


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
    """Return a deterministic hash for an API key using PBKDF2.

    Uses internal caching to avoid recomputing the expensive hash.
    """
    return _hash_api_key_cached(value)


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
    """Load a cached payload for key when available.

    Uses two-tier caching:
    1. First checks in-memory cache (fast, no I/O)
    2. Falls back to file cache if not in memory
    """
    resolved = _resolve_cache_config(config)
    if not is_cache_enabled(resolved):
        return None

    # Check memory cache first (fast path)
    memory_key = f"cache:{key}"
    memory_entry = _memory_cache.get(memory_key)
    if memory_entry is not None:
        LOGGER.debug("Memory cache hit for %s", key)
        return memory_entry

    # Fall back to file cache
    path = _cache_path(resolved, key)
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    try:
        with _acquire_cache_lock(path):
            entry = _read_payload(path)
            if entry is not None and not entry.is_expired:
                # Store in memory cache for subsequent fast access
                _memory_cache.set(memory_key, entry)
            return entry
    except Timeout:
        LOGGER.warning("Skipping cache read for %s due to lock contention", path)
        return None


def store_cache_entry(
    key: str,
    payload: dict[str, Any],
    config: CacheSettings | None = None,
) -> float | None:
    """Persist payload under key respecting the configured TTL.

    Updates both memory cache (for fast access) and file cache (for persistence).

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

    # Create cache entry for memory cache
    entry = CacheEntry(payload=payload, refreshed_at=refreshed_at, expires_at=expires_at)

    # Store in memory cache first (fast, always succeeds)
    memory_key = f"cache:{key}"
    memory_ttl = min(_MEMORY_CACHE_TTL_SECONDS, ttl) if ttl > 0 else _MEMORY_CACHE_TTL_SECONDS
    _memory_cache.set(memory_key, entry, ttl=memory_ttl)

    # Persist to file cache
    path = _cache_path(resolved, key)
    try:
        with _acquire_cache_lock(path):
            path.write_text(json.dumps(data), "utf-8")
    except Timeout:
        LOGGER.warning("Unable to persist cache entry %s due to lock contention", path)
        # Memory cache still has the data, so partial success
        return refreshed_at
    except OSError:
        LOGGER.warning("Unable to persist cache entry %s", path)
        return refreshed_at  # Memory cache still works

    return refreshed_at


def clear_cache(config: CacheSettings | None = None, key: str | None = None) -> None:
    """Remove cached payloads from both memory and file cache."""
    resolved = _resolve_cache_config(config)

    if key is not None:
        # Clear specific key from memory cache
        memory_key = f"cache:{key}"
        _memory_cache.delete(memory_key)

        # Clear from file cache
        path = _cache_path(resolved, key)
        try:
            path.unlink()
        except OSError:
            pass
        return

    # Clear all - memory cache
    _memory_cache.clear()

    # Clear all - file cache
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
    "MemoryCache",
    "build_cache_key",
    "cache_ttl_seconds",
    "clear_cache",
    "get_memory_cache",
    "is_cache_enabled",
    "load_cache_entry",
    "store_cache_entry",
]
