"""Central logging configuration for the Streamlit Portainer dashboard."""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)  # type: ignore[call-arg]


logging.Logger.trace = _trace  # type: ignore[attr-defined]

_LOG_LEVEL_ALIASES: dict[str, int] = {
    "trace": TRACE_LEVEL,
    "verbose": logging.DEBUG,
    "debug": logging.DEBUG,
    "information": logging.INFO,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_INITIALISED = False


class _MaxLevelFilter(logging.Filter):
    """Filter that allows log records up to ``max_level`` (inclusive)."""

    def __init__(self, max_level: int) -> None:
        super().__init__(name="")
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - inherited docstring
        return record.levelno <= self.max_level


def _resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    cleaned = level.strip().lower()
    if not cleaned:
        return logging.INFO
    if cleaned.isdigit():
        return int(cleaned)
    return _LOG_LEVEL_ALIASES.get(cleaned, logging.INFO)


def _build_handler(stream: Any, *, level: int) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def configure_logging(*, level: str | int | None = None, force: bool = False) -> None:
    """Configure structured console logging for the dashboard.

    The configuration prefers stdout for diagnostic output (TRACE, DEBUG, INFO,
    WARNING) while routing ERROR+ to stderr. The minimum log level can be
    overridden with ``DASHBOARD_LOG_LEVEL`` or by passing ``level``.
    """

    global _INITIALISED
    if _INITIALISED and not force:
        return

    requested_level: str | int = level if level is not None else os.getenv("DASHBOARD_LOG_LEVEL", "INFO")
    numeric_level = max(TRACE_LEVEL, _resolve_level(requested_level))

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.setLevel(numeric_level)

    stdout_handler = _build_handler(sys.stdout, level=TRACE_LEVEL)
    stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))

    stderr_handler = _build_handler(sys.stderr, level=logging.ERROR)

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)

    _INITIALISED = True

