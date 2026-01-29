"""Authentication and access-control configuration."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import _empty_str_to_default_bool, _empty_str_to_default_int


class StaticAuthSettings(BaseSettings):
    """Static credential pair used for dashboard authentication."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_",
        extra="ignore",
    )

    username: str | None = None
    key: str | None = None


class OIDCSettings(BaseSettings):
    """Configuration required to initiate the OIDC authorisation flow."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_OIDC_",
        extra="ignore",
    )

    issuer: str = ""
    client_id: str = ""
    client_secret: str | None = None
    redirect_uri: str = ""
    scopes: str = "openid profile email"
    discovery_url: str | None = None
    audience: str | None = None

    @property
    def scope_list(self) -> list[str]:
        """Return normalised list of scopes with openid first."""
        raw = self.scopes.replace(",", " ").split()
        scopes = [s.strip() for s in raw if s.strip()]
        if "openid" not in scopes:
            scopes.insert(0, "openid")
        seen: set[str] = set()
        deduped: list[str] = []
        for scope in scopes:
            if scope not in seen:
                seen.add(scope)
                deduped.append(scope)
        return deduped

    @property
    def well_known_url(self) -> str:
        """Return the OIDC discovery URL."""
        if self.discovery_url:
            return self.discovery_url
        return f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_RATE_LIMIT_",
        extra="ignore",
    )

    enabled: bool = True
    login_rate_limit: str = "5/minute"
    global_rate_limit: str = "100/minute"

    @field_validator("enabled", mode="before")
    @classmethod
    def handle_empty_enabled(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)


class WebSocketSettings(BaseSettings):
    """WebSocket connection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_WS_",
        extra="ignore",
    )

    max_connections_per_user: int = 5

    @field_validator("max_connections_per_user", mode="before")
    @classmethod
    def handle_empty_max(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=5)


class AuthSettings(BaseSettings):
    """Authentication configuration for the dashboard."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_",
        extra="ignore",
    )

    auth_provider: Literal["static", "oidc"] = "static"
    session_timeout_minutes: int = 60  # Default: 60 minutes
    secure_cookies: bool = False  # Set to True in production with HTTPS
    cors_origins: str = ""  # Comma-separated allowed origins; empty = allow all (for backward compat)

    @field_validator("secure_cookies", mode="before")
    @classmethod
    def handle_empty_secure_cookies(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=False)

    @property
    def provider(self) -> Literal["static", "oidc"]:
        """Alias for auth_provider to maintain API compatibility."""
        return self.auth_provider

    @property
    def session_timeout(self) -> timedelta:
        """Return session timeout as timedelta."""
        if self.session_timeout_minutes <= 0:
            return timedelta(minutes=60)  # Fallback to 60 min
        return timedelta(minutes=self.session_timeout_minutes)

    @property
    def cors_origin_list(self) -> list[str]:
        """Return list of allowed CORS origins."""
        if not self.cors_origins:
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
