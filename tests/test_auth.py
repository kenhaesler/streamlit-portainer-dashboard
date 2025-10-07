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


def test_update_session_activity_refreshes_cookie(monkeypatch):
    store = _setup_session_store(monkeypatch)
    token = "token-value"
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store[token] = auth._PersistentSession(
        username="alice",
        authenticated_at=now - timedelta(minutes=5),
        last_active=now - timedelta(minutes=1),
        session_timeout=timedelta(minutes=30),
    )

    class DummyStreamlit:
        def __init__(self) -> None:
            self.session_state = {"_session_token": token}
            self.cookie_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def experimental_set_cookie(self, *args, **kwargs) -> None:  # pragma: no cover - data capture only
            self.cookie_calls.append((args, kwargs))

    dummy_streamlit = DummyStreamlit()
    monkeypatch.setattr(auth, "st", dummy_streamlit)

    auth._update_persistent_session_activity(now, timedelta(minutes=30))

    assert dummy_streamlit.cookie_calls, "Expected cookie to be refreshed"
    args, kwargs = dummy_streamlit.cookie_calls[-1]
    assert args[0] == auth.SESSION_COOKIE_NAME
    assert args[1] == token
    assert kwargs["path"] == "/"


def test_store_session_prunes_expired_entries(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store["expired"] = auth._PersistentSession(
        username="dave",
        authenticated_at=now - timedelta(hours=2),
        last_active=now - timedelta(hours=2),
        session_timeout=timedelta(minutes=30),
    )

    class DummyStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}

        def experimental_set_cookie(self, *_, **__):  # pragma: no cover - noop for tests
            return None

    dummy_streamlit = DummyStreamlit()
    monkeypatch.setattr(auth, "st", dummy_streamlit)
    monkeypatch.setattr(auth, "token_urlsafe", lambda *_: "new-token")

    auth._store_persistent_session("alice", now, timedelta(minutes=30))

    assert "expired" not in store
    assert "new-token" in store
    assert store["new-token"].username == "alice"
