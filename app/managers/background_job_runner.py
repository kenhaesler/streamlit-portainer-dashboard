"""Background orchestration helpers for Streamlit-agnostic usage."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from ..services.backup_scheduler import maybe_run_scheduled_backups


class BackgroundJobRunner:
    """Encapsulate execution of background jobs with defensive guards."""

    def __init__(
        self,
        *,
        backup_runner: Callable[[Iterable[dict[str, object]]], None] = maybe_run_scheduled_backups,
        logger: logging.Logger | None = None,
    ) -> None:
        self._backup_runner = backup_runner
        self._logger = logger or logging.getLogger(__name__)

    def maybe_run_backups(self, environments: Iterable[dict[str, object]]) -> None:
        """Execute the scheduled backup runner with defensive logging."""

        try:
            self._backup_runner(environments)
        except Exception:  # pragma: no cover - protective guard
            self._logger.warning("Scheduled backup execution failed", exc_info=True)
