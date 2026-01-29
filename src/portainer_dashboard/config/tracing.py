"""OpenTelemetry distributed tracing configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import PROJECT_ROOT, _empty_str_to_default_bool, _empty_str_to_default_int


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
