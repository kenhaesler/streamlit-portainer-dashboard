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


def test_store_session_reuses_existing_cookie_token(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    token = "existing-token"

    store.create(
        SessionRecord(
            token=token,
            username="alice",
            authenticated_at=now - timedelta(hours=1),
            last_active=now - timedelta(minutes=5),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
    )

    class DummyStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}
            self.cookies = {auth.SESSION_COOKIE_NAME: token}

        def experimental_get_cookie(self, name: str) -> str | None:  # pragma: no cover - simple passthrough
            return self.cookies.get(name)

        def experimental_set_cookie(self, name: str, value: str, **kwargs) -> None:  # pragma: no cover - data capture only
            self.cookies[name] = value

    dummy_streamlit = DummyStreamlit()
    monkeypatch.setattr(auth, "st", dummy_streamlit)

    def fail_token_urlsafe(*_: object) -> str:  # pragma: no cover - defensive assertion
        raise AssertionError("token_urlsafe should not be called when reusing cookie token")

    monkeypatch.setattr(auth, "token_urlsafe", fail_token_urlsafe)

    auth._store_persistent_session("alice", now, timedelta(minutes=30))

    reused = store.retrieve(token)
    assert reused is not None
    assert reused.username == "alice"
    assert dummy_streamlit.session_state["_session_token"] == token
    assert dummy_streamlit.cookies[auth.SESSION_COOKIE_NAME] == token


def test_store_session_rejects_unknown_cookie_token(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    class DummyStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}
            self.cookies = {auth.SESSION_COOKIE_NAME: "attacker-token"}

        def experimental_get_cookie(self, name: str) -> str | None:  # pragma: no cover - simple passthrough
            return self.cookies.get(name)

        def experimental_set_cookie(self, name: str, value: str, **kwargs) -> None:  # pragma: no cover - data capture only
            self.cookies[name] = value

    dummy_streamlit = DummyStreamlit()
    monkeypatch.setattr(auth, "st", dummy_streamlit)

    generated_tokens: list[str] = []

    def fake_token_urlsafe(length: int) -> str:
        generated_tokens.append("called")
        return "fresh-token"

    monkeypatch.setattr(auth, "token_urlsafe", fake_token_urlsafe)

    auth._store_persistent_session("alice", now, timedelta(minutes=30))

    assert generated_tokens, "Expected a new token to be generated"
    assert store.retrieve("fresh-token") is not None
    assert dummy_streamlit.session_state["_session_token"] == "fresh-token"
    assert dummy_streamlit.cookies[auth.SESSION_COOKIE_NAME] == "fresh-token"


def test_store_session_replaces_cookie_when_user_changes(monkeypatch):
    store = _setup_session_store(monkeypatch)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    existing_token = "existing-token"

    store.create(
        SessionRecord(
            token=existing_token,
            username="alice",
            authenticated_at=now - timedelta(hours=1),
            last_active=now - timedelta(minutes=5),
            session_timeout=timedelta(minutes=30),
            auth_method="static",
        )
    )

    class DummyStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}
            self.cookies = {auth.SESSION_COOKIE_NAME: existing_token}

        def experimental_get_cookie(self, name: str) -> str | None:  # pragma: no cover - simple passthrough
            return self.cookies.get(name)

        def experimental_set_cookie(self, name: str, value: str, **kwargs) -> None:  # pragma: no cover - data capture only
            self.cookies[name] = value

    dummy_streamlit = DummyStreamlit()
    monkeypatch.setattr(auth, "st", dummy_streamlit)
    monkeypatch.setattr(auth, "token_urlsafe", lambda *_: "new-token")

    auth._store_persistent_session("bob", now, timedelta(minutes=30))

    assert store.retrieve(existing_token) is None
    replacement = store.retrieve("new-token")
    assert replacement is not None
    assert replacement.username == "bob"
    assert dummy_streamlit.session_state["_session_token"] == "new-token"
    assert dummy_streamlit.cookies[auth.SESSION_COOKIE_NAME] == "new-token"
