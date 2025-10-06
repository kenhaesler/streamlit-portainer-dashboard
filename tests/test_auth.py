from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import auth


def _setup_session_store(monkeypatch):
    store: dict[str, auth._PersistentSession] = {}

    def _get_store() -> dict[str, auth._PersistentSession]:
        return store

    monkeypatch.setattr(auth, "_get_persistent_sessions", _get_store)
    return store


def test_get_active_session_count_filters_expired_sessions(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store["active"] = auth._PersistentSession(
        username="alice",
        authenticated_at=now - timedelta(minutes=10),
        last_active=now - timedelta(minutes=1),
        session_timeout=timedelta(minutes=30),
    )
    store["expired"] = auth._PersistentSession(
        username="bob",
        authenticated_at=now - timedelta(hours=2),
        last_active=now - timedelta(hours=2),
        session_timeout=timedelta(minutes=30),
    )

    assert auth.get_active_session_count(now=now) == 1
    assert "expired" not in store


def test_get_active_session_count_supports_sessions_without_timeout(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store["persistent"] = auth._PersistentSession(
        username="carol",
        authenticated_at=now - timedelta(days=1),
        last_active=now - timedelta(hours=1),
        session_timeout=None,
    )

    assert auth.get_active_session_count(now=now) == 1
