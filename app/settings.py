"""Application settings helpers for Portainer environments."""
from __future__ import annotations

import errno
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any

__all__ = [
    "PortainerEnvironment",
    "get_configured_environments",
    "load_environments",
    "save_environments",
]


@dataclass(frozen=True)
class PortainerEnvironment:
    """Configuration for a single Portainer environment."""

    name: str
    api_url: str
    api_key: str
    verify_ssl: bool = True


_FALSEY_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    """Parse a boolean value from an environment variable string."""

    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned.lower() not in _FALSEY_VALUES


def _normalise_key(name: str) -> str:
    return name.upper().replace(" ", "_")


def _build_environment(name: str, *, prefix: str | None = None) -> PortainerEnvironment:
    key_prefix = prefix or _normalise_key(name)
    api_url = os.getenv(f"PORTAINER_{key_prefix}_API_URL", "").strip()
    api_key = os.getenv(f"PORTAINER_{key_prefix}_API_KEY", "").strip()
    verify_ssl = _parse_bool(
        os.getenv(f"PORTAINER_{key_prefix}_VERIFY_SSL"),
        default=True,
    )
    if not api_url or not api_key:
        raise ValueError(
            f"Configuration for environment '{name}' is incomplete: "
            "missing API URL or API key."
        )
    return PortainerEnvironment(
        name=name,
        api_url=api_url,
        api_key=api_key,
        verify_ssl=verify_ssl,
    )


def get_configured_environments() -> list[PortainerEnvironment]:
    """Return all configured Portainer environments from environment variables."""

    configured: list[PortainerEnvironment] = []
    raw_environments = os.getenv("PORTAINER_ENVIRONMENTS", "").strip()
    if raw_environments:
        names: Iterable[str] = (
            name.strip() for name in raw_environments.split(",") if name.strip()
        )
        for name in names:
            key_prefix = _normalise_key(name)
            configured.append(_build_environment(name, prefix=key_prefix))
        return configured

    api_url = os.getenv("PORTAINER_API_URL", "").strip()
    api_key = os.getenv("PORTAINER_API_KEY", "").strip()
    if api_url and api_key:
        default_name = os.getenv("PORTAINER_ENVIRONMENT_NAME", "Default")
        verify_ssl = _parse_bool(os.getenv("PORTAINER_VERIFY_SSL"), default=True)
        configured.append(
            PortainerEnvironment(
                name=default_name,
                api_url=api_url,
                api_key=api_key,
                verify_ssl=verify_ssl,
            )
        )
    return configured


_PERMISSION_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}


def _config_path_candidates() -> list[Path]:
    """Return the ordered list of potential locations for the config file."""

    candidates: list[Path] = []
    override_file = os.getenv("PORTAINER_ENVIRONMENTS_PATH")
    if override_file:
        candidates.append(Path(override_file).expanduser())

    override_dir = os.getenv("PORTAINER_ENVIRONMENTS_DIR")
    if override_dir:
        candidates.append(Path(override_dir).expanduser() / "portainer_environments.json")

    repo_default = (
        Path(__file__).resolve().parent.parent / ".streamlit" / "portainer_environments.json"
    )
    candidates.append(repo_default)

    home_default = Path.home() / ".streamlit" / "portainer_environments.json"
    candidates.append(home_default)

    tmp_default = (
        Path(tempfile.gettempdir())
        / "streamlit-portainer-dashboard"
        / "portainer_environments.json"
    )
    candidates.append(tmp_default)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        expanded = candidate.expanduser()
        key = str(expanded)
        if key in seen:
            continue
        seen.add(key)
        unique.append(expanded)
    return unique


def _initial_config_path(candidates: list[Path]) -> Path:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return candidates[0]


_CONFIG_CANDIDATES = _config_path_candidates()
CONFIG_PATH = _initial_config_path(_CONFIG_CANDIDATES)


def _update_config_path(path: Path) -> None:
    global CONFIG_PATH
    CONFIG_PATH = path


def _current_config_path() -> Path:
    try:
        if CONFIG_PATH.exists():
            return CONFIG_PATH
    except OSError:
        pass
    for candidate in _CONFIG_CANDIDATES:
        try:
            if candidate.exists():
                _update_config_path(candidate)
                return candidate
        except OSError:
            continue
    return CONFIG_PATH


def _coerce_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def load_environments() -> list[dict[str, Any]]:
    """Load saved Portainer environments from disk."""

    path = _current_config_path()
    try:
        if not path.exists():
            return []
    except OSError:
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    environments: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        environments.append(
            {
                "name": str(item.get("name", "")).strip(),
                "api_url": str(item.get("api_url", "")).strip(),
                "api_key": str(item.get("api_key", "")).strip(),
                "verify_ssl": _coerce_bool(item.get("verify_ssl"), default=True),
            }
        )
    return environments


def save_environments(environments: Iterable[dict[str, Any]]) -> None:
    """Persist the provided environments to disk."""

    serialisable: list[dict[str, Any]] = []
    for env in environments:
        if not isinstance(env, dict):
            continue
        serialisable.append(
            {
                "name": str(env.get("name", "")).strip(),
                "api_url": str(env.get("api_url", "")).strip(),
                "api_key": str(env.get("api_key", "")).strip(),
                "verify_ssl": _coerce_bool(env.get("verify_ssl"), default=True),
            }
        )
    last_error: OSError | None = None
    payload = json.dumps(serialisable, indent=2)
    for candidate in _CONFIG_CANDIDATES:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            last_error = error
            continue
        try:
            candidate.write_text(payload, "utf-8")
        except OSError as error:
            if error.errno in _PERMISSION_ERRNOS or error.errno is None:
                last_error = error
                continue
            raise
        else:
            _update_config_path(candidate)
            return
    if last_error is not None:
        raise PermissionError(
            "Unable to persist Portainer environments to any configured location."
        ) from last_error
    raise PermissionError(
        "Unable to determine a writable location for Portainer environments."
    )
