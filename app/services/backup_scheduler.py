"""Helpers for scheduling recurring Portainer backups."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence

try:  # pragma: no cover - import shim for Streamlit runtime
    from ..file_locking import FileLock, Timeout  # type: ignore[import-not-found]
except (ModuleNotFoundError, ImportError):  # pragma: no cover - fallback when executed as a script
    from file_locking import FileLock, Timeout  # type: ignore[no-redef]

from .backup import (
    backup_directory,
    create_environment_backup,
    default_backup_password,
)
from ..settings import load_environments

__all__ = [
    "BackupHistoryEntry",
    "ScheduleSnapshot",
    "configured_interval_seconds",
    "ensure_scheduler_running",
    "get_schedule_snapshot",
    "maybe_run_scheduled_backups",
    "schedule_state_path",
    "update_schedule_interval",
]


LOGGER = logging.getLogger(__name__)

_INTERVAL_ENV_VAR = "PORTAINER_BACKUP_INTERVAL"
_SCHEDULE_FILENAME = "schedule.json"
_DISABLE_VALUES = {"0", "false", "no", "off", "never", "none"}
_UNIT_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86_400}
_DEFAULT_INTERVAL_UNIT = "h"
_SCHEDULE_LOCK_SUFFIX = ".lock"
_SCHEDULE_LOCK_TIMEOUT_SECONDS = 10.0
_SCHEDULER_THREAD_LOCK = threading.Lock()
_SCHEDULER_THREAD: threading.Thread | None = None
_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_WAKE_EVENT = threading.Event()
_DEFAULT_NEXT_RUN_DELAY_SECONDS = 300.0
_LOCK_CONTENTION_BACKOFF_SECONDS = 60.0
_MIN_SCHEDULER_SLEEP_SECONDS = 1.0
_MAX_SCHEDULER_SLEEP_SECONDS = 3600.0
_SCHEDULER_CATCHUP_SLEEP_SECONDS = 15.0


@dataclass(frozen=True)
class BackupHistoryEntry:
    """Represents a single scheduled backup execution."""

    completed_at: _dt.datetime
    generated_paths: tuple[Path, ...]
    errors: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.errors and self.generated_paths:
            return "partial"
        if self.errors:
            return "failed"
        if self.generated_paths:
            return "completed"
        return "skipped"


@dataclass
class _ScheduleState:
    next_run: _dt.datetime | None
    interval_seconds: int
    history: list[BackupHistoryEntry]


@dataclass(frozen=True)
class ScheduleSnapshot:
    """Current persisted scheduler configuration."""

    interval_seconds: int
    next_run: _dt.datetime | None
    history: tuple[BackupHistoryEntry, ...]
    managed_by_env: bool
    env_value: str | None
    env_parse_error: str | None


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _parse_interval(raw_value: str | None) -> tuple[int, str | None]:
    if raw_value is None:
        return 0, None
    cleaned = raw_value.strip()
    if not cleaned:
        return 0, None
    lowered = cleaned.lower()
    if lowered in _DISABLE_VALUES:
        return 0, None
    match = re.fullmatch(r"(\d+)([smhdSMHD]?)", cleaned)
    if not match:
        message = (
            f"Invalid value for {_INTERVAL_ENV_VAR}: {raw_value!r}. "
            "Disabling scheduled backups."
        )
        LOGGER.warning(message)
        return 0, message
    amount = int(match.group(1))
    suffix = match.group(2).lower() if match.group(2) else _DEFAULT_INTERVAL_UNIT
    multiplier = _UNIT_MULTIPLIERS.get(suffix)
    if multiplier is None:
        message = (
            f"Unsupported interval unit {suffix!r} for {_INTERVAL_ENV_VAR}. "
            "Disabling scheduled backups."
        )
        LOGGER.warning(message)
        return 0, message
    interval = amount * multiplier
    if interval <= 0:
        message = (
            f"Interval from {_INTERVAL_ENV_VAR} must be greater than zero seconds."
        )
        LOGGER.warning(message)
        return 0, message
    return interval, None


def _env_interval_metadata() -> tuple[int, str | None, str | None]:
    raw_value = os.getenv(_INTERVAL_ENV_VAR)
    interval, error = _parse_interval(raw_value)
    return interval, raw_value, error


def configured_interval_seconds() -> int:
    """Return the configured backup interval in seconds (0 when disabled)."""

    with _acquire_schedule_lock():
        state = _load_schedule_unlocked()
        env_interval, env_value, _ = _env_interval_metadata()

        if env_value is not None:
            history = list(state.history if state else [])
            if env_interval <= 0:
                _store_schedule_unlocked(
                    _ScheduleState(next_run=None, interval_seconds=0, history=history)
                )
                _notify_scheduler()
                return 0
            if state is None or env_interval != state.interval_seconds:
                next_run = _advance_schedule(_utcnow(), env_interval)
                _store_schedule_unlocked(
                    _ScheduleState(
                        next_run=next_run,
                        interval_seconds=env_interval,
                        history=history,
                    )
                )
                _notify_scheduler()
            return env_interval

        if state is not None:
            return state.interval_seconds
        return env_interval


def schedule_state_path() -> Path:
    """Return the filesystem path used to persist the backup schedule."""

    return backup_directory() / _SCHEDULE_FILENAME


def _schedule_lock_path() -> Path:
    path = schedule_state_path()
    return path.with_suffix(f"{path.suffix}{_SCHEDULE_LOCK_SUFFIX}")


@contextmanager
def _acquire_schedule_lock(timeout: float = _SCHEDULE_LOCK_TIMEOUT_SECONDS):
    lock_path = _schedule_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path))
    acquired = False
    try:
        lock.acquire(timeout=timeout)
        acquired = True
        yield
    except Timeout:
        LOGGER.warning("Timeout acquiring backup schedule lock at %s", lock_path)
        raise
    finally:
        if acquired:
            try:
                lock.release()
            except RuntimeError:
                LOGGER.debug("Backup schedule lock already released: %s", lock_path)


def _load_schedule_unlocked() -> _ScheduleState | None:
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
    raw_next_run = payload.get("next_run")
    interval = payload.get("interval_seconds")
    history_payload = payload.get("history", [])
    if not isinstance(interval, int):
        return None
    if raw_next_run in (None, ""):
        next_run_dt: _dt.datetime | None = None
    elif isinstance(raw_next_run, (int, float)):
        try:
            next_run_dt = _dt.datetime.fromtimestamp(
                float(raw_next_run), tz=_dt.timezone.utc
            )
        except (OverflowError, OSError, ValueError):
            next_run_dt = None
    else:
        next_run_dt = None

    history: list[BackupHistoryEntry] = []
    if isinstance(history_payload, list):
        for entry in history_payload:
            if not isinstance(entry, dict):
                continue
            completed_at_raw = entry.get("completed_at")
            if not isinstance(completed_at_raw, (int, float)):
                continue
            try:
                completed_at = _dt.datetime.fromtimestamp(
                    float(completed_at_raw), tz=_dt.timezone.utc
                )
            except (OverflowError, OSError, ValueError):
                continue
            generated_raw = entry.get("generated", [])
            if isinstance(generated_raw, (list, tuple)):
                generated = tuple(Path(str(value)) for value in generated_raw)
            else:
                generated = tuple()
            errors_raw = entry.get("errors", [])
            if isinstance(errors_raw, (list, tuple)):
                errors = tuple(str(value) for value in errors_raw if value is not None)
            else:
                errors = tuple()
            history.append(
                BackupHistoryEntry(
                    completed_at=completed_at,
                    generated_paths=generated,
                    errors=errors,
                )
            )

    return _ScheduleState(
        next_run=next_run_dt,
        interval_seconds=interval,
        history=history,
    )


def _store_schedule_unlocked(state: _ScheduleState) -> None:
    path = schedule_state_path()
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "next_run": state.next_run.timestamp() if state.next_run else None,
        "interval_seconds": state.interval_seconds,
        "history": [
            {
                "completed_at": entry.completed_at.timestamp(),
                "generated": [str(path) for path in entry.generated_paths],
                "errors": list(entry.errors),
            }
            for entry in state.history
        ],
    }
    try:
        path.write_text(json.dumps(payload), "utf-8")
    except OSError as exc:
        LOGGER.warning("Unable to persist backup schedule %s: %s", path, exc)


def _clear_schedule() -> None:
    with _acquire_schedule_lock():
        _store_schedule_unlocked(
            _ScheduleState(next_run=None, interval_seconds=0, history=[])
        )
    _notify_scheduler()


def _notify_scheduler() -> None:
    _SCHEDULER_WAKE_EVENT.set()


def _advance_schedule(now: _dt.datetime, interval_seconds: int) -> _dt.datetime:
    delta = _dt.timedelta(seconds=interval_seconds)
    next_run = now + delta
    return next_run


def _roll_forward(
    now: _dt.datetime,
    *,
    interval_seconds: int,
    previous_next_run: _dt.datetime | None,
) -> _dt.datetime:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    delta = _dt.timedelta(seconds=interval_seconds)
    next_run = previous_next_run or now
    while next_run <= now:
        next_run += delta
    return next_run


def _with_history(
    history: Sequence[BackupHistoryEntry],
    entry: BackupHistoryEntry,
    *,
    limit: int = 10,
) -> list[BackupHistoryEntry]:
    combined = [entry, *history]
    return combined[:limit]


def get_schedule_snapshot() -> ScheduleSnapshot:
    """Return the persisted scheduler state for display in the UI."""

    configured_interval_seconds()
    with _acquire_schedule_lock():
        state = _load_schedule_unlocked()
        env_interval, env_value, env_error = _env_interval_metadata()
        managed_by_env = env_value is not None

        if state is None:
            interval = env_interval if env_interval > 0 else 0
            next_run = None
            history: tuple[BackupHistoryEntry, ...] = tuple()
        else:
            interval = state.interval_seconds
            next_run = state.next_run
            history = tuple(state.history)

    return ScheduleSnapshot(
        interval_seconds=interval,
        next_run=next_run,
        history=history,
        managed_by_env=managed_by_env,
        env_value=env_value,
        env_parse_error=env_error,
    )


def update_schedule_interval(interval_seconds: int) -> ScheduleSnapshot:
    """Persist a new scheduler interval and return the updated snapshot."""

    _, env_value, _ = _env_interval_metadata()
    if env_value is not None:
        raise RuntimeError(
            "Scheduled backups are managed via the "
            f"{_INTERVAL_ENV_VAR} environment variable."
        )

    interval_seconds = max(int(interval_seconds), 0)

    with _acquire_schedule_lock():
        existing = _load_schedule_unlocked()
        history = list(existing.history if existing else [])

        if interval_seconds <= 0:
            state = _ScheduleState(next_run=None, interval_seconds=0, history=history)
            _store_schedule_unlocked(state)
            snapshot = ScheduleSnapshot(
                interval_seconds=0,
                next_run=None,
                history=tuple(history),
                managed_by_env=False,
                env_value=None,
                env_parse_error=None,
            )
        else:
            now = _utcnow()
            next_run = _advance_schedule(now, interval_seconds)
            state = _ScheduleState(
                next_run=next_run, interval_seconds=interval_seconds, history=history
            )
            _store_schedule_unlocked(state)
            snapshot = ScheduleSnapshot(
                interval_seconds=interval_seconds,
                next_run=next_run,
                history=tuple(history),
                managed_by_env=False,
                env_value=None,
                env_parse_error=None,
            )

    _notify_scheduler()
    return snapshot


def maybe_run_scheduled_backups(
    environments: Iterable[Mapping[str, object]],
) -> list[Path]:
    """Create backups when the configured schedule is due.

    Parameters
    ----------
    environments:
        Iterable of saved Portainer environment configurations. Backups are
        attempted for each entry when the schedule triggers.
    """

    interval_seconds = configured_interval_seconds()
    envs_list = list(environments)

    schedule_updated = False
    result: list[Path] = []

    try:
        with _acquire_schedule_lock():
            current_state = _load_schedule_unlocked()
            history = list(current_state.history if current_state else [])

            if interval_seconds <= 0:
                if (
                    current_state is None
                    or current_state.interval_seconds != 0
                    or current_state.next_run is not None
                ):
                    _store_schedule_unlocked(
                        _ScheduleState(
                            next_run=None, interval_seconds=0, history=history
                        )
                    )
                    schedule_updated = True
                LOGGER.info("Scheduled backup run skipped because the schedule is disabled")
                return []

            now = _utcnow()

            if (
                current_state is None
                or current_state.interval_seconds != interval_seconds
            ):
                next_run = _advance_schedule(now, interval_seconds)
                _store_schedule_unlocked(
                    _ScheduleState(
                        next_run=next_run,
                        interval_seconds=interval_seconds,
                        history=history,
                    )
                )
                schedule_updated = True
                LOGGER.info(
                    "Initialised scheduled backups at %s second interval", interval_seconds
                )
                return []

            if not envs_list:
                if current_state.next_run is None or now >= current_state.next_run:
                    next_run = _roll_forward(
                        now,
                        interval_seconds=interval_seconds,
                        previous_next_run=current_state.next_run,
                    )
                    _store_schedule_unlocked(
                        _ScheduleState(
                            next_run=next_run,
                            interval_seconds=interval_seconds,
                            history=history,
                        )
                    )
                    schedule_updated = True
                LOGGER.info(
                    "Scheduled backup run skipped because no environments are configured"
                )
                return []

            if current_state.next_run is not None and now < current_state.next_run:
                LOGGER.info(
                    "Scheduled backup run skipped; next run at %s", current_state.next_run
                )
                return []

            generated: list[Path] = []
            errors: list[str] = []
            password = default_backup_password()
            for environment in envs_list:
                try:
                    kwargs = {"password": password} if password else {}
                    path = create_environment_backup(environment, **kwargs)
                except Exception as exc:  # pragma: no cover - defensive guard
                    env_name = str(environment.get("name", "environment"))
                    LOGGER.warning(
                        "Scheduled backup failed for %s (error type: %s)",
                        env_name,
                        type(exc).__name__,
                    )
                    errors.append(f"{env_name}: {exc}")
                    continue
                generated.append(path)

            completion_time = _utcnow()
            if generated or errors:
                history = _with_history(
                    history,
                    BackupHistoryEntry(
                        completed_at=completion_time,
                        generated_paths=tuple(generated),
                        errors=tuple(errors),
                    ),
                )

            next_run = _roll_forward(
                now,
                interval_seconds=interval_seconds,
                previous_next_run=current_state.next_run,
            )
            _store_schedule_unlocked(
                _ScheduleState(
                    next_run=next_run,
                    interval_seconds=interval_seconds,
                    history=list(history),
                )
            )
            schedule_updated = True

            if errors and generated:
                LOGGER.info(
                    "Scheduled backup completed with %d archive(s) and %d error(s)",
                    len(generated),
                    len(errors),
                )
            elif errors:
                LOGGER.info(
                    "Scheduled backup completed with %d error(s) and no archives",
                    len(errors),
                )
            elif generated:
                LOGGER.info(
                    "Scheduled backup created %d archive(s)",
                    len(generated),
                )
            else:
                LOGGER.info("Scheduled backup completed without generating archives")

            result = generated
    except Timeout:
        LOGGER.warning(
            "Skipping scheduled backup run because another worker holds the lock"
        )
        return []
    finally:
        if schedule_updated:
            _notify_scheduler()

    return result


def _seconds_until_next_run() -> float:
    try:
        with _acquire_schedule_lock():
            state = _load_schedule_unlocked()
            if state is None or state.next_run is None:
                return _DEFAULT_NEXT_RUN_DELAY_SECONDS
            remaining = (state.next_run - _utcnow()).total_seconds()
            if remaining <= 0:
                return 0.0
            return remaining
    except Timeout:
        LOGGER.warning(
            "Unable to evaluate next scheduled backup time due to lock contention"
        )
        return _LOCK_CONTENTION_BACKOFF_SECONDS


def _scheduler_loop() -> None:
    LOGGER.info("Scheduled backup runner thread started")
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            try:
                environments = list(load_environments())
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.warning(
                    "Unable to load environments for scheduled backups: %s",
                    exc,
                    exc_info=True,
                )
                environments = []
            maybe_run_scheduled_backups(environments)
        except Exception:  # pragma: no cover - defensive guard
            LOGGER.exception("Scheduled backup runner encountered an unexpected error")
        delay = _seconds_until_next_run()
        delay = (
            max(_MIN_SCHEDULER_SLEEP_SECONDS, min(delay, _MAX_SCHEDULER_SLEEP_SECONDS))
            if delay > 0
            else _SCHEDULER_CATCHUP_SLEEP_SECONDS
        )
        _SCHEDULER_WAKE_EVENT.clear()
        awakened = _SCHEDULER_WAKE_EVENT.wait(timeout=delay)
        if _SCHEDULER_STOP_EVENT.is_set():
            break
        if awakened:
            _SCHEDULER_WAKE_EVENT.clear()
    LOGGER.info("Scheduled backup runner thread stopping")


def ensure_scheduler_running() -> None:
    """Start the background scheduler thread when it is not already running."""

    global _SCHEDULER_THREAD

    with _SCHEDULER_THREAD_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_STOP_EVENT.clear()
        _SCHEDULER_WAKE_EVENT.set()
        thread = threading.Thread(
            target=_scheduler_loop,
            name="portainer-scheduled-backups",
            daemon=True,
        )
        thread.start()
        _SCHEDULER_THREAD = thread
        LOGGER.info("Started scheduled backup runner thread")
