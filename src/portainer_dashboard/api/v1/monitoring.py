"""REST API endpoints for monitoring insights and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.monitoring import MonitoringInsight, MonitoringReport
from portainer_dashboard.services.insights_store import InsightsStore, get_insights_store

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


async def get_store() -> InsightsStore:
    """Dependency to get the insights store."""
    return await get_insights_store()


StoreDep = Annotated[InsightsStore, Depends(get_store)]


@router.get("/status")
async def get_monitoring_status() -> dict:
    """Get the current status of the monitoring service."""
    settings = get_settings()
    store = await get_insights_store()

    latest_report = await store.get_latest_report()

    return {
        "enabled": settings.monitoring.enabled,
        "interval_minutes": settings.monitoring.interval_minutes,
        "include_security_scan": settings.monitoring.include_security_scan,
        "include_image_check": settings.monitoring.include_image_check,
        "last_analysis": latest_report.timestamp.isoformat() if latest_report else None,
        "insights_stored": len(await store.get_insights()),
    }


@router.get("/insights", response_model=list[MonitoringInsight])
async def get_insights(
    store: StoreDep,
    limit: int = Query(default=50, ge=1, le=100),
    since: datetime | None = Query(default=None),
) -> list[MonitoringInsight]:
    """Get stored monitoring insights.

    Args:
        limit: Maximum number of insights to return (1-100)
        since: Only return insights after this timestamp
    """
    return await store.get_insights(limit=limit, since=since)


@router.get("/reports", response_model=list[MonitoringReport])
async def get_reports(
    store: StoreDep,
    limit: int = Query(default=10, ge=1, le=50),
    since: datetime | None = Query(default=None),
) -> list[MonitoringReport]:
    """Get stored monitoring reports.

    Args:
        limit: Maximum number of reports to return (1-50)
        since: Only return reports after this timestamp
    """
    return await store.get_reports(limit=limit, since=since)


@router.get("/reports/latest", response_model=MonitoringReport | None)
async def get_latest_report(store: StoreDep) -> MonitoringReport | None:
    """Get the most recent monitoring report."""
    report = await store.get_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No monitoring reports available yet",
        )
    return report


@router.post("/trigger")
async def trigger_analysis() -> dict:
    """Manually trigger a monitoring analysis.

    This is useful for testing or getting immediate results.
    """
    from portainer_dashboard.services.monitoring_service import create_monitoring_service
    from portainer_dashboard.websocket.monitoring_insights import broadcast_report

    settings = get_settings()

    if not settings.monitoring.enabled:
        raise HTTPException(
            status_code=400,
            detail="Monitoring is disabled",
        )

    async def broadcast_wrapper(report: MonitoringReport) -> None:
        await broadcast_report(report)

    try:
        service = await create_monitoring_service(broadcast_callback=broadcast_wrapper)
        report = await service.run_analysis()

        return {
            "success": True,
            "report_id": report.id,
            "insights_count": len(report.insights),
            "summary": report.summary,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {exc}",
        ) from exc


@router.delete("/insights")
async def clear_insights(store: StoreDep) -> dict:
    """Clear all stored insights and reports."""
    await store.clear()
    return {"success": True, "message": "All insights cleared"}


__all__ = ["router"]
