"""Monitoring, metrics, remediation, and Kibana configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import PROJECT_ROOT, _empty_str_to_default_bool, _empty_str_to_default_int


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
