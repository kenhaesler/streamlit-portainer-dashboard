"""Authentication utilities for the Streamlit dashboard."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import streamlit as st
from streamlit_autorefresh import st_autorefresh

USERNAME_ENV_VAR = "DASHBOARD_USERNAME"
KEY_ENV_VAR = "DASHBOARD_KEY"
SESSION_TIMEOUT_ENV_VAR = "DASHBOARD_SESSION_TIMEOUT_MINUTES"


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
                st.session_state["auth_error"] = "Session expired due to inactivity."
                session_timer_placeholder.empty()
            else:
                session_timer_placeholder.info(
                    f"Session expires in {_format_remaining_time(time_remaining)}",
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

    if st.sidebar.button("Log out", use_container_width=True):
        for key in ("authenticated", "auth_error"):
            st.session_state.pop(key, None)
        _trigger_rerun()
