"""Distributed tracing data models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class SpanKind(str, Enum):
    """Type of span in the trace."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(str, Enum):
    """Status of a span."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class Span(BaseModel):
    """Single span in a distributed trace."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: SpanKind = SpanKind.INTERNAL
    status: SpanStatus = SpanStatus.UNSET
    status_message: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: int | None = None
    service_name: str = "portainer-dashboard"
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class Trace(BaseModel):
    """Complete trace with all spans."""

    trace_id: str
    root_span_name: str
    service_name: str = "portainer-dashboard"
    start_time: datetime
    end_time: datetime | None = None
    total_duration_ms: int | None = None
    span_count: int = 0
    has_errors: bool = False
    spans: list[Span] = Field(default_factory=list)

    # Correlation metadata
    endpoint_id: int | None = None
    container_id: str | None = None
    http_method: str | None = None
    http_route: str | None = None
    http_status_code: int | None = None
    user_id: str | None = None


class TracesSummary(BaseModel):
    """Summary statistics for traces."""

    total_traces: int = 0
    traces_last_hour: int = 0
    traces_with_errors: int = 0
    error_rate: float = 0.0
    avg_duration_ms: float = 0.0
    p50_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    unique_routes: int = 0
    storage_size_bytes: int = 0


class ServiceNode(BaseModel):
    """Node in the service dependency map."""

    service_name: str
    request_count: int = 0
    error_count: int = 0
    avg_duration_ms: float = 0.0


class ServiceEdge(BaseModel):
    """Edge in the service dependency map."""

    source: str
    target: str
    request_count: int = 0
    error_count: int = 0
    avg_duration_ms: float = 0.0


class ServiceMap(BaseModel):
    """Service dependency map."""

    nodes: list[ServiceNode] = Field(default_factory=list)
    edges: list[ServiceEdge] = Field(default_factory=list)


class TraceFilter(BaseModel):
    """Filters for querying traces."""

    trace_id: str | None = None
    service_name: str | None = None
    http_method: str | None = None
    http_route: str | None = None
    min_duration_ms: int | None = None
    max_duration_ms: int | None = None
    has_errors: bool | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = 100
    offset: int = 0


__all__ = [
    "ServiceEdge",
    "ServiceMap",
    "ServiceNode",
    "Span",
    "SpanKind",
    "SpanStatus",
    "Trace",
    "TraceFilter",
    "TracesSummary",
]
