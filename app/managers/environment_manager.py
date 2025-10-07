"""Session-agnostic helpers for managing Portainer environments."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, MutableMapping

from ..settings import PortainerEnvironment, get_configured_environments, load_environments, save_environments

StateMapping = MutableMapping[str, object]
EnvironmentList = list[dict[str, object]]


def _default_clear_cache(*, persistent: bool = True) -> None:  # pragma: no cover - placeholder
    """Fallback cache clearer used when none is provided.

    The ``persistent`` parameter is unused, but retained for interface
    compatibility with cache clearer implementations that distinguish between
    transient and persistent storage.
    """

    pass


@dataclass
class EnvironmentManager:
    """Coordinate persisted environments independently of Streamlit."""

    state: StateMapping
    clear_cache: Callable[..., None] = field(default=_default_clear_cache)
    loader: Callable[[], EnvironmentList] = field(default=load_environments)
    saver: Callable[[Iterable[dict[str, object]]], None] = field(default=save_environments)
    env_setter: Callable[[str, str], None] = field(default=os.environ.__setitem__)

    ENVIRONMENTS_KEY: str = "portainer_envs"
    SELECTED_ENV_KEY: str = "portainer_selected_env"
    APPLIED_ENV_KEY: str = "portainer_active_env_applied"

    def initialise(self) -> EnvironmentList:
        """Ensure environments and the active selection are initialised."""

        environments = self.ensure_environments_loaded()
        self.ensure_selection(environments)
        return environments

    def ensure_environments_loaded(self) -> EnvironmentList:
        """Load environments into the state mapping when missing."""

        if self.ENVIRONMENTS_KEY not in self.state:
            self.state[self.ENVIRONMENTS_KEY] = list(self.loader())
        value = self.state.get(self.ENVIRONMENTS_KEY, [])
        if not isinstance(value, list):
            value = list(value)
            self.state[self.ENVIRONMENTS_KEY] = value
        return list(value)

    def ensure_selection(self, environments: EnvironmentList | None = None) -> None:
        """Guarantee a default selection is available for downstream code."""

        if environments is None:
            environments = self.ensure_environments_loaded()
        if self.SELECTED_ENV_KEY in self.state:
            return
        if environments:
            default = str(environments[0].get("name", ""))
        else:
            default = ""
        self.state[self.SELECTED_ENV_KEY] = default

    def get_saved_environments(self) -> EnvironmentList:
        """Return a serialisable snapshot of the configured environments."""

        return list(self.ensure_environments_loaded())

    def set_saved_environments(self, environments: Iterable[dict[str, object]]) -> None:
        """Persist the provided environments to the session and disk."""

        serialisable = list(environments)
        self.state[self.ENVIRONMENTS_KEY] = serialisable
        self.saver(serialisable)

    def get_selected_environment_name(self) -> str:
        """Return the name of the currently selected environment."""

        selection = self.state.get(self.SELECTED_ENV_KEY, "")
        return str(selection)

    def set_active_environment(self, name: str) -> None:
        """Update the active environment selection and clear caches."""

        previous_selection = str(self.state.get(self.SELECTED_ENV_KEY, ""))
        self.state[self.SELECTED_ENV_KEY] = name
        self.state.pop(self.APPLIED_ENV_KEY, None)
        persistent = bool(previous_selection.strip())
        self.clear_cache(persistent=persistent)

    def apply_selected_environment(self) -> None:
        """Apply the selected environment and mark it as active."""

        selected = self.get_selected_environment_name()
        applied = self.state.get(self.APPLIED_ENV_KEY)
        if applied == selected:
            return
        environment = self._get_selected_environment()
        if environment is None:
            return
        self._set_environment_variables(environment)
        self.state[self.APPLIED_ENV_KEY] = selected

    def _get_selected_environment(self) -> dict[str, object] | None:
        selected_name = self.get_selected_environment_name()
        for environment in self.get_saved_environments():
            if environment.get("name") == selected_name:
                return environment
        return None

    def _set_environment_variables(self, environment: dict[str, object]) -> None:
        self.env_setter("PORTAINER_API_URL", str(environment.get("api_url", "")))
        self.env_setter("PORTAINER_API_KEY", str(environment.get("api_key", "")))
        verify_ssl = bool(environment.get("verify_ssl", True))
        self.env_setter("PORTAINER_VERIFY_SSL", "true" if verify_ssl else "false")
        name = environment.get("name")
        if name:
            self.env_setter("PORTAINER_ENVIRONMENT_NAME", str(name))

    @staticmethod
    def load_configured_environment_settings() -> tuple[PortainerEnvironment, ...]:
        """Expose the environment configuration loader for convenience."""

        return tuple(get_configured_environments())
