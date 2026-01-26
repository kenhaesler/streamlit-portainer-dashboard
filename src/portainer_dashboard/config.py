"""Application configuration via Pydantic Settings."""

from __future__ import annotations

import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_str_to_none(v: str | None) -> str | None:
    """Convert empty strings to None so Pydantic uses field defaults."""
    if v == "":
        return None
    return v


def _empty_str_to_default_bool(v: str | bool | None, default: bool) -> bool:
    """Convert empty strings to default bool value."""
    if v == "" or v is None:
        return default
    if isinstance(v, bool):
        return v
    # Handle string boolean values
    return v.lower() in {"true", "1", "yes", "on"}


def _empty_str_to_default_int(v: str | int | None, default: int) -> int:
    """Convert empty strings to default int value."""
    if v == "" or v is None:
        return default
    if isinstance(v, int):
        return v
    return int(v)


class ConfigurationError(RuntimeError):
    """Raised when dashboard configuration is invalid."""


def _project_root() -> Path:
    """Return the project root directory."""
    try:
        return Path(__file__).resolve().parents[2]
    except IndexError:
        return Path.cwd()


PROJECT_ROOT = _project_root()


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


class AuthSettings(BaseSettings):
    """Authentication configuration for the dashboard."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_",
        extra="ignore",
    )

    auth_provider: Literal["static", "oidc"] = "static"
    session_timeout_minutes: int = 60  # Default: 60 minutes

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


class CacheSettings(BaseSettings):
    """Caching configuration for persisted Portainer payloads."""

    model_config = SettingsConfigDict(
        env_prefix="PORTAINER_CACHE_",
        extra="ignore",
    )

    enabled: bool = True
    ttl_seconds: int = 900
    dir: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "cache")

    @field_validator("enabled", mode="before")
    @classmethod
    def handle_empty_enabled(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("ttl_seconds", mode="before")
    @classmethod
    def handle_empty_ttl(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=900)

    @field_validator("dir", mode="before")
    @classmethod
    def expand_directory(cls, v: str | Path | None) -> Path:
        if v is None or v == "":
            return PROJECT_ROOT / ".data" / "cache"
        return Path(v).expanduser()

    @property
    def directory(self) -> Path:
        """Alias for dir to maintain API compatibility."""
        return self.dir


class PortainerEnvironmentSettings(BaseSettings):
    """Single Portainer environment configuration."""

    name: str
    api_url: str
    api_key: str
    verify_ssl: bool = True
    timeout: float = 60.0  # Increased from 30s to handle slow API responses


class PortainerSettings(BaseSettings):
    """Portainer environment configuration loaded at startup."""

    model_config = SettingsConfigDict(
        env_prefix="PORTAINER_",
        extra="ignore",
    )

    api_url: str | None = None
    api_key: str | None = None
    verify_ssl: bool = True
    timeout: float = 60.0  # Increased from 30s to handle slow API responses
    environment_name: str = "Default"
    environments: str = ""

    def get_configured_environments(self) -> list[PortainerEnvironmentSettings]:
        """Return all configured Portainer environments from environment variables."""
        configured: list[PortainerEnvironmentSettings] = []

        if self.environments.strip():
            names = [n.strip() for n in self.environments.split(",") if n.strip()]
            for name in names:
                key_prefix = name.upper().replace(" ", "_")
                api_url = os.getenv(f"PORTAINER_{key_prefix}_API_URL", "").strip()
                api_key = os.getenv(f"PORTAINER_{key_prefix}_API_KEY", "").strip()
                verify_ssl_raw = os.getenv(f"PORTAINER_{key_prefix}_VERIFY_SSL", "true")
                verify_ssl = verify_ssl_raw.strip().lower() not in {"0", "false", "no", "off"}
                timeout_raw = os.getenv(f"PORTAINER_{key_prefix}_TIMEOUT", "").strip()
                timeout = float(timeout_raw) if timeout_raw else self.timeout
                if api_url and api_key:
                    configured.append(
                        PortainerEnvironmentSettings(
                            name=name,
                            api_url=api_url,
                            api_key=api_key,
                            verify_ssl=verify_ssl,
                            timeout=timeout,
                        )
                    )
            return configured

        if self.api_url and self.api_key:
            configured.append(
                PortainerEnvironmentSettings(
                    name=self.environment_name,
                    api_url=self.api_url,
                    api_key=self.api_key,
                    verify_ssl=self.verify_ssl,
                    timeout=self.timeout,
                )
            )
        return configured


class LLMSettings(BaseSettings):
    """LLM API configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
    )

    api_endpoint: str | None = None
    bearer_token: str | None = None
    model: str = "gpt-oss"
    max_tokens: int = 4096
    ca_bundle: str | None = None
    timeout: int = 60


