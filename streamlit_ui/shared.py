"""Shared UI components for Streamlit pages."""

from __future__ import annotations

import time
from typing import Callable

import streamlit as st

from api_client import get_api_client


# Auto-refresh configuration
AUTO_REFRESH_OPTIONS = {
    "Off": 0,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "10m": 600,
}


def require_auth() -> None:
    """Check authentication and redirect to login if needed.

    This function first checks session state, then attempts to restore
    from browser cookie (survives F5 refresh).
    """
    client = get_api_client()

    # Fast path: already authenticated
    if client.is_authenticated():
        return

    # Try to restore session from browser cookie
    if client.try_restore_session():
        return

    # No valid session
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


def render_refresh_controls(
    page_key: str,
    on_refresh: Callable[[], None] | None = None,
) -> bool:
    """Render auto-refresh toggle and manual refresh button.

    Args:
        page_key: Unique key for this page's refresh state.
        on_refresh: Optional callback when refresh is triggered.

    Returns:
        True if a refresh was triggered (manual or auto), False otherwise.
    """
    refresh_triggered = False

    col1, col2, col3 = st.columns([4, 2, 1])

    with col2:
        # Auto-refresh interval selector
        current_interval = st.session_state.get(f"{page_key}_auto_refresh", "Off")
        selected_interval = st.selectbox(
            "Auto-refresh",
            options=list(AUTO_REFRESH_OPTIONS.keys()),
            index=list(AUTO_REFRESH_OPTIONS.keys()).index(current_interval),
            key=f"{page_key}_refresh_select",
            label_visibility="collapsed",
        )
        st.session_state[f"{page_key}_auto_refresh"] = selected_interval

    with col3:
        # Manual refresh button
        if st.button("Refresh", use_container_width=True, key=f"{page_key}_manual_refresh"):
            st.cache_data.clear()
            refresh_triggered = True
            if on_refresh:
                on_refresh()

    # Handle auto-refresh timing
    interval_seconds = AUTO_REFRESH_OPTIONS.get(selected_interval, 0)
    if interval_seconds > 0:
        last_refresh_key = f"{page_key}_last_refresh"
        last_refresh = st.session_state.get(last_refresh_key, 0)
        current_time = time.time()

        if current_time - last_refresh >= interval_seconds:
            st.session_state[last_refresh_key] = current_time
            st.cache_data.clear()
            refresh_triggered = True
            if on_refresh:
                on_refresh()
            st.rerun()

        # Show time until next refresh
        time_remaining = int(interval_seconds - (current_time - last_refresh))
        if time_remaining > 0:
            with col1:
                st.caption(f"Next refresh in {time_remaining}s")

    return refresh_triggered


__all__ = [
    "require_auth",
    "render_sidebar",
    "render_session_expiry_banner",
    "render_refresh_controls",
    "AUTO_REFRESH_OPTIONS",
]
