"""Authentication dependencies for FastAPI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from portainer_dashboard.config import get_settings
from portainer_dashboard.core.session import SessionStorage
from portainer_dashboard.dependencies import get_session_storage
from portainer_dashboard.models.auth import SessionData

SESSION_COOKIE_NAME = "dashboard_session_token"


async def get_session_token(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> str | None:
    """Extract session token from cookie."""
    return session_token


async def get_optional_user(
    session_token: Annotated[str | None, Depends(get_session_token)],
    storage: Annotated[SessionStorage, Depends(get_session_storage)],
) -> SessionData | None:
    """Get the current user if authenticated, otherwise return None."""
    if not session_token:
        return None

    record = storage.retrieve(session_token)
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
        storage.delete(session_token)
        return None

    # Update last active time
    storage.touch(
        session_token,
        last_active=now,
        session_timeout=session_data.session_timeout,
    )

    return session_data


async def get_current_user(
    user: Annotated[SessionData | None, Depends(get_optional_user)],
) -> SessionData:
    """Get the current authenticated user or raise 401."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_auth_for_page(
    request: Request,
    user: Annotated[SessionData | None, Depends(get_optional_user)],
) -> SessionData | None:
    """Dependency for HTML pages that need to redirect to login."""
    # This will be used with a redirect response in the page handlers
    return user


# Type aliases for dependency injection
OptionalUserDep = Annotated[SessionData | None, Depends(get_optional_user)]
CurrentUserDep = Annotated[SessionData, Depends(get_current_user)]


__all__ = [
    "CurrentUserDep",
    "OptionalUserDep",
    "SESSION_COOKIE_NAME",
    "get_current_user",
    "get_optional_user",
    "get_session_token",
    "require_auth_for_page",
]
