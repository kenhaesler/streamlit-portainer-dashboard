"""REST API endpoints for distributed tracing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.tracing import (
    ServiceMap,
    Trace,
    TraceFilter,
    TracesSummary,
)
from portainer_dashboard.services.trace_store import get_trace_store

router = APIRouter(prefix="/traces", tags=["Traces"])


@router.get("/status")
async def get_tracing_status() -> dict:
    """Get tracing status and configuration."""
    settings = get_settings()

    return {
        "enabled": settings.tracing.enabled,
        "service_name": settings.tracing.service_name,
        "retention_hours": settings.tracing.retention_hours,
        "sample_rate": settings.tracing.sample_rate,
    }


@router.get("/summary", response_model=TracesSummary)
async def get_traces_summary() -> TracesSummary:
    """Get summary statistics for traces."""
    settings = get_settings()

    if not settings.tracing.enabled:
        raise HTTPException(status_code=503, detail="Tracing is disabled")

    store = await get_trace_store()
    return store.get_summary()


@router.get("/", response_model=list[Trace])
async def list_traces(
    service_name: str | None = None,
    http_method: str | None = None,
    http_route: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    has_errors: bool | None = None,
    hours: int = Query(default=1, ge=1, le=24),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[Trace]:
    """List traces with optional filtering.

    Args:
        service_name: Filter by service name.
        http_method: Filter by HTTP method (GET, POST, etc.).
        http_route: Filter by HTTP route (partial match).
        min_duration_ms: Minimum duration in milliseconds.
        max_duration_ms: Maximum duration in milliseconds.
        has_errors: Filter by error status.
        hours: Number of hours of history (default 1, max 24).
        limit: Maximum number of traces to return.
        offset: Pagination offset.
    """
    settings = get_settings()

    if not settings.tracing.enabled:
        raise HTTPException(status_code=503, detail="Tracing is disabled")

    store = await get_trace_store()

    filter = TraceFilter(
        service_name=service_name,
        http_method=http_method,
        http_route=http_route,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        has_errors=has_errors,
        start_time=datetime.now(timezone.utc) - timedelta(hours=hours),
        limit=limit,
        offset=offset,
    )

    return store.list_traces(filter)


@router.get("/service-map", response_model=ServiceMap)
async def get_service_map(
    hours: int = Query(default=1, ge=1, le=24),
) -> ServiceMap:
    """Get the service dependency map.

    Returns nodes (services) and edges (dependencies) based on
    trace data from the specified time period.
    """
    settings = get_settings()

    if not settings.tracing.enabled:
        raise HTTPException(status_code=503, detail="Tracing is disabled")

    store = await get_trace_store()
    return store.get_service_map(hours=hours)


@router.get("/{trace_id}", response_model=Trace)
async def get_trace(trace_id: str) -> Trace:
    """Get a specific trace with all its spans.

    Returns the complete trace including the waterfall of spans
    for detailed analysis.
    """
    settings = get_settings()

    if not settings.tracing.enabled:
        raise HTTPException(status_code=503, detail="Tracing is disabled")

    store = await get_trace_store()
    trace = store.get_trace(trace_id)

    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    return trace


@router.get("/routes/stats")
async def get_route_stats(
    hours: int = Query(default=1, ge=1, le=24),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """Get statistics for routes/endpoints.

    Returns aggregated stats per route including request count,
    error rate, and latency percentiles.
    """
    settings = get_settings()

    if not settings.tracing.enabled:
        raise HTTPException(status_code=503, detail="Tracing is disabled")

    store = await get_trace_store()

    # Get all traces for the period
    filter = TraceFilter(
        start_time=datetime.now(timezone.utc) - timedelta(hours=hours),
        limit=10000,  # Get enough data for aggregation
    )
    traces = store.list_traces(filter)

    # Aggregate by route
    route_stats: dict[str, dict] = {}

    for trace in traces:
        route = trace.http_route or "unknown"
        method = trace.http_method or "?"

        key = f"{method} {route}"

        if key not in route_stats:
            route_stats[key] = {
                "route": route,
                "method": method,
                "request_count": 0,
                "error_count": 0,
                "durations": [],
            }

        route_stats[key]["request_count"] += 1
        if trace.has_errors:
            route_stats[key]["error_count"] += 1
        if trace.total_duration_ms is not None:
            route_stats[key]["durations"].append(trace.total_duration_ms)

    # Calculate final stats
    results = []
    for key, stats in route_stats.items():
        durations = sorted(stats["durations"])
        n = len(durations)

        result = {
            "route": stats["route"],
            "method": stats["method"],
            "request_count": stats["request_count"],
            "error_count": stats["error_count"],
            "error_rate": (
                stats["error_count"] / stats["request_count"] * 100
                if stats["request_count"] > 0 else 0
            ),
            "avg_duration_ms": sum(durations) / n if n > 0 else 0,
            "p50_duration_ms": durations[int(n * 0.5)] if n > 0 else 0,
            "p95_duration_ms": durations[int(n * 0.95)] if n > 0 else 0,
            "p99_duration_ms": durations[int(n * 0.99)] if n > 0 else 0,
        }
        results.append(result)

    # Sort by request count descending
    results.sort(key=lambda x: x["request_count"], reverse=True)

    return results[:limit]


__all__ = ["router"]
