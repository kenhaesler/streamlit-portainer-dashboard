"""Logging helpers for the Streamlit Portainer dashboard."""
from __future__ import annotations

import logging
import os
import sys

try:  # pragma: no cover - Streamlit not available during some tests
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - allows unit tests without Streamlit
    st = None  # type: ignore[assignment]

__all__ = ["setup_logging"]


class _SessionUserFilter(logging.Filter):
    """Attach the active Streamlit username to log records."""

    _default_username = "-"

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - trivial
        record.user = self._resolve_username()
        return True

    @staticmethod
    def _resolve_username() -> str:
        if st is None:
            return _SessionUserFilter._default_username
        try:
            username = st.session_state.get("authenticated_username")
        except Exception:  # pragma: no cover - defensive guard for Streamlit runtime
            return _SessionUserFilter._default_username
        if not username:
            return _SessionUserFilter._default_username
        return str(username)


_CONFIGURED = False


def setup_logging() -> None:
    """Configure application logging for container-friendly output."""

    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("PORTAINER_DASHBOARD_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.INFO

    log_format = os.getenv(
        "PORTAINER_DASHBOARD_LOG_FORMAT",
        "%(asctime)s | %(levelname)s | %(name)s | user=%(user)s | %(message)s",
    )

    user_filter = _SessionUserFilter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format))
    handler.addFilter(user_filter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    root_logger.addFilter(user_filter)

    _CONFIGURED = True

