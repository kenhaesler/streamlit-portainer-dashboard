from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.session_storage import (
    InMemorySessionStorage,
    SQLiteSessionStorage,
    SessionRecord,
)


def _sample_record(token: str, *, last_active_delta: timedelta) -> SessionRecord:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return SessionRecord(
        token=token,
        username="user",
        authenticated_at=now - timedelta(minutes=5),
        last_active=now - last_active_delta,
        session_timeout=timedelta(minutes=30),
        auth_method="static",
    )


def test_inmemory_storage_purges_expired_sessions() -> None:
    store = InMemorySessionStorage()
    record = _sample_record("active", last_active_delta=timedelta(minutes=10))
    expired = _sample_record("expired", last_active_delta=timedelta(hours=1))

    store.create(record)
    store.create(expired)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert store.count(now) == 1
    assert store.retrieve("active") is not None
    assert store.retrieve("expired") is None


def test_session_record_expiry_override() -> None:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    record = SessionRecord(
        token="token",
        username="user",
        authenticated_at=now - timedelta(minutes=10),
        last_active=now - timedelta(minutes=5),
        session_timeout=timedelta(minutes=15),
        auth_method="static",
    )

    assert not record.is_expired(now)
    assert record.is_expired(now, session_timeout=timedelta(minutes=1))
    assert not record.is_expired(now, session_timeout=None)


def test_sqlite_storage_roundtrip(tmp_path) -> None:
    database_path = tmp_path / "sessions.db"
    store = SQLiteSessionStorage(database_path)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    record = SessionRecord(
        token="token",
        username="alice",
        authenticated_at=now - timedelta(minutes=3),
        last_active=now - timedelta(minutes=1),
        session_timeout=timedelta(minutes=30),
        auth_method="oidc",
    )

    store.create(record)

    fetched = store.retrieve("token")
    assert fetched is not None
    assert fetched.username == "alice"
    assert fetched.auth_method == "oidc"

    store.touch(
        "token",
        last_active=now,
        session_timeout=timedelta(minutes=45),
    )

    updated = store.retrieve("token")
    assert updated is not None
    assert updated.session_timeout == timedelta(minutes=45)

    store.purge_expired(now + timedelta(hours=1))
    assert store.retrieve("token") is None
