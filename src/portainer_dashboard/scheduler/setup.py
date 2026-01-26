"""APScheduler configuration for periodic monitoring."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from portainer_dashboard.config import get_settings
from portainer_dashboard.services.monitoring_service import (
    MonitoringService,
    create_monitoring_service,
)
from portainer_dashboard.websocket.monitoring_insights import broadcast_report

if TYPE_CHECKING:
    from portainer_dashboard.models.monitoring import MonitoringReport

LOGGER = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_monitoring_service: MonitoringService | None = None


async def _refresh_cache_job() -> None:
    """Refresh the Portainer cache in the background."""
    from portainer_dashboard.services.cache_service import get_cache_service

    settings = get_settings()
    if not settings.cache.enabled:
        return

    try:
        cache_service = get_cache_service()
        results = await cache_service.refresh_cache()
        LOGGER.debug("Cache refresh completed: %s", results)
    except Exception as exc:
        LOGGER.warning("Cache refresh failed: %s", exc)


async def _purge_old_metrics() -> None:
    """Purge old metrics and traces based on retention settings."""
    settings = get_settings()

    if settings.metrics.enabled:
        try:
            from portainer_dashboard.services.metrics_store import get_metrics_store
            store = await get_metrics_store()
            deleted = store.purge_old_metrics(settings.metrics.retention_hours)
            if deleted > 0:
                LOGGER.info("Purged %d old metrics", deleted)
        except Exception as exc:
            LOGGER.warning("Failed to purge old metrics: %s", exc)

    if settings.tracing.enabled:
        try:
            from portainer_dashboard.services.trace_store import get_trace_store
            store = await get_trace_store()
            deleted = store.purge_old_traces(settings.tracing.retention_hours)
            if deleted > 0:
                LOGGER.info("Purged %d old traces", deleted)
        except Exception as exc:
            LOGGER.warning("Failed to purge old traces: %s", exc)

    if settings.remediation.enabled:
        try:
            from portainer_dashboard.services.actions_store import get_actions_store
            store = await get_actions_store()
            deleted = store.purge_old_actions(days=30)
            if deleted > 0:
                LOGGER.info("Purged %d old actions", deleted)
        except Exception as exc:
            LOGGER.warning("Failed to purge old actions: %s", exc)


async def _run_monitoring_job() -> None:
    """Execute the monitoring analysis job."""
    global _monitoring_service

    if _monitoring_service is None:
        LOGGER.warning("Monitoring service not initialized")
        return

    try:
        report = await _monitoring_service.run_analysis()
        LOGGER.debug("Monitoring job completed with %d insights", len(report.insights))
    except Exception as exc:
        LOGGER.exception("Monitoring job failed: %s", exc)


async def _broadcast_wrapper(report: "MonitoringReport") -> None:
    """Wrapper to broadcast reports via WebSocket."""
    try:
        await broadcast_report(report)
    except Exception as exc:
        LOGGER.warning("Failed to broadcast monitoring report: %s", exc)


async def create_scheduler() -> AsyncIOScheduler | None:
    """Create and configure the scheduler for monitoring jobs.

    Returns None if monitoring is disabled and caching is disabled.
    """
    global _scheduler, _monitoring_service

    settings = get_settings()

    # Check if we need to create a scheduler at all
    if not settings.monitoring.enabled and not settings.cache.enabled:
        LOGGER.info("AI monitoring and caching are disabled, no scheduler needed")
        return None

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        }
    )

    # Add AI monitoring job if enabled
    if settings.monitoring.enabled:
        _monitoring_service = await create_monitoring_service(
            broadcast_callback=_broadcast_wrapper
        )

        interval_minutes = settings.monitoring.interval_minutes
        if interval_minutes < 1:
            interval_minutes = 1

        _scheduler.add_job(
            _run_monitoring_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="ai_monitoring",
            name="AI Infrastructure Monitoring",
            replace_existing=True,
        )

        LOGGER.info(
            "Scheduled AI monitoring analysis every %d minutes",
            interval_minutes,
        )

    # Add cache refresh job if caching is enabled
    if settings.cache.enabled:
        # Refresh cache at half the TTL interval to ensure data is always fresh
        cache_ttl = settings.cache.ttl_seconds
        # Minimum 1 minute, maximum half the TTL (at least refresh before expiry)
        refresh_seconds = max(60, min(cache_ttl // 2, 300))  # Cap at 5 minutes

        _scheduler.add_job(
            _refresh_cache_job,
            trigger=IntervalTrigger(seconds=refresh_seconds),
            id="cache_refresh",
            name="Portainer Cache Refresh",
            replace_existing=True,
        )

        LOGGER.info(
            "Scheduled cache refresh every %d seconds (TTL: %ds)",
            refresh_seconds,
            cache_ttl,
        )

    # Add purge job for metrics, traces, and actions (runs every hour)
    _scheduler.add_job(
        _purge_old_metrics,
        trigger=IntervalTrigger(hours=1),
        id="data_purge",
        name="Data Retention Purge",
        replace_existing=True,
    )

    LOGGER.info("Scheduled data retention purge every hour")

    return _scheduler


async def start_scheduler() -> None:
    """Start the scheduler if configured."""
    global _scheduler

    if _scheduler is None:
        _scheduler = await create_scheduler()

    if _scheduler is None:
        return

    if not _scheduler.running:
        _scheduler.start()
        LOGGER.info("Scheduler started")

        # Only run initial analysis if monitoring is enabled
        settings = get_settings()
        if settings.monitoring.enabled:
            asyncio.create_task(_run_initial_analysis())


async def _run_initial_analysis() -> None:
    """Run initial analysis after a short delay."""
    await asyncio.sleep(5)

    if _monitoring_service is not None:
        LOGGER.info("Running initial monitoring analysis")
        try:
            await _monitoring_service.run_analysis()
        except Exception as exc:
            LOGGER.exception("Initial monitoring analysis failed: %s", exc)


def shutdown_scheduler(wait: bool = False) -> None:
    """Shutdown the scheduler."""
    global _scheduler, _monitoring_service

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=wait)
        LOGGER.info("Scheduler stopped")

    _scheduler = None
    _monitoring_service = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Get the current scheduler instance."""
    return _scheduler


__all__ = [
    "create_scheduler",
    "get_scheduler",
    "shutdown_scheduler",
    "start_scheduler",
]
