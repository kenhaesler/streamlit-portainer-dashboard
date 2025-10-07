"""Session storage backends for authentication metadata."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
from threading import RLock
from typing import Final, Optional, Protocol, cast


SESSION_BACKEND_ENV_VAR = "DASHBOARD_SESSION_BACKEND"
SQLITE_PATH_ENV_VAR = "DASHBOARD_SESSION_SQLITE_PATH"

class _UnsetType:
    """Sentinel used to distinguish explicit ``None`` from omitted values."""

    __slots__ = ()


_UNSET: Final = _UnsetType()


@dataclass
class SessionRecord:
    """Data persisted for long-lived authenticated sessions."""

    token: str
    username: str
    authenticated_at: datetime
    last_active: datetime
    session_timeout: Optional[timedelta]
    auth_method: str

    def is_expired(
        self,
        now: datetime,
        *,
        session_timeout: Optional[timedelta] | _UnsetType = _UNSET,
    ) -> bool:
        """Return ``True`` if the record expired relative to ``now``.

        ``session_timeout`` allows callers to evaluate expiry using a
        different timeout value without mutating the record in-place.
        """

        if session_timeout is _UNSET:
            effective_timeout = self.session_timeout
        else:
            effective_timeout = cast(Optional[timedelta], session_timeout)

        if effective_timeout is None:
            return False
        return now - self.last_active >= effective_timeout


class SessionStorage(Protocol):
    """Interface implemented by all session storage backends."""

    def create(self, record: SessionRecord) -> None:
        """Persist ``record`` in the backing store."""

    def retrieve(self, token: str) -> Optional[SessionRecord]:
        """Return the session identified by ``token`` if present."""

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: Optional[timedelta],
    ) -> None:
        """Update the activity metadata for ``token``."""

    def delete(self, token: str) -> None:
        """Delete the session ``token`` if it exists."""

    def purge_expired(self, now: datetime) -> None:
        """Remove expired sessions relative to ``now``."""

    def count(self, now: datetime) -> int:
        """Return the number of non-expired sessions."""


class InMemorySessionStorage(SessionStorage):
    """In-process dictionary based session storage."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._sessions[record.token] = record

    def retrieve(self, token: str) -> Optional[SessionRecord]:
        with self._lock:
            return self._sessions.get(token)

    def touch(
        self,
        token: str,
        *,
        last_active: datetime,
        session_timeout: Optional[timedelta],
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


class SQLiteSessionStorage(SessionStorage):
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
        # Setting ``check_same_thread=False`` allows the SQLite connection to be used
        # across multiple threads. Note: each method creates a new connection via
        # ``self._connect()``, so connections are not shared between operations.
        # Thread safety is ensured by guarding all access with ``self._lock``, which
        # protects concurrent access to the database file, not connection sharing.
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
    def _seconds_from_timeout(timeout: Optional[timedelta]) -> Optional[int]:
        if timeout is None:
            return None
        return int(timeout.total_seconds())

    @staticmethod
    def _timeout_from_seconds(seconds: Optional[int]) -> Optional[timedelta]:
        if seconds is None:
            return None
        return timedelta(seconds=seconds)

    def _compute_expiry(
        self, *, last_active: datetime, session_timeout: Optional[timedelta]
    ) -> Optional[str]:
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

    def retrieve(self, token: str) -> Optional[SessionRecord]:
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
        session_timeout: Optional[timedelta],
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


def _determine_backend() -> str:
    backend = os.getenv(SESSION_BACKEND_ENV_VAR, "memory").strip().lower()
    if not backend:
        return "memory"
    return backend


def _sqlite_path() -> Path:
    raw_path = os.getenv(SQLITE_PATH_ENV_VAR, "")
    if raw_path:
        return Path(raw_path).expanduser()
    return Path(".streamlit") / "sessions.db"


def create_session_storage() -> SessionStorage:
    """Instantiate the configured session storage backend."""

    backend = _determine_backend()
    if backend == "sqlite":
        return SQLiteSessionStorage(_sqlite_path())
    return InMemorySessionStorage()
