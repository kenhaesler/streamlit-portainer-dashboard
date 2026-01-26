"""Tests for session storage module."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from portainer_dashboard.core.session import (
    InMemorySessionStorage,
    RedisSessionStorage,
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


class TestRedisSessionStorage:
    """Tests for RedisSessionStorage with mocked Redis client."""

    @pytest.fixture
    def mock_redis_client(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def storage(self, mock_redis_client: MagicMock) -> RedisSessionStorage:
        """Create a RedisSessionStorage with mocked client."""
        with patch("portainer_dashboard.core.session.redis.Redis.from_url") as mock_from_url:
            mock_from_url.return_value = mock_redis_client
            storage = RedisSessionStorage(
                redis_url="redis://localhost:6379/0",
                key_prefix="test-session:",
            )
        return storage

    def test_make_key(self, storage: RedisSessionStorage) -> None:
        """Test key generation with prefix."""
        key = storage._make_key("my-token")
        assert key == "test-session:my-token"

    def test_create_with_timeout(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test creating a session with TTL uses setex."""
        storage.create(sample_record)

        storage._client.setex.assert_called_once()
        call_args = storage._client.setex.call_args
        assert call_args[0][0] == "test-session:test-token-123"
        assert call_args[0][1] == 3600  # 1 hour in seconds

    def test_create_without_timeout(self, storage: RedisSessionStorage) -> None:
        """Test creating a session without TTL uses set."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="no-timeout-token",
            username="testuser",
            authenticated_at=now,
            last_active=now,
            session_timeout=None,
            auth_method="static",
        )

        storage.create(record)

        storage._client.set.assert_called_once()
        call_args = storage._client.set.call_args
        assert call_args[0][0] == "test-session:no-timeout-token"

    def test_retrieve_existing(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test retrieving an existing session."""
        serialized = RedisSessionStorage._serialize_record(sample_record)
        storage._client.get.return_value = serialized

        retrieved = storage.retrieve(sample_record.token)

        assert retrieved is not None
        assert retrieved.token == sample_record.token
        assert retrieved.username == sample_record.username
        storage._client.get.assert_called_once_with("test-session:test-token-123")

    def test_retrieve_nonexistent(self, storage: RedisSessionStorage) -> None:
        """Test retrieving a nonexistent session returns None."""
        storage._client.get.return_value = None

        result = storage.retrieve("nonexistent-token")

        assert result is None
        storage._client.get.assert_called_once_with("test-session:nonexistent-token")

    def test_touch_updates_record(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test touch updates last_active and refreshes TTL."""
        serialized = RedisSessionStorage._serialize_record(sample_record)
        storage._client.get.return_value = serialized

        new_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        storage.touch(
            sample_record.token,
            last_active=new_time,
            session_timeout=timedelta(hours=2),
        )

        storage._client.get.assert_called_once()
        storage._client.setex.assert_called_once()
        call_args = storage._client.setex.call_args
        assert call_args[0][1] == 7200  # 2 hours in seconds

    def test_touch_without_timeout(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test touch without timeout uses set instead of setex."""
        serialized = RedisSessionStorage._serialize_record(sample_record)
        storage._client.get.return_value = serialized

        new_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        storage.touch(
            sample_record.token,
            last_active=new_time,
            session_timeout=None,
        )

        storage._client.set.assert_called_once()

    def test_delete(self, storage: RedisSessionStorage) -> None:
        """Test deleting a session."""
        storage.delete("some-token")

        storage._client.delete.assert_called_once_with("test-session:some-token")

    def test_purge_expired_is_noop(self, storage: RedisSessionStorage) -> None:
        """Test that purge_expired is a no-op (Redis TTL handles it)."""
        now = datetime.now(timezone.utc)
        storage.purge_expired(now)

        # No Redis calls should be made
        storage._client.delete.assert_not_called()
        storage._client.get.assert_not_called()

    def test_count_uses_scan(self, storage: RedisSessionStorage) -> None:
        """Test count uses SCAN to count keys with prefix."""
        # Simulate scan returning keys in batches
        storage._client.scan.side_effect = [
            (1, ["test-session:token1", "test-session:token2"]),
            (0, ["test-session:token3"]),
        ]

        now = datetime.now(timezone.utc)
        count = storage.count(now)

        assert count == 3
        assert storage._client.scan.call_count == 2

    def test_connection_error_handling_on_create(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test graceful handling of connection errors on create."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        storage._client.setex.side_effect = RedisConnectionError("Connection refused")

        # Should not raise, just log warning
        storage.create(sample_record)

    def test_connection_error_handling_on_retrieve(
        self, storage: RedisSessionStorage
    ) -> None:
        """Test graceful handling of connection errors on retrieve."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        storage._client.get.side_effect = RedisConnectionError("Connection refused")

        result = storage.retrieve("some-token")

        assert result is None

    def test_connection_error_handling_on_count(
        self, storage: RedisSessionStorage
    ) -> None:
        """Test graceful handling of connection errors on count."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        storage._client.scan.side_effect = RedisConnectionError("Connection refused")

        now = datetime.now(timezone.utc)
        count = storage.count(now)

        assert count == 0

    def test_roundtrip_serialization(self, sample_record: SessionRecord) -> None:
        """Test that serialization and deserialization preserves data."""
        serialized = RedisSessionStorage._serialize_record(sample_record)
        deserialized = RedisSessionStorage._deserialize_record(serialized)

        assert deserialized.token == sample_record.token
        assert deserialized.username == sample_record.username
        assert deserialized.auth_method == sample_record.auth_method
        assert deserialized.session_timeout == sample_record.session_timeout
        # Datetime comparison with tolerance for microsecond precision
        assert abs(
            (deserialized.authenticated_at - sample_record.authenticated_at).total_seconds()
        ) < 1
        assert abs(
            (deserialized.last_active - sample_record.last_active).total_seconds()
        ) < 1

    def test_roundtrip_serialization_no_timeout(self) -> None:
        """Test serialization with None session_timeout."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="test",
            username="user",
            authenticated_at=now,
            last_active=now,
            session_timeout=None,
            auth_method="oidc",
        )

        serialized = RedisSessionStorage._serialize_record(record)
        deserialized = RedisSessionStorage._deserialize_record(serialized)

        assert deserialized.session_timeout is None

    def test_close(self, storage: RedisSessionStorage) -> None:
        """Test that close calls client.close()."""
        storage.close()

        storage._client.close.assert_called_once()