class KibanaSettings(BaseSettings):
    """Kibana/Elasticsearch configuration for log retrieval."""

    model_config = SettingsConfigDict(
        env_prefix="KIBANA_",
        extra="ignore",
    )

    logs_endpoint: str | None = None
    api_key: str | None = None
    verify_ssl: bool = True
    timeout_seconds: int = 60  # Increased from 30s to handle slow API responses

    @property
    def timeout(self) -> int:
        """Alias for timeout_seconds to maintain API compatibility."""
        return self.timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Return True if Kibana is configured."""
        return bool(self.logs_endpoint and self.api_key)


class SessionSettings(BaseSettings):
    """Session storage configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_SESSION_",
        extra="ignore",
    )

    backend: Literal["memory", "sqlite"] = "memory"
    sqlite_path: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "sessions.db")

    @field_validator("backend", mode="before")
    @classmethod
    def parse_backend(cls, v: str | None) -> str:
        if v is None or v == "":
            return "memory"
        return v

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_sqlite_path(cls, v: str | Path | None) -> Path:
        if v is None or v == "":
            return PROJECT_ROOT / ".data" / "sessions.db"
        return Path(v).expanduser()


class MonitoringSettings(BaseSettings):
    """AI monitoring service configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MONITORING_",
        extra="ignore",
    )

    enabled: bool = True
    interval_minutes: int = 5
    max_insights_stored: int = 100
    include_security_scan: bool = True
    include_image_check: bool = True
    include_log_analysis: bool = True
    log_tail_lines: int = 100
    max_containers_for_logs: int = 10
    log_fetch_timeout: float = 10.0
    elevated_capabilities: list[str] = Field(
        default_factory=lambda: [
            "NET_ADMIN",
            "SYS_ADMIN",
            "SYS_PTRACE",
            "SYS_RAWIO",
            "SYS_MODULE",
            "DAC_OVERRIDE",
            "SETUID",
            "SETGID",
        ]
    )
    excluded_containers_raw: str = Field(
        default="portainer,sysdig-host-shield,traefik,portainer_edge_agent",
        validation_alias="MONITORING_EXCLUDED_CONTAINERS",
        description="Comma-separated container name patterns to exclude from monitoring (infrastructure containers that run privileged)",
    )

    @property
    def excluded_containers(self) -> list[str]:
        """Return list of container names to exclude from monitoring."""
        if not self.excluded_containers_raw:
            return ["portainer", "sysdig-host-shield", "traefik", "portainer_edge_agent"]
        return [name.strip() for name in self.excluded_containers_raw.split(",") if name.strip()]

    @field_validator("enabled", "include_security_scan", "include_image_check", "include_log_analysis", mode="before")
    @classmethod
    def handle_empty_bool(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("interval_minutes", mode="before")
    @classmethod
    def handle_empty_interval(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=5)

    @field_validator("max_insights_stored", mode="before")
    @classmethod
    def handle_empty_max_insights(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=100)

    @field_validator("log_tail_lines", mode="before")
    @classmethod
    def handle_empty_log_tail(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=100)

    @field_validator("max_containers_for_logs", mode="before")
    @classmethod
    def handle_empty_max_containers(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=10)

    @field_validator("log_fetch_timeout", mode="before")
    @classmethod
    def handle_empty_timeout(cls, v: str | float | None) -> float:
        if v == "" or v is None:
            return 10.0
        if isinstance(v, float):
            return v
        return float(v)

class MetricsSettings(BaseSettings):
    """Time-series metrics collection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MONITORING_METRICS_",
        extra="ignore",
    )

    enabled: bool = True
    retention_hours: int = 168  # 7 days
    collection_interval_seconds: int = 60
    sqlite_path: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "metrics.db")
    anomaly_detection_enabled: bool = True
    zscore_threshold: float = 3.0
    moving_average_window: int = 30
    min_samples_for_detection: int = 10

    @field_validator("enabled", "anomaly_detection_enabled", mode="before")
    @classmethod
    def handle_empty_bool(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("retention_hours", mode="before")
    @classmethod
    def handle_empty_retention(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=168)

    @field_validator("collection_interval_seconds", mode="before")
    @classmethod
    def handle_empty_interval(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=60)

    @field_validator("moving_average_window", mode="before")
    @classmethod
    def handle_empty_window(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=30)

    @field_validator("min_samples_for_detection", mode="before")
    @classmethod
    def handle_empty_min_samples(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=10)

    @field_validator("zscore_threshold", mode="before")
    @classmethod
    def handle_empty_zscore(cls, v: str | float | None) -> float:
        if v == "" or v is None:
            return 3.0
        if isinstance(v, float):
            return v
        return float(v)

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_metrics_path(cls, v: str | Path | None) -> Path:
        if v is None or v == "":
            return PROJECT_ROOT / ".data" / "metrics.db"
        return Path(v).expanduser()


class RemediationSettings(BaseSettings):
    """Self-healing remediation action configuration."""

    model_config = SettingsConfigDict(
        env_prefix="REMEDIATION_",
        extra="ignore",
    )

    enabled: bool = True
    auto_suggest: bool = True  # Auto-generate suggestions from insights
    max_pending_actions: int = 100
    action_timeout_seconds: int = 60
    sqlite_path: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "actions.db")

    @field_validator("enabled", "auto_suggest", mode="before")
    @classmethod
    def handle_empty_bool(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("max_pending_actions", mode="before")
    @classmethod
    def handle_empty_max_pending(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=100)

    @field_validator("action_timeout_seconds", mode="before")
    @classmethod
    def handle_empty_timeout(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=60)

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_actions_path(cls, v: str | Path | None) -> Path:
        if v is None or v == "":
            return PROJECT_ROOT / ".data" / "actions.db"
        return Path(v).expanduser()


class TracingSettings(BaseSettings):
    """OpenTelemetry distributed tracing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="TRACING_",
        extra="ignore",
    )

    enabled: bool = True
    service_name: str = "portainer-dashboard"
    sqlite_path: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "traces.db")
    retention_hours: int = 24
    sample_rate: float = 1.0

    @field_validator("enabled", mode="before")
    @classmethod
    def handle_empty_enabled(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("retention_hours", mode="before")
    @classmethod
    def handle_empty_retention(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=24)

    @field_validator("sample_rate", mode="before")
    @classmethod
    def handle_empty_sample_rate(cls, v: str | float | None) -> float:
        if v == "" or v is None:
            return 1.0
        if isinstance(v, float):
            return v
        return float(v)

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_traces_path(cls, v: str | Path | None) -> Path:
        if v is None or v == "":
            return PROJECT_ROOT / ".data" / "traces.db"
        return Path(v).expanduser()


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 1
    log_level: str = "info"


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


__all__ = [
    "AuthSettings",
    "CacheSettings",
    "ConfigurationError",
    "KibanaSettings",
    "LLMSettings",
    "MetricsSettings",
    "MonitoringSettings",
    "OIDCSettings",
    "PortainerEnvironmentSettings",
    "PortainerSettings",
    "PROJECT_ROOT",
    "RemediationSettings",
    "SessionSettings",
    "ServerSettings",
    "Settings",
    "StaticAuthSettings",
    "TracingSettings",
    "get_settings",
    "reload_settings",
]
