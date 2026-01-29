"""Session storage configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import PROJECT_ROOT, _empty_str_to_default_bool, _empty_str_to_default_int


class SessionSettings(BaseSettings):
    """Session storage configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DASHBOARD_SESSION_",
        extra="ignore",
    )

    backend: Literal["memory", "sqlite", "redis"] = "memory"
    sqlite_path: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "sessions.db")

    # Redis settings
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "session:"
    redis_socket_timeout: float = 5.0
    redis_socket_connect_timeout: float = 5.0
    redis_retry_on_timeout: bool = True
    redis_health_check_interval: int = 30

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

    @field_validator("redis_url", mode="before")
    @classmethod
    def parse_redis_url(cls, v: str | None) -> str:
        if v is None or v == "":
            return "redis://localhost:6379/0"
        return v

    @field_validator("redis_key_prefix", mode="before")
    @classmethod
    def parse_redis_key_prefix(cls, v: str | None) -> str:
        if v is None or v == "":
            return "session:"
        return v

    @field_validator("redis_socket_timeout", "redis_socket_connect_timeout", mode="before")
    @classmethod
    def handle_empty_redis_timeout(cls, v: str | float | None) -> float:
        if v == "" or v is None:
            return 5.0
        if isinstance(v, float):
            return v
        return float(v)

    @field_validator("redis_retry_on_timeout", mode="before")
    @classmethod
    def handle_empty_retry(cls, v: str | bool | None) -> bool:
        return _empty_str_to_default_bool(v, default=True)

    @field_validator("redis_health_check_interval", mode="before")
    @classmethod
    def handle_empty_health_check(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=30)
