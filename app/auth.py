"""Authentication utilities for the Streamlit dashboard."""
from __future__ import annotations

import os

import streamlit as st

USERNAME_ENV_VAR = "DASHBOARD_USERNAME"
KEY_ENV_VAR = "DASHBOARD_KEY"


def _trigger_rerun() -> None:
    """Trigger a Streamlit rerun using the available API."""
    try:  # Streamlit < 1.27
        st.experimental_rerun()
    except AttributeError:  # pragma: no cover - Streamlit >= 1.27
        st.rerun()  # type: ignore[attr-defined]


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

    if st.session_state.get("authenticated"):
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
