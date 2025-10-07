from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import auth
from app.session_storage import InMemorySessionStorage, SessionRecord


def _setup_session_store(monkeypatch):
    store = InMemorySessionStorage()

    def _get_storage() -> InMemorySessionStorage:
        return store

    monkeypatch.setattr(auth, "_get_session_storage", _get_storage)
    return store


def test_get_active_session_count_filters_expired_sessions(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store.create(
        SessionRecord(
            token="active",
            username="alice",
            authenticated_at=now - timedelta(minutes=10),
            last_active=now - timedelta(minutes=1),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
    )
    store.create(
        SessionRecord(
            token="expired",
            username="bob",
            authenticated_at=now - timedelta(hours=2),
            last_active=now - timedelta(hours=2),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
    )

    assert auth.get_active_session_count(now=now) == 1
    assert store.retrieve("expired") is None


def test_get_active_session_count_supports_sessions_without_timeout(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store.create(
        SessionRecord(
            token="persistent",
            username="carol",
            authenticated_at=now - timedelta(days=1),
            last_active=now - timedelta(hours=1),
            session_timeout=None,
            auth_method="static",
        )
    )

    assert auth.get_active_session_count(now=now) == 1


def test_update_session_activity_refreshes_cookie(monkeypatch):
    store = _setup_session_store(monkeypatch)
    token = "token-value"
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    store.create(
        SessionRecord(
            token=token,
            username="alice",
            authenticated_at=now - timedelta(minutes=5),
            last_active=now - timedelta(minutes=1),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
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

    store.create(
        SessionRecord(
            token="expired",
            username="dave",
            authenticated_at=now - timedelta(hours=2),
            last_active=now - timedelta(hours=2),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
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

    assert store.retrieve("expired") is None
    created = store.retrieve("new-token")
    assert created is not None
    assert created.username == "alice"
