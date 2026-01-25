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

    Returns None if monitoring is disabled.
    """
    global _scheduler, _monitoring_service

    settings = get_settings()

    if not settings.monitoring.enabled:
        LOGGER.info("AI monitoring is disabled")
        return None

    _monitoring_service = await create_monitoring_service(
        broadcast_callback=_broadcast_wrapper
    )

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        }
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
