"""Session storage backends for authentication metadata."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Final, Protocol

import redis
from redis.exceptions import ConnectionError as RedisConnectionError

from portainer_dashboard.config import get_settings

logger = logging.getLogger(__name__)


class _UnsetType:
    """Sentinel used to distinguish explicit None from omitted values."""

    __slots__ = ()


_UNSET: Final = _UnsetType()


@dataclass
class SessionRecord:
    """Data persisted for long-lived authenticated sessions."""

    token: str
    username: str
    authenticated_at: datetime
    last_active: datetime
    session_timeout: timedelta | None
    auth_method: str

    def is_expired(
        self,
        now: datetime,
        *,
        session_timeout: timedelta | None | _UnsetType = _UNSET,
    ) -> bool:
        """Return True if the record expired relative to now.

        session_timeout allows callers to evaluate expiry using a
        different timeout value without mutating the record in-place.
        """
        if isinstance(session_timeout, _UnsetType):
            effective_timeout = self.session_timeout
        else:
            effective_timeout = session_timeout

        if effective_timeout is None:
            return False
        return now - self.last_active >= effective_timeout


class SessionStorage(Protocol):
    """Interface implemented by all session storage backends."""

    def create(self, record: SessionRecord) -> None:
        """Persist record in the backing store."""
        ...

    def retrieve(self, token: str) -> SessionRecord | None:
        """Return the session identified by token if present."""
        ...

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: timedelta | None,
    ) -> None:
        """Update the activity metadata for token."""
        ...

    def delete(self, token: str) -> None:
        """Delete the session token if it exists."""
        ...

    def purge_expired(self, now: datetime) -> None:
        """Remove expired sessions relative to now."""
        ...

    def count(self, now: datetime) -> int:
        """Return the number of non-expired sessions."""
        ...


class InMemorySessionStorage:
    """In-process dictionary based session storage."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._sessions[record.token] = record

    def retrieve(self, token: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(token)

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: timedelta | None,
    ) -> None:
        with self._lock:
            record = self._sessions.get(token)
            if record is None:
                return
            record.last_active = last_active
            record.session_timeout = session_timeout

    def delete(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def purge_expired(self, now: datetime) -> None:
        with self._lock:
            for token, record in list(self._sessions.items()):
                if record.is_expired(now):
                    self._sessions.pop(token, None)

    def count(self, now: datetime) -> int:
        with self._lock:
            self.purge_expired(now)
            return len(self._sessions)


class SQLiteSessionStorage:
    """SQLite backed session storage suitable for multi-instance deployments."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = RLock()
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._lock:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        username TEXT NOT NULL,
                        authenticated_at TEXT NOT NULL,
                        last_active TEXT NOT NULL,
                        session_timeout_seconds INTEGER,
                        auth_method TEXT NOT NULL,
                        expiry_at TEXT
                    )
                    """
                )
                connection.commit()

    @staticmethod
    def _encode_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    @staticmethod
    def _seconds_from_timeout(timeout: timedelta | None) -> int | None:
        if timeout is None:
            return None
        return int(timeout.total_seconds())

    @staticmethod
    def _timeout_from_seconds(seconds: int | None) -> timedelta | None:
        if seconds is None:
            return None
        return timedelta(seconds=seconds)

    def _compute_expiry(
        self, *, last_active: datetime, session_timeout: timedelta | None
    ) -> str | None:
        if session_timeout is None:
            return None
        expiry = last_active + session_timeout
        return self._encode_datetime(expiry)

    def create(self, record: SessionRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    token,
                    username,
                    authenticated_at,
                    last_active,
                    session_timeout_seconds,
                    auth_method,
                    expiry_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.token,
                    record.username,
                    self._encode_datetime(record.authenticated_at),
                    self._encode_datetime(record.last_active),
                    self._seconds_from_timeout(record.session_timeout),
                    record.auth_method,
                    self._compute_expiry(
                        last_active=record.last_active,
                        session_timeout=record.session_timeout,
                    ),
                ),
            )
            connection.commit()

    def retrieve(self, token: str) -> SessionRecord | None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM sessions WHERE token = ?",
                (token,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return SessionRecord(
                token=row["token"],
                username=row["username"],
                authenticated_at=self._decode_datetime(row["authenticated_at"]),
                last_active=self._decode_datetime(row["last_active"]),
                session_timeout=self._timeout_from_seconds(row["session_timeout_seconds"]),
                auth_method=row["auth_method"],
            )

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: timedelta | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET last_active = ?,
                    session_timeout_seconds = ?,
                    expiry_at = ?
                WHERE token = ?
                """,
                (
                    self._encode_datetime(last_active),
                    self._seconds_from_timeout(session_timeout),
                    self._compute_expiry(
                        last_active=last_active, session_timeout=session_timeout
                    ),
                    token,
                ),
            )
            connection.commit()

    def delete(self, token: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
            connection.commit()

    def _delete_expired_sessions(
        self, connection: sqlite3.Connection, now: datetime
    ) -> None:
        connection.execute(
            "DELETE FROM sessions WHERE expiry_at IS NOT NULL AND expiry_at <= ?",
            (self._encode_datetime(now),),
        )
        connection.commit()

    def purge_expired(self, now: datetime) -> None:
        with self._lock, self._connect() as connection:
            self._delete_expired_sessions(connection, now)

    def count(self, now: datetime) -> int:
        with self._lock, self._connect() as connection:
            self._delete_expired_sessions(connection, now)
            cursor = connection.execute("SELECT COUNT(*) FROM sessions")
            (count,) = cursor.fetchone()
            return int(count)


class RedisSessionStorage:
    """Redis-backed session storage for distributed deployments."""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "session:",
        socket_timeout: float = 5.0,
        socket_connect_timeout: float = 5.0,
        retry_on_timeout: bool = True,
        health_check_interval: int = 30,
    ) -> None:
        self._key_prefix = key_prefix
        self._client = redis.Redis.from_url(
            redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            retry_on_timeout=retry_on_timeout,
            health_check_interval=health_check_interval,
            decode_responses=True,
        )

    def _make_key(self, token: str) -> str:
        """Generate a prefixed Redis key for the session token."""
        return f"{self._key_prefix}{token}"

    @staticmethod
    def _serialize_record(record: SessionRecord) -> str:
        """Serialize a SessionRecord to JSON for Redis storage."""
        data: dict[str, Any] = {
            "token": record.token,
            "username": record.username,
            "authenticated_at": record.authenticated_at.isoformat(),
            "last_active": record.last_active.isoformat(),
            "session_timeout_seconds": (
                int(record.session_timeout.total_seconds())
                if record.session_timeout is not None
                else None
            ),
            "auth_method": record.auth_method,
        }
        return json.dumps(data)

    @staticmethod
    def _deserialize_record(data: str) -> SessionRecord:
        """Deserialize JSON data to a SessionRecord."""
        parsed = json.loads(data)
        session_timeout = None
        if parsed["session_timeout_seconds"] is not None:
            session_timeout = timedelta(seconds=parsed["session_timeout_seconds"])
        return SessionRecord(
            token=parsed["token"],
            username=parsed["username"],
            authenticated_at=datetime.fromisoformat(parsed["authenticated_at"]),
            last_active=datetime.fromisoformat(parsed["last_active"]),
            session_timeout=session_timeout,
            auth_method=parsed["auth_method"],
        )

    def create(self, record: SessionRecord) -> None:
        """Persist a session record in Redis."""
        key = self._make_key(record.token)
        value = self._serialize_record(record)
        try:
            if record.session_timeout is not None:
                ttl_seconds = int(record.session_timeout.total_seconds())
                self._client.setex(key, ttl_seconds, value)
            else:
                self._client.set(key, value)
        except RedisConnectionError:
            logger.warning("Redis connection error during session create")

    def retrieve(self, token: str) -> SessionRecord | None:
        """Retrieve a session record from Redis."""
        key = self._make_key(token)
        try:
            data = self._client.get(key)
            if data is None:
                return None
            return self._deserialize_record(data)
        except RedisConnectionError:
            logger.warning("Redis connection error during session retrieve")
            return None

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: timedelta | None,
    ) -> None:
        """Update session activity timestamp and refresh TTL."""
        key = self._make_key(token)
        try:
            data = self._client.get(key)
            if data is None:
                return
            record = self._deserialize_record(data)
            record.last_active = last_active
            record.session_timeout = session_timeout
            value = self._serialize_record(record)
            if session_timeout is not None:
                ttl_seconds = int(session_timeout.total_seconds())
                self._client.setex(key, ttl_seconds, value)
            else:
                self._client.set(key, value)
        except RedisConnectionError:
            logger.warning("Redis connection error during session touch")

    def delete(self, token: str) -> None:
        """Delete a session from Redis."""
        key = self._make_key(token)
        try:
            self._client.delete(key)
        except RedisConnectionError:
            logger.warning("Redis connection error during session delete")

    def purge_expired(self, now: datetime) -> None:
        """No-op: Redis TTL handles expiration automatically."""
        pass

    def count(self, now: datetime) -> int:
        """Count active sessions using SCAN with key prefix."""
        count = 0
        try:
            cursor = 0
            pattern = f"{self._key_prefix}*"
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=100)
                count += len(keys)
                if cursor == 0:
                    break
        except RedisConnectionError:
            logger.warning("Redis connection error during session count")
            return 0
        return count

    def close(self) -> None:
        """Close the Redis connection pool."""
        self._client.close()


def create_session_storage() -> SessionStorage:
    """Instantiate the configured session storage backend."""
    settings = get_settings()
    if settings.session.backend == "sqlite":
        return SQLiteSessionStorage(settings.session.sqlite_path)
    if settings.session.backend == "redis":
        return RedisSessionStorage(
            redis_url=settings.session.redis_url,
            key_prefix=settings.session.redis_key_prefix,
            socket_timeout=settings.session.redis_socket_timeout,
            socket_connect_timeout=settings.session.redis_socket_connect_timeout,
            retry_on_timeout=settings.session.redis_retry_on_timeout,
            health_check_interval=settings.session.redis_health_check_interval,
        )
    return InMemorySessionStorage()


__all__ = [
    "InMemorySessionStorage",
    "RedisSessionStorage",
    "SessionRecord",
    "SessionStorage",
    "SQLiteSessionStorage",
    "create_session_storage",
]
