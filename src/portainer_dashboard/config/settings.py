"""Aggregate settings and cached accessor."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .auth import (
    AuthSettings,
    OIDCSettings,
    RateLimitSettings,
    StaticAuthSettings,
    WebSocketSettings,
)
from .cache import CacheSettings
from .helpers import ConfigurationError
from .llm import LLMSettings
from .monitoring import (
    KibanaSettings,
    MetricsSettings,
    MonitoringSettings,
    RemediationSettings,
)
from .portainer import PortainerSettings
from .server import ServerSettings
from .session import SessionSettings
from .tracing import TracingSettings


class Settings(BaseSettings):
    """Aggregate configuration for the dashboard."""

    model_config = SettingsConfigDict(extra="ignore")

    auth: AuthSettings = Field(default_factory=AuthSettings)
    static_auth: StaticAuthSettings = Field(default_factory=StaticAuthSettings)
    oidc: OIDCSettings = Field(default_factory=OIDCSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    portainer: PortainerSettings = Field(default_factory=PortainerSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    kibana: KibanaSettings = Field(default_factory=KibanaSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)
    remediation: RemediationSettings = Field(default_factory=RemediationSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)

    @model_validator(mode="after")
    def validate_oidc_when_enabled(self) -> "Settings":
        """Validate OIDC settings when OIDC auth is enabled."""
        if self.auth.provider == "oidc":
            if not self.oidc.issuer:
                raise ConfigurationError(
                    "OIDC authentication is enabled but the issuer URL is missing. "
                    "Set DASHBOARD_OIDC_ISSUER."
                )
            if not self.oidc.client_id:
                raise ConfigurationError(
                    "OIDC authentication is enabled but the client ID is missing. "
                    "Set DASHBOARD_OIDC_CLIENT_ID."
                )
            if not self.oidc.redirect_uri:
                raise ConfigurationError(
                    "OIDC authentication requires a redirect URI. "
                    "Set DASHBOARD_OIDC_REDIRECT_URI."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()


def reload_settings() -> Settings:
    """Force settings cache to reload from environment."""
    get_settings.cache_clear()
    return get_settings()
