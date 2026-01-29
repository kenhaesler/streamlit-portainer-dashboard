"""Portainer environment configuration."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    max_connections: int = 20
    max_keepalive_connections: int = 10
    keepalive_expiry: float = 30.0

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
