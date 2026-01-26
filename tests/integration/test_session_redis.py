"""Integration tests for RedisSessionStorage with a real Redis instance.

These tests require a running Redis server. They will be skipped if Redis
is not available at the configured URL.

Run with: REDIS_TEST_URL=redis://localhost:6379/0 pytest tests/integration/test_session_redis.py -v
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import redis

from portainer_dashboard.core.session import RedisSessionStorage, SessionRecord


# Get Redis URL from environment or use default
REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/0")


def redis_is_available() -> bool:
    """Check if Redis is available for testing."""
    try:
        client = redis.Redis.from_url(REDIS_TEST_URL, socket_timeout=1)
        client.ping()
        client.close()
        return True
    except (redis.ConnectionError, redis.TimeoutError):
        return False


# Skip all tests in this module if Redis is not available
pytestmark = pytest.mark.skipif(
    not redis_is_available(),
    reason=f"Redis not available at {REDIS_TEST_URL}",
)


@pytest.fixture
def storage() -> RedisSessionStorage:
    """Create a RedisSessionStorage for testing with unique prefix."""
    # Use a unique prefix per test run to avoid conflicts
    prefix = f"test-session-{int(time.time() * 1000)}:"
    storage = RedisSessionStorage(
        redis_url=REDIS_TEST_URL,
        key_prefix=prefix,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    yield storage
    # Cleanup: delete all test keys
    client = redis.Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=100)
        if keys:
            client.delete(*keys)
        if cursor == 0:
            break
    client.close()
    storage.close()


@pytest.fixture
def sample_record() -> SessionRecord:
    """Create a sample session record."""
    now = datetime.now(timezone.utc)
    return SessionRecord(
        token="integration-test-token",
        username="testuser",
        authenticated_at=now,
        last_active=now,
        session_timeout=timedelta(hours=1),
        auth_method="static",
    )


class TestRedisSessionStorageIntegration:
    """Integration tests for RedisSessionStorage with real Redis."""

    def test_create_and_retrieve(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test full create and retrieve cycle."""
        storage.create(sample_record)

        retrieved = storage.retrieve(sample_record.token)

        assert retrieved is not None
        assert retrieved.token == sample_record.token
        assert retrieved.username == sample_record.username
        assert retrieved.auth_method == sample_record.auth_method

    def test_ttl_is_set(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test that Redis TTL is properly set on session creation."""
        storage.create(sample_record)

        # Check TTL directly via Redis client
        client = redis.Redis.from_url(REDIS_TEST_URL)
        key = storage._make_key(sample_record.token)
        ttl = client.ttl(key)
        client.close()

        # TTL should be around 3600 seconds (1 hour), allow some tolerance
        assert 3500 < ttl <= 3600

    def test_session_auto_expires(self, storage: RedisSessionStorage) -> None:
        """Test that sessions with short TTL auto-expire in Redis."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="short-lived-token",
            username="testuser",
            authenticated_at=now,
            last_active=now,
            session_timeout=timedelta(seconds=1),  # 1 second TTL
            auth_method="static",
        )

        storage.create(record)

        # Should exist immediately
        assert storage.retrieve(record.token) is not None

        # Wait for TTL to expire
        time.sleep(2)

        # Should be gone now
        assert storage.retrieve(record.token) is None

    def test_touch_refreshes_ttl(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test that touch updates the session and refreshes TTL."""
        storage.create(sample_record)

        # Get initial TTL
        client = redis.Redis.from_url(REDIS_TEST_URL)
        key = storage._make_key(sample_record.token)
        initial_ttl = client.ttl(key)

        # Touch with new timeout
        new_time = datetime.now(timezone.utc)
        storage.touch(
            sample_record.token,
            last_active=new_time,
            session_timeout=timedelta(hours=2),  # Extend to 2 hours
        )

        # Get new TTL
        new_ttl = client.ttl(key)
        client.close()

        # New TTL should be around 7200 seconds (2 hours)
        assert new_ttl > initial_ttl
        assert 7100 < new_ttl <= 7200

        # Verify data was updated
        retrieved = storage.retrieve(sample_record.token)
        assert retrieved is not None
        assert retrieved.session_timeout == timedelta(hours=2)

    def test_delete_removes_session(
        self, storage: RedisSessionStorage, sample_record: SessionRecord
    ) -> None:
        """Test that delete properly removes the session."""
        storage.create(sample_record)
        assert storage.retrieve(sample_record.token) is not None

        storage.delete(sample_record.token)

        assert storage.retrieve(sample_record.token) is None

    def test_count_returns_active_sessions(
        self, storage: RedisSessionStorage
    ) -> None:
        """Test that count correctly counts sessions with prefix."""
        now = datetime.now(timezone.utc)

        # Create multiple sessions
        for i in range(5):
            record = SessionRecord(
                token=f"count-test-token-{i}",
                username="testuser",
                authenticated_at=now,
                last_active=now,
                session_timeout=timedelta(hours=1),
                auth_method="static",
            )
            storage.create(record)

        count = storage.count(now)

        assert count == 5

    def test_retrieve_nonexistent_returns_none(
        self, storage: RedisSessionStorage
    ) -> None:
        """Test that retrieving a nonexistent session returns None."""
        result = storage.retrieve("nonexistent-token-xyz")

        assert result is None

    def test_session_without_timeout(self, storage: RedisSessionStorage) -> None:
        """Test creating a session without timeout (no TTL)."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            token="no-timeout-token",
            username="testuser",
            authenticated_at=now,
            last_active=now,
            session_timeout=None,
            auth_method="oidc",
        )

        storage.create(record)

        # Check that key has no TTL (returns -1)
        client = redis.Redis.from_url(REDIS_TEST_URL)
        key = storage._make_key(record.token)
        ttl = client.ttl(key)
        client.close()

        # -1 means no expiration
        assert ttl == -1

        # Should still be retrievable
        retrieved = storage.retrieve(record.token)
        assert retrieved is not None
        assert retrieved.session_timeout is None
