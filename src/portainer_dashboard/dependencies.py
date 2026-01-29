"""FastAPI dependency injection providers."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, AsyncGenerator

from fastapi import Depends, Request
from jinja2 import Environment, FileSystemLoader, select_autoescape

from portainer_dashboard.config import (
    PROJECT_ROOT,
    Settings,
    get_settings,
)
from portainer_dashboard.core.session import SessionStorage, create_session_storage


def get_settings_dep() -> Settings:
    """Dependency that provides the settings instance."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@lru_cache(maxsize=1)
def _get_session_storage() -> SessionStorage:
    """Create and cache the session storage instance."""
    return create_session_storage()


def get_session_storage() -> SessionStorage:
    """Dependency that provides the session storage instance."""
    return _get_session_storage()


SessionStorageDep = Annotated[SessionStorage, Depends(get_session_storage)]


@lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Create and cache the Jinja2 environment."""
    templates_dir = PROJECT_ROOT / "templates"
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=True,
    )
    env.globals["settings"] = get_settings()
    return env


def get_jinja_env() -> Environment:
    """Dependency that provides the Jinja2 environment."""
    return _get_jinja_env()


JinjaEnvDep = Annotated[Environment, Depends(get_jinja_env)]


async def get_template_context(
    request: Request,
    settings: SettingsDep,
) -> dict:
    """Build the base template context for page rendering."""
    return {
        "request": request,
        "settings": settings,
        "current_path": request.url.path,
    }


TemplateContextDep = Annotated[dict, Depends(get_template_context)]


def get_client_pool_dep():
    """Dependency that provides the Portainer client pool."""
    from portainer_dashboard.services.portainer_client import get_client_pool
    return get_client_pool()


def get_event_bus_dep():
    """Dependency that provides the event bus."""
    from portainer_dashboard.core.event_bus import get_event_bus
    return get_event_bus()


def get_audit_logger_dep():
    """Dependency that provides the audit logger."""
    from portainer_dashboard.core.audit import get_audit_logger
    return get_audit_logger()


def reset_dependencies() -> None:
    """Clear all cached dependencies. Useful for testing."""
    _get_session_storage.cache_clear()
    _get_jinja_env.cache_clear()

    from portainer_dashboard.core.audit import reset_audit_logger
    from portainer_dashboard.core.event_bus import reset_event_bus
    from portainer_dashboard.core.ws_limiter import reset_ws_tracker
    from portainer_dashboard.core.oidc_state_store import reset_oidc_state_store

    reset_audit_logger()
    reset_event_bus()
    reset_ws_tracker()
    reset_oidc_state_store()


__all__ = [
    "JinjaEnvDep",
    "SessionStorageDep",
    "SettingsDep",
    "TemplateContextDep",
    "get_audit_logger_dep",
    "get_client_pool_dep",
    "get_event_bus_dep",
    "get_jinja_env",
    "get_session_storage",
    "get_settings_dep",
    "get_template_context",
    "reset_dependencies",
]
