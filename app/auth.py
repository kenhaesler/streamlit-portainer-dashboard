"""Authentication utilities for the Streamlit dashboard."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from functools import lru_cache
from typing import Dict, Optional

import streamlit as st
from streamlit_autorefresh import st_autorefresh

USERNAME_ENV_VAR = "DASHBOARD_USERNAME"
KEY_ENV_VAR = "DASHBOARD_KEY"
SESSION_TIMEOUT_ENV_VAR = "DASHBOARD_SESSION_TIMEOUT_MINUTES"
SESSION_COOKIE_NAME = "dashboard_session_token"
DEFAULT_SESSION_COOKIE_DURATION = timedelta(days=30)


@dataclass
class _PersistentSession:
    """Metadata used to keep track of long-lived authenticated sessions."""

    username: str
    authenticated_at: datetime
    last_active: datetime
    session_timeout: Optional[timedelta]

    def is_expired(self, now: datetime) -> bool:
        """Return ``True`` if the session expired according to the timeout."""
        if self.session_timeout is None:
            return False
        return now - self.last_active >= self.session_timeout


@st.cache_resource(show_spinner=False)
def _get_persistent_sessions() -> Dict[str, _PersistentSession]:
    """Return a process-wide store of persistent session metadata."""

    return {}


def get_active_session_count(*, now: Optional[datetime] = None) -> int:
    """Return the number of currently active authenticated sessions.

    The count is derived from the persistent session store used for cookie
    based authentication. Expired sessions are discarded based on their
    configured timeout. Active sessions are those which have not expired –
    callers may optionally provide ``now`` to aid deterministic testing.
    """

    reference_time = now or datetime.now(timezone.utc)
    sessions = _get_persistent_sessions()
    active_tokens: list[str] = []
    expired_tokens: list[str] = []

    for token, session in list(sessions.items()):
        if session.is_expired(reference_time):
            expired_tokens.append(token)
            continue
        active_tokens.append(token)

    for token in expired_tokens:
        sessions.pop(token, None)

    return len(active_tokens)


def _trigger_rerun() -> None:
    """Trigger a Streamlit rerun using the available API."""
    try:  # Streamlit < 1.27
        st.experimental_rerun()
    except AttributeError:  # pragma: no cover - Streamlit >= 1.27
        st.rerun()  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def _get_session_timeout() -> Optional[timedelta]:
    """Return the configured session timeout, if any."""
    timeout_value = os.getenv(SESSION_TIMEOUT_ENV_VAR)
    if timeout_value is None or not timeout_value.strip():
        return None

    try:
        minutes = int(timeout_value)
    except ValueError as exc:  # pragma: no cover - defensive programming
        raise ValueError(
            "Invalid session timeout. Set "
            f"`{SESSION_TIMEOUT_ENV_VAR}` to an integer number of minutes."
        ) from exc

    if minutes <= 0:
        return None

    return timedelta(minutes=minutes)


def _format_remaining_time(delta: timedelta) -> str:
    """Return a human friendly representation of a positive timedelta."""
    total_seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:d}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes:d}m {seconds:02d}s"
    return f"{seconds:d}s"


def _format_remaining_minutes(delta: timedelta) -> str:
    """Return the remaining time rounded up to the nearest minute."""
    total_seconds = max(0, int(delta.total_seconds()))

    if total_seconds == 0:
        return "0m"

    total_minutes = math.ceil(total_seconds / 60)
    return f"{total_minutes:d}m"


def _get_session_token_from_query_params() -> Optional[str]:
    """Return the persistent session token from the query parameters, if any."""
    token_value = st.query_params.get("session_token")
    if isinstance(token_value, list):
        token_value = token_value[0] if token_value else None

    if not token_value:
        return None
    return token_value


def _ensure_session_query_param(token: Optional[str]) -> None:
    """Synchronise the ``session_token`` query parameter with the provided token."""

    params = st.query_params
    current_token = params.get("session_token")
    if isinstance(current_token, list):
        current_token = current_token[0] if current_token else None

    if token == current_token:
        return

    if token is None:
        if "session_token" in params:
            del params["session_token"]
    else:
        params["session_token"] = token


def _get_session_token_from_cookie() -> Optional[str]:
    """Return the persistent session token from the browser cookie, if any."""

    try:
        token = st.experimental_get_cookie(SESSION_COOKIE_NAME)
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return None

    if not token:
        return None
    return token


def _set_session_cookie(
    token: str, *, now: datetime, session_timeout: Optional[timedelta]
) -> None:
    """Persist the session token in a browser cookie."""

    try:
        expires_at = now + (
            session_timeout if session_timeout is not None else DEFAULT_SESSION_COOKIE_DURATION
        )
        st.experimental_set_cookie(
            SESSION_COOKIE_NAME,
            token,
            expires_at=expires_at,
            path="/",
        )
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return


def _delete_session_cookie() -> None:
    """Remove the session token cookie from the browser."""

    try:
        st.experimental_delete_cookie(SESSION_COOKIE_NAME, path="/")
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return


def _clear_persistent_session(remove_query_param: bool = True) -> None:
    """Forget any persisted session token for the active user."""

    token = st.session_state.pop("_session_token", None)
    if token:
        _get_persistent_sessions().pop(token, None)

    _delete_session_cookie()

    if remove_query_param:
        _ensure_session_query_param(None)


def _store_persistent_session(
    username: str, now: datetime, session_timeout: Optional[timedelta]
) -> None:
    """Create and persist a new session token for the authenticated user."""

    token = token_urlsafe(32)
    _get_persistent_sessions()[token] = _PersistentSession(
        username=username,
        authenticated_at=now,
        last_active=now,
        session_timeout=session_timeout,
    )
    st.session_state["_session_token"] = token
    _ensure_session_query_param(token)
    _set_session_cookie(token, now=now, session_timeout=session_timeout)


def _update_persistent_session_activity(
    now: datetime, session_timeout: Optional[timedelta]
) -> None:
    """Update the ``last_active`` timestamp for the stored session token."""

    token = st.session_state.get("_session_token")
    if not isinstance(token, str):
        return

    session = _get_persistent_sessions().get(token)
    if session is None:
        return

    session.last_active = now
    session.session_timeout = session_timeout
    _ensure_session_query_param(token)
    _set_session_cookie(token, now=now, session_timeout=session_timeout)


def _restore_persistent_session(
    expected_username: str, session_timeout: Optional[timedelta], now: datetime
) -> None:
    """Restore an authenticated session based on the persisted token, if present."""

    tokens_to_check = []
    token_from_query = _get_session_token_from_query_params()
    if token_from_query:
        tokens_to_check.append(("query", token_from_query))

    token_from_cookie = _get_session_token_from_cookie()
    if token_from_cookie and token_from_cookie != token_from_query:
        tokens_to_check.append(("cookie", token_from_cookie))

    if not tokens_to_check:
        return

    sessions = _get_persistent_sessions()

    for source, token in tokens_to_check:
        session = sessions.get(token)
        if session is None or session.username != expected_username:
            sessions.pop(token, None)
            if source == "query":
                _ensure_session_query_param(None)
            else:
                _delete_session_cookie()
            continue

        # Ensure we use the most up-to-date timeout configuration.
        session.session_timeout = session_timeout

        if session.is_expired(now):
            sessions.pop(token, None)
            if source == "query":
                _ensure_session_query_param(None)
            else:
                _delete_session_cookie()
            st.session_state.pop("authenticated", None)
            st.session_state.pop("authenticated_at", None)
            st.session_state.pop("last_active", None)
            st.session_state["auth_error"] = "Session expired due to inactivity."
            return

        st.session_state["authenticated"] = True
        st.session_state["authenticated_at"] = session.authenticated_at
        st.session_state["last_active"] = now
        st.session_state["_session_token"] = token
        _ensure_session_query_param(token)
        _set_session_cookie(token, now=now, session_timeout=session_timeout)
        session.last_active = now
        return


def require_authentication() -> None:
    """Prompt the user for credentials and block execution until authenticated."""
    expected_username = os.getenv(USERNAME_ENV_VAR)
    expected_key = os.getenv(KEY_ENV_VAR)

    if not expected_username or not expected_key:
        st.error(
            "Dashboard credentials are not configured. Set both the "
            f"`{USERNAME_ENV_VAR}` and `{KEY_ENV_VAR}` environment variables "
            "before starting the app."
        )
        st.stop()

    try:
        session_timeout = _get_session_timeout()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    now = datetime.now(timezone.utc)
    _restore_persistent_session(expected_username, session_timeout, now)
    session_timer_placeholder = st.sidebar.empty()
    auto_refresh_triggered = False

    if st.session_state.get("authenticated") and session_timeout is not None:
        refresh_count = st_autorefresh(interval=30000, key="session_timeout_refresh")
        previous_refresh_count = st.session_state.get("_session_timeout_refresh_count")
        auto_refresh_triggered = (
            previous_refresh_count is not None and refresh_count != previous_refresh_count
        )
        st.session_state["_session_timeout_refresh_count"] = refresh_count
    else:
        st.session_state.pop("_session_timeout_refresh_count", None)

    if st.session_state.get("authenticated"):
        last_active = st.session_state.get("last_active")
        if not isinstance(last_active, datetime):
            last_active = st.session_state.get("authenticated_at")

        if session_timeout is not None and isinstance(last_active, datetime):
            time_remaining = session_timeout - (now - last_active)
            if time_remaining <= timedelta(0):
                st.session_state.pop("authenticated", None)
                st.session_state.pop("authenticated_at", None)
                st.session_state.pop("last_active", None)
                _clear_persistent_session()
                st.session_state["auth_error"] = "Session expired due to inactivity."
                session_timer_placeholder.empty()
            else:
                session_timer_placeholder.info(
                    f"Session expires in {_format_remaining_minutes(time_remaining)}",
                    icon="⏳",
                )

                if timedelta(0) < time_remaining <= timedelta(seconds=30):
                    warning_container = st.empty()
                    with warning_container.container():
                        st.warning(
                            "Your session will expire soon due to inactivity.",
                            icon="⚠️",
                        )
                        st.write(
                            f"Remaining time: {_format_remaining_time(time_remaining)}"
                        )
                        if st.button("Keep me logged in", key="keep_session_active"):
                            st.session_state["last_active"] = datetime.now(timezone.utc)
                            _trigger_rerun()

                if not auto_refresh_triggered:
                    st.session_state["last_active"] = now
                    _update_persistent_session_activity(now, session_timeout)
                return
        else:
            if session_timeout is None:
                session_timer_placeholder.info(
                    "Session timeout is not configured.",
                    icon="🟢",
                )
            else:
                session_timer_placeholder.empty()
            st.session_state["last_active"] = now
            _update_persistent_session_activity(now, session_timeout)
            return

    session_timer_placeholder.empty()

    st.markdown("### 🔐 Sign in to the Portainer dashboard")
    st.caption(
        "Enter the credentials configured through the dashboard environment "
        "variables."
    )

    error_message = st.session_state.get("auth_error")
    if error_message:
        st.error(error_message)

    with st.form("dashboard-authentication"):
        username = st.text_input("Username", placeholder="Dashboard username")
        access_key = st.text_input(
            "Access key",
            placeholder="Dashboard access key",
            type="password",
        )
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if username == expected_username and access_key == expected_key:
            st.session_state["authenticated"] = True
            st.session_state["authenticated_at"] = now
            st.session_state["last_active"] = now
            _store_persistent_session(username, now, session_timeout)
            st.session_state.pop("auth_error", None)
            _trigger_rerun()
        else:
            st.session_state["auth_error"] = "Invalid username or access key."
            _trigger_rerun()

    st.stop()


def render_logout_button() -> None:
    """Display a logout control in the sidebar for authenticated users."""
    if not st.session_state.get("authenticated"):
        return

    if st.sidebar.button("Log out", width="stretch"):
        _clear_persistent_session()
        for key in ("authenticated", "auth_error"):
            st.session_state.pop(key, None)
        _trigger_rerun()
