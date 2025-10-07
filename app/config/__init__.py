from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.settings import (  # type: ignore[import-not-found]
        PortainerEnvironment,
        get_configured_environments,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from settings import (  # type: ignore[no-redef]
        PortainerEnvironment,
        get_configured_environments,
    )


LOGGER = logging.getLogger(__name__)

# Authentication environment variables
USERNAME_ENV_VAR = "DASHBOARD_USERNAME"
KEY_ENV_VAR = "DASHBOARD_KEY"
SESSION_TIMEOUT_ENV_VAR = "DASHBOARD_SESSION_TIMEOUT_MINUTES"
AUTH_PROVIDER_ENV_VAR = "DASHBOARD_AUTH_PROVIDER"
OIDC_ISSUER_ENV_VAR = "DASHBOARD_OIDC_ISSUER"
OIDC_CLIENT_ID_ENV_VAR = "DASHBOARD_OIDC_CLIENT_ID"
OIDC_CLIENT_SECRET_ENV_VAR = "DASHBOARD_OIDC_CLIENT_SECRET"
OIDC_REDIRECT_URI_ENV_VAR = "DASHBOARD_OIDC_REDIRECT_URI"
OIDC_SCOPES_ENV_VAR = "DASHBOARD_OIDC_SCOPES"
OIDC_DISCOVERY_URL_ENV_VAR = "DASHBOARD_OIDC_DISCOVERY_URL"
OIDC_AUDIENCE_ENV_VAR = "DASHBOARD_OIDC_AUDIENCE"

# Cache environment variables
CACHE_ENABLED_ENV_VAR = "PORTAINER_CACHE_ENABLED"
CACHE_TTL_ENV_VAR = "PORTAINER_CACHE_TTL_SECONDS"
CACHE_DIR_ENV_VAR = "PORTAINER_CACHE_DIR"
DEFAULT_CACHE_TTL_SECONDS = 900

# Portainer environment variables
PORTAINER_API_URL_ENV_VAR = "PORTAINER_API_URL"
PORTAINER_API_KEY_ENV_VAR = "PORTAINER_API_KEY"
PORTAINER_VERIFY_SSL_ENV_VAR = "PORTAINER_VERIFY_SSL"
PORTAINER_ENVIRONMENT_NAME_ENV_VAR = "PORTAINER_ENVIRONMENT_NAME"

_FALSEY_VALUES = {"0", "false", "no", "off"}


class ConfigurationError(RuntimeError):
    """Raised when dashboard configuration is invalid."""


@dataclass(frozen=True)
class StaticAuthConfig:
    """Static credential pair used for dashboard authentication."""

    username: str | None
    key: str | None


@dataclass(frozen=True)
class OIDCConfig:
    """Configuration required to initiate the OIDC authorisation flow."""

    issuer: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: tuple[str, ...]
    audience: str | None
    discovery_url: str


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration for the dashboard."""

    provider: str
    session_timeout: timedelta | None
    static: StaticAuthConfig
    oidc: OIDCConfig | None


@dataclass(frozen=True)
class CacheConfig:
    """Caching configuration for persisted Portainer payloads."""

    enabled: bool
    ttl_seconds: int
    directory: Path


@dataclass(frozen=True)
class PortainerDefaults:
    """Default Portainer environment derived from environment variables."""

    api_url: str | None
    api_key: str | None
    verify_ssl: bool
    environment_name: str | None


@dataclass(frozen=True)
class PortainerConfig:
    """Portainer environment configuration loaded at startup."""

    default_environment: PortainerDefaults
    configured_environments: tuple[PortainerEnvironment, ...]


@dataclass(frozen=True)
class Config:
    """Aggregate configuration for the Streamlit dashboard."""

    auth: AuthConfig
    cache: CacheConfig
    portainer: PortainerConfig


def _get_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned.lower() not in _FALSEY_VALUES


def _normalise_scopes(raw_scopes: str | None) -> tuple[str, ...]:
    if not raw_scopes:
        scopes: list[str] = ["openid", "profile", "email"]
    else:
        scopes = [scope for scope in raw_scopes.replace(",", " ").split() if scope]
        if "openid" not in scopes:
            scopes.insert(0, "openid")
    seen: set[str] = set()
    deduped: list[str] = []
    for scope in scopes:
        if scope in seen:
            continue
        seen.add(scope)
        deduped.append(scope)
    return tuple(deduped)


def _build_well_known_url(issuer: str) -> str:
    cleaned = issuer.rstrip("/")
    return f"{cleaned}/.well-known/openid-configuration"


def _parse_session_timeout(raw_value: str | None) -> timedelta | None:
    if raw_value is None:
        return None
    cleaned = raw_value.strip()
    if not cleaned:
        return None
    try:
        minutes = int(cleaned)
    except ValueError as exc:
        raise ConfigurationError(
            "Invalid value for DASHBOARD_SESSION_TIMEOUT_MINUTES. Provide the number of minutes as an integer."
        ) from exc
    if minutes <= 0:
        return None
    return timedelta(minutes=minutes)


def _load_oidc_config() -> OIDCConfig:
    issuer = _get_env(OIDC_ISSUER_ENV_VAR)
    if not issuer:
        raise ConfigurationError(
            "OIDC authentication is enabled but the issuer URL is missing. Set `DASHBOARD_OIDC_ISSUER`."
        )
    client_id = _get_env(OIDC_CLIENT_ID_ENV_VAR)
    if not client_id:
        raise ConfigurationError(
            "OIDC authentication is enabled but the client ID is missing. Set `DASHBOARD_OIDC_CLIENT_ID`."
        )
    redirect_uri = _get_env(OIDC_REDIRECT_URI_ENV_VAR)
    if not redirect_uri:
        raise ConfigurationError(
            "OIDC authentication requires a redirect URI. Set `DASHBOARD_OIDC_REDIRECT_URI`."
        )
    discovery_url = _get_env(OIDC_DISCOVERY_URL_ENV_VAR)
    if not discovery_url:
        discovery_url = _build_well_known_url(issuer)
    client_secret = _get_env(OIDC_CLIENT_SECRET_ENV_VAR)
    scopes = _normalise_scopes(_get_env(OIDC_SCOPES_ENV_VAR))
    audience = _get_env(OIDC_AUDIENCE_ENV_VAR)
    return OIDCConfig(
        issuer=issuer.rstrip("/"),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        audience=audience,
        discovery_url=discovery_url,
    )


def _load_auth_config() -> AuthConfig:
    provider = (_get_env(AUTH_PROVIDER_ENV_VAR) or "static").lower()
    session_timeout = _parse_session_timeout(_get_env(SESSION_TIMEOUT_ENV_VAR))
    static_config = StaticAuthConfig(
        username=_get_env(USERNAME_ENV_VAR),
        key=_get_env(KEY_ENV_VAR),
    )
    oidc_config: OIDCConfig | None = None
    if provider == "oidc":
        oidc_config = _load_oidc_config()
    return AuthConfig(
        provider=provider,
        session_timeout=session_timeout,
        static=static_config,
        oidc=oidc_config,
    )


def _load_cache_config() -> CacheConfig:
    enabled = _parse_bool(_get_env(CACHE_ENABLED_ENV_VAR), default=True)
    raw_ttl = _get_env(CACHE_TTL_ENV_VAR)
    if raw_ttl is None:
        ttl_seconds = DEFAULT_CACHE_TTL_SECONDS
    else:
        try:
            ttl_seconds = int(raw_ttl)
        except ValueError:
            LOGGER.warning(
                "Invalid value for %s: %s. Falling back to default TTL (%s seconds).",
                CACHE_TTL_ENV_VAR,
                raw_ttl,
                DEFAULT_CACHE_TTL_SECONDS,
            )
            ttl_seconds = DEFAULT_CACHE_TTL_SECONDS
    directory_override = _get_env(CACHE_DIR_ENV_VAR)
    if directory_override:
        directory = Path(directory_override).expanduser()
    else:
        directory = Path(__file__).resolve().parent.parent / ".streamlit" / "cache"
    return CacheConfig(enabled=enabled, ttl_seconds=ttl_seconds, directory=directory)


def _load_portainer_defaults() -> PortainerDefaults:
    return PortainerDefaults(
        api_url=_get_env(PORTAINER_API_URL_ENV_VAR),
        api_key=_get_env(PORTAINER_API_KEY_ENV_VAR),
        verify_ssl=_parse_bool(_get_env(PORTAINER_VERIFY_SSL_ENV_VAR), default=True),
        environment_name=_get_env(PORTAINER_ENVIRONMENT_NAME_ENV_VAR),
    )


def _load_portainer_config() -> PortainerConfig:
    defaults = _load_portainer_defaults()
    try:
        environments = tuple(get_configured_environments())
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    return PortainerConfig(default_environment=defaults, configured_environments=environments)


def _build_config() -> Config:
    auth_config = _load_auth_config()
    cache_config = _load_cache_config()
    portainer_config = _load_portainer_config()
    return Config(auth=auth_config, cache=cache_config, portainer=portainer_config)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the cached configuration for the dashboard."""

    return _build_config()


def reload_config() -> Config:
    """Force the configuration cache to reload from the environment."""

    get_config.cache_clear()
    return get_config()


__all__ = [
    "AUTH_PROVIDER_ENV_VAR",
    "CACHE_DIR_ENV_VAR",
    "CACHE_ENABLED_ENV_VAR",
    "CACHE_TTL_ENV_VAR",
    "Config",
    "ConfigurationError",
    "DEFAULT_CACHE_TTL_SECONDS",
    "KEY_ENV_VAR",
    "OIDC_AUDIENCE_ENV_VAR",
    "OIDC_CLIENT_ID_ENV_VAR",
    "OIDC_CLIENT_SECRET_ENV_VAR",
    "OIDC_DISCOVERY_URL_ENV_VAR",
    "OIDC_ISSUER_ENV_VAR",
    "OIDC_REDIRECT_URI_ENV_VAR",
    "OIDC_SCOPES_ENV_VAR",
    "PORTAINER_API_KEY_ENV_VAR",
    "PORTAINER_API_URL_ENV_VAR",
    "PORTAINER_ENVIRONMENT_NAME_ENV_VAR",
    "PORTAINER_VERIFY_SSL_ENV_VAR",
    "SESSION_TIMEOUT_ENV_VAR",
    "StaticAuthConfig",
    "OIDCConfig",
    "AuthConfig",
    "CacheConfig",
    "PortainerConfig",
    "PortainerDefaults",
    "USERNAME_ENV_VAR",
    "get_config",
    "reload_config",
]
