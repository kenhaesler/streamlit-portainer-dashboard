"""Shared UI components for Streamlit pages."""

from __future__ import annotations

import streamlit as st

from api_client import get_api_client


def require_auth() -> None:
    """Check authentication and redirect to login if needed."""
    client = get_api_client()
    if not client.is_authenticated():
        st.warning("Please login from the Home page")
        st.stop()


def render_sidebar() -> None:
    """Render sidebar with user info, session timeout, and logout."""
    client = get_api_client()

    with st.sidebar:
        st.markdown(f"**Logged in as:** {st.session_state.get('username', 'User')}")

        # Get session status for timeout display
        session_info = client.get_session_status()
        if session_info:
            minutes_remaining = session_info.get("minutes_remaining", 0)
            seconds_remaining = session_info.get("seconds_remaining", 0)

            # Format time remaining
            if minutes_remaining > 5:
                # Show minutes only when there's plenty of time
                time_str = f"{minutes_remaining} min"
                st.caption(f"Session expires in {time_str}")
            elif minutes_remaining > 0:
                # Show more precise time when running low
                secs = seconds_remaining % 60
                time_str = f"{minutes_remaining}:{secs:02d}"
                st.warning(f"Session expires in {time_str}")
            else:
                # Session about to expire
                st.error(f"Session expires in {seconds_remaining}s")

        if st.button("Logout", use_container_width=True):
            client.logout()
            st.rerun()

        st.markdown("---")


def render_session_expiry_banner() -> None:
    """Render a session expiry banner at the top if time is running low."""
    client = get_api_client()
    session_info = client.get_session_status()

    if session_info:
        minutes_remaining = session_info.get("minutes_remaining", 0)

        if minutes_remaining <= 5:
            seconds_remaining = session_info.get("seconds_remaining", 0)
            if minutes_remaining > 0:
                secs = seconds_remaining % 60
                time_str = f"{minutes_remaining}:{secs:02d}"
            else:
                time_str = f"{seconds_remaining} seconds"

            st.warning(
                f"Your session will expire in **{time_str}**. "
                "Please save any unsaved work. "
                "[Refresh to extend session](#)"
            )


__all__ = ["require_auth", "render_sidebar", "render_session_expiry_banner"]
