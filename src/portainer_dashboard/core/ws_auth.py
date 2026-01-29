"""Shared WebSocket authentication logic.

Extracted from the triplicated _authenticate_websocket() implementations
in websocket/llm_chat.py, websocket/monitoring_insights.py, and
websocket/remediation.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import WebSocket

from portainer_dashboard.auth.dependencies import SESSION_COOKIE_NAME
from portainer_dashboard.config import get_settings
from portainer_dashboard.core.session import SessionStorage
from portainer_dashboard.dependencies import get_session_storage
from portainer_dashboard.models.auth import SessionData


async def authenticate_websocket(websocket: WebSocket) -> SessionData | None:
    """Authenticate a WebSocket connection using session cookie.

    Args:
        websocket: The WebSocket connection to authenticate.

    Returns:
        SessionData if authenticated, None otherwise.
    """
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    storage: SessionStorage = get_session_storage()
    record = storage.retrieve(token)
    if record is None:
        return None

    now = datetime.now(timezone.utc)
    settings = get_settings()

    session_data = SessionData(
        token=record.token,
        username=record.username,
        auth_method=record.auth_method,
        authenticated_at=record.authenticated_at,
        last_active=record.last_active,
        session_timeout=record.session_timeout or settings.auth.session_timeout,
    )

    if session_data.is_expired(now):
        storage.delete(token)
        return None

    # Update last active time
    storage.touch(
        token,
        last_active=now,
        session_timeout=session_data.session_timeout,
    )

    return session_data


__all__ = ["authenticate_websocket"]
