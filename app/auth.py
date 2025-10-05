"""Authentication utilities for the Streamlit dashboard."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import streamlit as st

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
    if st.session_state.get("authenticated"):
        last_active = st.session_state.get("last_active")
        if not isinstance(last_active, datetime):
            last_active = st.session_state.get("authenticated_at")

        if session_timeout is not None and isinstance(last_active, datetime):
            if now - last_active > session_timeout:
                st.session_state.pop("authenticated", None)
                st.session_state.pop("authenticated_at", None)
                st.session_state.pop("last_active", None)
                st.session_state["auth_error"] = "Session expired due to inactivity."
            else:
                st.session_state["last_active"] = now
                return
        else:
            st.session_state["last_active"] = now
            return

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
