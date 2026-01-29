"""Server configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = "0.0.0.0"  # nosec B104 - binding all interfaces is expected in Docker containers
    port: int = 8000
    reload: bool = False
    workers: int = 1
    log_level: str = "info"
