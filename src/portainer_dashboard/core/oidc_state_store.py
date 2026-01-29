"""OIDC state store with pluggable backends matching the session storage pattern."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)


class OIDCStateStore(Protocol):
    """Protocol for OIDC state storage backends."""

    def store(self, state: str, data: dict[str, Any], ttl_seconds: int = 600) -> None:
        """Store state data with a TTL."""
        ...

    def retrieve_and_delete(self, state: str) -> dict[str, Any] | None:
        """Retrieve and atomically delete state data."""
        ...

    def purge_expired(self) -> None:
        """Remove expired state entries."""
        ...


class InMemoryOIDCStateStore:
    """In-memory OIDC state store (suitable for single-worker deployments)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[dict[str, Any], float]] = {}
        self._lock = threading.Lock()

    def store(self, state: str, data: dict[str, Any], ttl_seconds: int = 600) -> None:
        with self._lock:
            expires_at = time.time() + ttl_seconds
            self._store[state] = (data, expires_at)

    def retrieve_and_delete(self, state: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._store.pop(state, None)
            if entry is None:
                return None
            data, expires_at = entry
            if time.time() > expires_at:
                return None
            return data

    def purge_expired(self) -> None:
        with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


class SQLiteOIDCStateStore:
    """SQLite-backed OIDC state store (persistent across restarts)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS oidc_state (
                        state TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        expires_at REAL NOT NULL
                    )"""
                )
                conn.commit()
            finally:
                conn.close()

    def store(self, state: str, data: dict[str, Any], ttl_seconds: int = 600) -> None:
        expires_at = time.time() + ttl_seconds
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO oidc_state (state, data, expires_at) VALUES (?, ?, ?)",
                    (state, json.dumps(data, default=str), expires_at),
                )
                conn.commit()
            finally:
                conn.close()

    def retrieve_and_delete(self, state: str) -> dict[str, Any] | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT data, expires_at FROM oidc_state WHERE state = ?",
                    (state,),
                ).fetchone()
                if row is None:
                    return None
                conn.execute("DELETE FROM oidc_state WHERE state = ?", (state,))
                conn.commit()
                data_str, expires_at = row
                if time.time() > expires_at:
                    return None
                return json.loads(data_str)
            finally:
                conn.close()

    def purge_expired(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "DELETE FROM oidc_state WHERE expires_at < ?", (time.time(),)
                )
                conn.commit()
            finally:
                conn.close()


class RedisOIDCStateStore:
    """Redis-backed OIDC state store (distributed, native TTL)."""

    def __init__(self, redis_url: str, key_prefix: str = "oidc_state:") -> None:
        import redis as redis_lib

        self._client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, state: str) -> str:
        return f"{self._prefix}{state}"

    def store(self, state: str, data: dict[str, Any], ttl_seconds: int = 600) -> None:
        self._client.setex(
            self._key(state),
            ttl_seconds,
            json.dumps(data, default=str),
        )

    def retrieve_and_delete(self, state: str) -> dict[str, Any] | None:
        key = self._key(state)
        # Use pipeline for atomicity
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = pipe.execute()
        raw = results[0]
        if raw is None:
            return None
        return json.loads(raw)

    def purge_expired(self) -> None:
        # Redis handles TTL natively, nothing to do
        pass


def create_oidc_state_store() -> OIDCStateStore:
    """Create an OIDC state store matching the configured session backend."""
    from portainer_dashboard.config import get_settings

    settings = get_settings()
    backend = settings.session.backend

    if backend == "redis":
        LOGGER.info("Using Redis OIDC state store")
        return RedisOIDCStateStore(
            redis_url=settings.session.redis_url,
            key_prefix=f"{settings.session.redis_key_prefix}oidc_state:",
        )
    elif backend == "sqlite":
        db_path = str(settings.session.sqlite_path.parent / "oidc_state.db")
        LOGGER.info("Using SQLite OIDC state store: %s", db_path)
        return SQLiteOIDCStateStore(db_path=db_path)
    else:
        LOGGER.info("Using in-memory OIDC state store")
        return InMemoryOIDCStateStore()


_oidc_state_store: OIDCStateStore | None = None


def get_oidc_state_store() -> OIDCStateStore:
    """Get or create the global OIDC state store."""
    global _oidc_state_store
    if _oidc_state_store is None:
        _oidc_state_store = create_oidc_state_store()
    return _oidc_state_store


def reset_oidc_state_store() -> None:
    """Reset the store (for testing)."""
    global _oidc_state_store
    _oidc_state_store = None


__all__ = [
    "InMemoryOIDCStateStore",
    "OIDCStateStore",
    "RedisOIDCStateStore",
    "SQLiteOIDCStateStore",
    "create_oidc_state_store",
    "get_oidc_state_store",
    "reset_oidc_state_store",
]
