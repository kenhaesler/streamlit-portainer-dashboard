"""Tests for session storage module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest

from portainer_dashboard.core.session import (
    InMemorySessionStorage,
    SessionRecord,
    SQLiteSessionStorage,
)


@pytest.fixture
def sample_record() -> SessionRecord:
    """Create a sample session record."""
    now = datetime.now(timezone.utc)
    return SessionRecord(
        token="test-token-123",
        username="testuser",
        authenticated_at=now,
        last_active=now,
        session_timeout=timedelta(hours=1),
        auth_method="static",
    )


class TestSessionRecord:
    """Tests for SessionRecord class."""

    def test_is_expired_no_timeout(self) -> None:
        """Test that session without timeout never expires."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="test",
            username="user",
            authenticated_at=now,
            last_active=now - timedelta(days=30),
            session_timeout=None,
            auth_method="static",
        )
        assert record.is_expired(now) is False

    def test_is_expired_within_timeout(self) -> None:
        """Test that session within timeout is not expired."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="test",
            username="user",
            authenticated_at=now,
            last_active=now - timedelta(minutes=30),
            session_timeout=timedelta(hours=1),
            auth_method="static",
        )
        assert record.is_expired(now) is False

    def test_is_expired_past_timeout(self) -> None:
        """Test that session past timeout is expired."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="test",
            username="user",
            authenticated_at=now,
            last_active=now - timedelta(hours=2),
            session_timeout=timedelta(hours=1),
            auth_method="static",
        )
        assert record.is_expired(now) is True


class TestInMemorySessionStorage:
    """Tests for InMemorySessionStorage."""

    def test_create_and_retrieve(self, sample_record: SessionRecord) -> None:
        """Test creating and retrieving a session."""
        storage = InMemorySessionStorage()
        storage.create(sample_record)

        retrieved = storage.retrieve(sample_record.token)
        assert retrieved is not None
        assert retrieved.token == sample_record.token
        assert retrieved.username == sample_record.username

    def test_retrieve_nonexistent(self) -> None:
        """Test retrieving a nonexistent session."""
        storage = InMemorySessionStorage()
        assert storage.retrieve("nonexistent") is None

    def test_touch(self, sample_record: SessionRecord) -> None:
        """Test updating session activity."""
        storage = InMemorySessionStorage()
        storage.create(sample_record)

        new_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        storage.touch(
            sample_record.token,
            last_active=new_time,
            session_timeout=timedelta(hours=2),
        )

        retrieved = storage.retrieve(sample_record.token)
        assert retrieved is not None
        assert retrieved.last_active == new_time
        assert retrieved.session_timeout == timedelta(hours=2)

    def test_delete(self, sample_record: SessionRecord) -> None:
        """Test deleting a session."""
        storage = InMemorySessionStorage()
        storage.create(sample_record)
        storage.delete(sample_record.token)

        assert storage.retrieve(sample_record.token) is None

    def test_purge_expired(self) -> None:
        """Test purging expired sessions."""
        storage = InMemorySessionStorage()
        now = datetime.now(timezone.utc)

        # Create an expired session
        expired = SessionRecord(
            token="expired",
            username="user",
            authenticated_at=now,
            last_active=now - timedelta(hours=2),
            session_timeout=timedelta(hours=1),
            auth_method="static",
        )
        storage.create(expired)

        # Create a valid session
        valid = SessionRecord(
            token="valid",
            username="user",
            authenticated_at=now,
            last_active=now,
            session_timeout=timedelta(hours=1),
            auth_method="static",
        )
        storage.create(valid)

        storage.purge_expired(now)

        assert storage.retrieve("expired") is None
        assert storage.retrieve("valid") is not None

    def test_count(self) -> None:
        """Test counting active sessions."""
        storage = InMemorySessionStorage()
        now = datetime.now(timezone.utc)

        for i in range(5):
            record = SessionRecord(
                token=f"token-{i}",
                username="user",
                authenticated_at=now,
                last_active=now,
                session_timeout=timedelta(hours=1),
                auth_method="static",
            )
            storage.create(record)

        assert storage.count(now) == 5


class TestSQLiteSessionStorage:
    """Tests for SQLiteSessionStorage."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> SQLiteSessionStorage:
        """Create a temporary SQLite storage."""
        db_path = tmp_path / "test_sessions.db"
        storage = SQLiteSessionStorage(db_path)
        yield storage
        # Clean up by deleting the database file - pytest handles tmp_path cleanup
        import gc
        gc.collect()  # Force garbage collection to close any lingering connections

    def test_create_and_retrieve(
        self, storage: SQLiteSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test creating and retrieving a session."""
        storage.create(sample_record)

        retrieved = storage.retrieve(sample_record.token)
        assert retrieved is not None
        assert retrieved.token == sample_record.token
        assert retrieved.username == sample_record.username

    def test_touch(
        self, storage: SQLiteSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test updating session activity."""
        storage.create(sample_record)

        new_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        storage.touch(
            sample_record.token,
            last_active=new_time,
            session_timeout=timedelta(hours=2),
        )

        retrieved = storage.retrieve(sample_record.token)
        assert retrieved is not None
        # Compare with some tolerance for datetime precision
        assert abs((retrieved.last_active - new_time).total_seconds()) < 1

    def test_delete(
        self, storage: SQLiteSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test deleting a session."""
        storage.create(sample_record)
        storage.delete(sample_record.token)

        assert storage.retrieve(sample_record.token) is None
