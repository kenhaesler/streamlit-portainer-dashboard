"""Authentication routes for login, logout, and OIDC callback."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from portainer_dashboard.auth.dependencies import (
    SESSION_COOKIE_NAME,
    OptionalUserDep,
    get_session_storage,
)
from portainer_dashboard.auth.oidc import OIDCClient, OIDCError, create_oidc_client
from portainer_dashboard.auth.static_auth import verify_credentials
from portainer_dashboard.config import get_settings
from portainer_dashboard.core.security import generate_token
from portainer_dashboard.core.session import SessionRecord, SessionStorage
from portainer_dashboard.dependencies import JinjaEnvDep, SessionStorageDep

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory storage for OIDC state (in production, use Redis or similar)
_oidc_state_store: dict[str, dict] = {}


def _create_session(
    storage: SessionStorage,
    username: str,
    auth_method: str,
    session_timeout: timedelta | None,
) -> str:
    """Create a new session and return the token."""
    token = generate_token()
    now = datetime.now(timezone.utc)

    record = SessionRecord(
        token=token,
        username=username,
        authenticated_at=now,
        last_active=now,
        session_timeout=session_timeout,
        auth_method=auth_method,
    )
    storage.create(record)
    return token


def _set_session_cookie(response: Response, token: str) -> None:
    """Set the session cookie on the response."""
    settings = get_settings()
    max_age = 30 * 24 * 60 * 60  # 30 days
    if settings.auth.session_timeout:
        max_age = int(settings.auth.session_timeout.total_seconds())

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
    next: str = "/",
) -> HTMLResponse:
    """Render the login page."""
    if user is not None:
        return RedirectResponse(url=next, status_code=303)

    settings = get_settings()
    template = jinja.get_template("pages/login.html")
    content = await template.render_async(
        request=request,
        settings=settings,
        next_url=next,
        error=None,
    )
    return HTMLResponse(content=content)


@router.post("/login")
async def login(
    request: Request,
    jinja: JinjaEnvDep,
    storage: SessionStorageDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    """Process login form submission."""
    settings = get_settings()

    if settings.auth.provider != "static":
        raise HTTPException(status_code=400, detail="Static auth not enabled")

    if not verify_credentials(username, password):
        template = jinja.get_template("pages/login.html")
        content = await template.render_async(
            request=request,
            settings=settings,
            next_url=next,
            error="Invalid username or password",
        )
        return HTMLResponse(content=content, status_code=401)

    token = _create_session(
        storage=storage,
        username=username,
        auth_method="static",
        session_timeout=settings.auth.session_timeout,
    )

    response = RedirectResponse(url=next, status_code=303)
    _set_session_cookie(response, token)
    return response


@router.get("/logout")
async def logout(
    storage: SessionStorageDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> RedirectResponse:
    """Log out the current user."""
    if session_token:
        storage.delete(session_token)

    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/oidc/login")
async def oidc_login(next: str = "/") -> RedirectResponse:
    """Initiate OIDC authentication flow."""
    settings = get_settings()

    if settings.auth.provider != "oidc":
        raise HTTPException(status_code=400, detail="OIDC auth not enabled")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    # Store state for verification
    _oidc_state_store[state] = {
        "code_verifier": code_verifier,
        "next_url": next,
        "created_at": datetime.now(timezone.utc),
    }

    # Clean up old states (older than 10 minutes)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired_states = [
        s for s, data in _oidc_state_store.items()
        if data["created_at"] < cutoff
    ]
    for s in expired_states:
        _oidc_state_store.pop(s, None)

    client = create_oidc_client()
    auth_url = await client.get_authorization_url(state, code_verifier)

    return RedirectResponse(url=auth_url)


@router.get("/oidc/callback")
async def oidc_callback(
    storage: SessionStorageDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Handle OIDC callback after authentication."""
    settings = get_settings()

    if error:
        LOGGER.error("OIDC error: %s - %s", error, error_description)
        raise HTTPException(
            status_code=400,
            detail=f"OIDC authentication failed: {error_description or error}",
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Verify state
    state_data = _oidc_state_store.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    code_verifier = state_data["code_verifier"]
    next_url = state_data.get("next_url", "/")

    try:
        client = create_oidc_client()
        id_token, _ = await client.exchange_code(code, code_verifier)
        user_info = await client.verify_id_token(id_token)
    except OIDCError as e:
        LOGGER.error("OIDC verification failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    token = _create_session(
        storage=storage,
        username=user_info.username,
        auth_method="oidc",
        session_timeout=settings.auth.session_timeout,
    )

    response = RedirectResponse(url=next_url, status_code=303)
    _set_session_cookie(response, token)
    return response


__all__ = ["router"]
