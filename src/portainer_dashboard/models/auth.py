"""Authentication models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """Authenticated user information."""

    model_config = ConfigDict(from_attributes=True)

    username: str
    auth_method: Literal["static", "oidc"] = "static"
    authenticated_at: datetime
    last_active: datetime


class SessionData(BaseModel):
    """Session data stored in the session backend."""

    model_config = ConfigDict(from_attributes=True)

    token: str
    username: str
    auth_method: Literal["static", "oidc"] = "static"
    authenticated_at: datetime
    last_active: datetime
    session_timeout: timedelta | None = None

    def is_expired(self, now: datetime) -> bool:
        """Check if the session has expired."""
        if self.session_timeout is None:
            return False
        return now - self.last_active >= self.session_timeout


class LoginRequest(BaseModel):
    """Login form submission."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response."""

    success: bool
    message: str = ""
    redirect_url: str = "/"


__all__ = [
    "LoginRequest",
    "LoginResponse",
    "SessionData",
    "User",
]
