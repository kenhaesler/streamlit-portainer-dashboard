"""Helpers for scheduling recurring Portainer backups."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping

from .backup import (
    backup_directory,
    create_environment_backup,
    default_backup_password,
)

__all__ = [
    "configured_interval_seconds",
    "maybe_run_scheduled_backups",
    "schedule_state_path",
]


LOGGER = logging.getLogger(__name__)

_INTERVAL_ENV_VAR = "PORTAINER_BACKUP_INTERVAL"
_SCHEDULE_FILENAME = "schedule.json"
_DISABLE_VALUES = {"0", "false", "no", "off", "never", "none"}
_UNIT_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86_400}
_DEFAULT_INTERVAL_UNIT = "h"


@dataclass
class _ScheduleState:
    next_run: _dt.datetime
    interval_seconds: int


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _parse_interval(raw_value: str | None) -> int:
    if raw_value is None:
        return 0
    cleaned = raw_value.strip()
    if not cleaned:
        return 0
    lowered = cleaned.lower()
    if lowered in _DISABLE_VALUES:
        return 0
    match = re.fullmatch(r"(\d+)([smhdSMHD]?)", cleaned)
    if not match:
        LOGGER.warning(
            "Invalid value for %s: %s. Disabling scheduled backups.",
            _INTERVAL_ENV_VAR,
            raw_value,
        )
        return 0
    amount = int(match.group(1))
    suffix = match.group(2).lower() if match.group(2) else _DEFAULT_INTERVAL_UNIT
    multiplier = _UNIT_MULTIPLIERS.get(suffix)
    if multiplier is None:
        LOGGER.warning(
            "Unsupported interval unit %s for %s. Disabling scheduled backups.",
            suffix,
            _INTERVAL_ENV_VAR,
        )
        return 0
    interval = amount * multiplier
    if interval <= 0:
        return 0
    return interval


def configured_interval_seconds() -> int:
    """Return the configured backup interval in seconds (0 when disabled)."""

    return _parse_interval(os.getenv(_INTERVAL_ENV_VAR))


def schedule_state_path() -> Path:
    """Return the filesystem path used to persist the backup schedule."""

    return backup_directory() / _SCHEDULE_FILENAME


def _load_schedule() -> _ScheduleState | None:
    path = schedule_state_path()
    try:
        payload = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        LOGGER.warning("Unable to read backup schedule at %s: %s", path, exc)
        return None
    except json.JSONDecodeError:
        LOGGER.warning("Corrupted backup schedule at %s. Resetting.", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None
    next_run = payload.get("next_run")
    interval = payload.get("interval_seconds")
    if not isinstance(next_run, (int, float)) or not isinstance(interval, int):
        return None
    try:
        next_run_dt = _dt.datetime.fromtimestamp(float(next_run), tz=_dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return _ScheduleState(next_run=next_run_dt, interval_seconds=interval)


def _store_schedule(state: _ScheduleState) -> None:
    path = schedule_state_path()
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "next_run": state.next_run.timestamp(),
        "interval_seconds": state.interval_seconds,
    }
    try:
        path.write_text(json.dumps(payload), "utf-8")
    except OSError as exc:
        LOGGER.warning("Unable to persist backup schedule %s: %s", path, exc)


def _clear_schedule() -> None:
    path = schedule_state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        LOGGER.warning("Unable to remove backup schedule %s: %s", path, exc)


def _advance_schedule(now: _dt.datetime, interval_seconds: int) -> _dt.datetime:
    delta = _dt.timedelta(seconds=interval_seconds)
    next_run = now + delta
    return next_run


def maybe_run_scheduled_backups(
    environments: Iterable[Mapping[str, object]]
) -> List[Path]:
    """Create backups when the configured schedule is due.

    Parameters
    ----------
    environments:
        Iterable of saved Portainer environment configurations. Backups are
        attempted for each entry when the schedule triggers.
    """

    interval_seconds = configured_interval_seconds()
    if interval_seconds <= 0:
        _clear_schedule()
        return []

    envs = list(environments)
    now = _utcnow()
    schedule = _load_schedule()
    if schedule is None or schedule.interval_seconds != interval_seconds:
        next_run = _advance_schedule(now, interval_seconds)
        _store_schedule(_ScheduleState(next_run=next_run, interval_seconds=interval_seconds))
        return []

    if not envs:
        if now >= schedule.next_run:
            next_run = _advance_schedule(now, interval_seconds)
            _store_schedule(
                _ScheduleState(next_run=next_run, interval_seconds=interval_seconds)
            )
        return []

    if now < schedule.next_run:
        return []

    generated: List[Path] = []
    password = default_backup_password()
    for environment in envs:
        try:
            kwargs = {"password": password} if password else {}
            path = create_environment_backup(environment, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive guard
            env_name = str(environment.get("name", "environment"))
            LOGGER.warning(
                "Scheduled backup failed for %s: %s", env_name, exc, exc_info=True
            )
            continue
        generated.append(path)

    next_run = schedule.next_run
    delta = _dt.timedelta(seconds=interval_seconds)
    while next_run <= now:
        next_run += delta
    _store_schedule(_ScheduleState(next_run=next_run, interval_seconds=interval_seconds))
    return generated
