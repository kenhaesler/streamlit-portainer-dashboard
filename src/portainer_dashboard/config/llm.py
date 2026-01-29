"""LLM API configuration."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .helpers import _empty_str_to_default_int


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
    context_max_endpoints: int = 50
    max_connections: int = 10
    max_keepalive_connections: int = 5
    keepalive_expiry: float = 60.0

    @field_validator("context_max_endpoints", mode="before")
    @classmethod
    def handle_empty_context_max_endpoints(cls, v: str | int | None) -> int:
        return _empty_str_to_default_int(v, default=50)
