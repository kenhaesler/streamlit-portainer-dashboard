"""Caching configuration for Portainer payloads."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import PROJECT_ROOT, _empty_str_to_default_bool, _empty_str_to_default_int


class CacheSettings(BaseSettings):
    """Caching configuration for persisted Portainer payloads."""

    model_config = SettingsConfigDict(
        env_prefix="PORTAINER_CACHE_",
        extra="ignore",
    )

    enabled: bool = True
    ttl_seconds: int = 900
    dir: Path = Field(default_factory=lambda: PROJECT_ROOT / ".data" / "cache")
    max_cache_files: int = 50
    memory_cache_max_size: int = 100
    memory_cache_ttl_seconds: int = 60

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
