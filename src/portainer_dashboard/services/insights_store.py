"""In-memory storage for monitoring insights and reports."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.monitoring import MonitoringInsight, MonitoringReport

LOGGER = logging.getLogger(__name__)


@dataclass
class InsightsStore:
    """Thread-safe in-memory store for monitoring insights and reports."""

    max_insights: int = 100
    max_reports: int = 50
    _insights: deque[MonitoringInsight] = field(init=False)
    _reports: deque[MonitoringReport] = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _subscribers: list[Callable] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._insights = deque(maxlen=self.max_insights)
        self._reports = deque(maxlen=self.max_reports)

    async def add_insight(self, insight: MonitoringInsight) -> None:
        """Add a new insight to the store and notify subscribers."""
        async with self._lock:
            self._insights.append(insight)
        LOGGER.debug("Added insight: %s", insight.title)
        await self._notify_subscribers("insight", insight)

    async def add_report(self, report: MonitoringReport) -> None:
        """Add a new report to the store and notify subscribers."""
        async with self._lock:
            self._reports.append(report)
            for insight in report.insights:
                self._insights.append(insight)
        LOGGER.info(
            "Added monitoring report with %d insights", len(report.insights)
        )
        await self._notify_subscribers("report", report)

    async def get_insights(
        self, limit: int | None = None, since: datetime | None = None
    ) -> list[MonitoringInsight]:
        """Get insights, optionally filtered by time and limited count."""
        async with self._lock:
            insights = list(self._insights)

        if since:
            insights = [i for i in insights if i.timestamp >= since]

        insights = sorted(insights, key=lambda x: x.timestamp, reverse=True)

        if limit:
            insights = insights[:limit]

        return insights

    async def get_reports(
        self, limit: int | None = None, since: datetime | None = None
    ) -> list[MonitoringReport]:
        """Get reports, optionally filtered by time and limited count."""
        async with self._lock:
            reports = list(self._reports)

        if since:
            reports = [r for r in reports if r.timestamp >= since]

        reports = sorted(reports, key=lambda x: x.timestamp, reverse=True)

        if limit:
            reports = reports[:limit]

        return reports

    async def get_latest_report(self) -> MonitoringReport | None:
        """Get the most recent monitoring report."""
        async with self._lock:
            if self._reports:
                return self._reports[-1]
            return None

    async def clear(self) -> None:
        """Clear all stored insights and reports."""
        async with self._lock:
            self._insights.clear()
            self._reports.clear()
        LOGGER.info("Cleared insights store")

    def subscribe(self, callback: Callable) -> None:
        """Subscribe to new insights/reports. Callback receives (event_type, data)."""
        self._subscribers.append(callback)
        LOGGER.debug("New subscriber added, total: %d", len(self._subscribers))

    def unsubscribe(self, callback: Callable) -> None:
        """Unsubscribe from notifications."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            LOGGER.debug("Subscriber removed, remaining: %d", len(self._subscribers))

    async def _notify_subscribers(
        self, event_type: str, data: MonitoringInsight | MonitoringReport
    ) -> None:
        """Notify all subscribers of a new event."""
        for callback in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, data)
                else:
                    callback(event_type, data)
            except Exception as exc:
                LOGGER.warning("Subscriber callback failed: %s", exc)


_store_instance: InsightsStore | None = None
_store_lock = asyncio.Lock()


async def get_insights_store() -> InsightsStore:
    """Get or create the singleton insights store instance."""
    global _store_instance
    async with _store_lock:
        if _store_instance is None:
            settings = get_settings()
            _store_instance = InsightsStore(
                max_insights=settings.monitoring.max_insights_stored,
                max_reports=50,
            )
            LOGGER.info("Created insights store with max %d insights", settings.monitoring.max_insights_stored)
        return _store_instance


def reset_insights_store() -> None:
    """Reset the insights store singleton. Useful for testing."""
    global _store_instance
    _store_instance = None


__all__ = [
    "InsightsStore",
    "get_insights_store",
    "reset_insights_store",
]
