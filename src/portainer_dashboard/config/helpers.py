"""Configuration helper functions and constants."""

from __future__ import annotations

from pathlib import Path


def _empty_str_to_none(v: str | None) -> str | None:
    """Convert empty strings to None so Pydantic uses field defaults."""
    if v == "":
        return None
    return v


def _empty_str_to_default_bool(v: str | bool | None, default: bool) -> bool:
    """Convert empty strings to default bool value."""
    if v == "" or v is None:
        return default
    if isinstance(v, bool):
        return v
    # Handle string boolean values
    return v.lower() in {"true", "1", "yes", "on"}


def _empty_str_to_default_int(v: str | int | None, default: int) -> int:
    """Convert empty strings to default int value."""
    if v == "" or v is None:
        return default
    if isinstance(v, int):
        return v
    return int(v)


class ConfigurationError(RuntimeError):
    """Raised when dashboard configuration is invalid."""


def _project_root() -> Path:
    """Return the project root directory."""
    try:
        return Path(__file__).resolve().parents[3]
    except IndexError:
        return Path.cwd()


PROJECT_ROOT = _project_root()
