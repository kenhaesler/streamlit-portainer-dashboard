"""REST API endpoints for time-series metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.metrics import (
    AnomalyDetection,
    ContainerMetric,
    MetricsDashboard,
    MetricsSummary,
    MetricType,
)
from portainer_dashboard.services.metrics_store import get_metrics_store

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/status")
async def get_metrics_status() -> dict:
    """Get metrics collection status and configuration."""
    settings = get_settings()

    return {
        "enabled": settings.metrics.enabled,
        "anomaly_detection_enabled": settings.metrics.anomaly_detection_enabled,
        "retention_hours": settings.metrics.retention_hours,
        "collection_interval_seconds": settings.metrics.collection_interval_seconds,
        "zscore_threshold": settings.metrics.zscore_threshold,
        "moving_average_window": settings.metrics.moving_average_window,
        "min_samples_for_detection": settings.metrics.min_samples_for_detection,
    }


@router.get("/dashboard", response_model=MetricsDashboard)
async def get_metrics_dashboard() -> MetricsDashboard:
    """Get overview data for the metrics dashboard."""
    settings = get_settings()

    if not settings.metrics.enabled:
        raise HTTPException(status_code=503, detail="Metrics collection is disabled")

    store = await get_metrics_store()
    return store.get_dashboard_data()


@router.get("/containers/{container_id}", response_model=list[ContainerMetric])
async def get_container_metrics(
    container_id: str,
    metric_type: MetricType | None = None,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[ContainerMetric]:
    """Get historical metrics for a container.

    Args:
        container_id: The container ID to get metrics for.
        metric_type: Optional filter for specific metric type.
        hours: Number of hours of history to retrieve (default 24, max 168).
        limit: Maximum number of metrics to return (default 1000).
    """
    settings = get_settings()

    if not settings.metrics.enabled:
        raise HTTPException(status_code=503, detail="Metrics collection is disabled")

    store = await get_metrics_store()

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    return store.get_metrics(
        container_id,
        metric_type=metric_type,
        start_time=start_time,
        limit=limit,
    )


@router.get("/containers/{container_id}/summary", response_model=MetricsSummary | None)
async def get_container_metrics_summary(
    container_id: str,
    metric_type: MetricType = MetricType.CPU_PERCENT,
    hours: int = Query(default=24, ge=1, le=168),
) -> MetricsSummary | None:
    """Get statistical summary for a container's metrics.

    Args:
        container_id: The container ID.
        metric_type: The metric type to summarize.
        hours: Number of hours to analyze.
    """
    settings = get_settings()

    if not settings.metrics.enabled:
        raise HTTPException(status_code=503, detail="Metrics collection is disabled")

    store = await get_metrics_store()
    return store.get_metrics_summary(container_id, metric_type, hours=hours)


@router.get("/anomalies", response_model=list[AnomalyDetection])
async def get_anomalies(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=1000),
    only_anomalies: bool = True,
) -> list[AnomalyDetection]:
    """Get recent anomaly detections.

    Args:
        hours: Number of hours of history to retrieve.
        limit: Maximum number of results.
        only_anomalies: If True, only return actual anomalies (zscore > threshold).
    """
    settings = get_settings()

    if not settings.metrics.enabled:
        raise HTTPException(status_code=503, detail="Metrics collection is disabled")

    if not settings.metrics.anomaly_detection_enabled:
        raise HTTPException(status_code=503, detail="Anomaly detection is disabled")

    store = await get_metrics_store()
    return store.get_anomalies(hours=hours, limit=limit, only_anomalies=only_anomalies)


@router.get("/containers/{container_id}/anomalies", response_model=list[AnomalyDetection])
async def get_container_anomalies(
    container_id: str,
    hours: int = Query(default=24, ge=1, le=168),
) -> list[AnomalyDetection]:
    """Get anomalies for a specific container.

    Args:
        container_id: The container ID.
        hours: Number of hours of history.
    """
    settings = get_settings()

    if not settings.metrics.enabled:
        raise HTTPException(status_code=503, detail="Metrics collection is disabled")

    store = await get_metrics_store()
    all_anomalies = store.get_anomalies(hours=hours, limit=1000, only_anomalies=True)

    return [a for a in all_anomalies if a.container_id == container_id]


__all__ = ["router"]
