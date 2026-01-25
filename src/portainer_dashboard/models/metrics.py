"""Time-series metrics data models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class MetricType(str, Enum):
    """Types of container metrics collected."""

    CPU_PERCENT = "cpu_percent"
    MEMORY_PERCENT = "memory_percent"
    MEMORY_USAGE = "memory_usage"
    NETWORK_RX_BYTES = "network_rx_bytes"
    NETWORK_TX_BYTES = "network_tx_bytes"
    BLOCK_READ_BYTES = "block_read_bytes"
    BLOCK_WRITE_BYTES = "block_write_bytes"


class ContainerMetric(BaseModel):
    """Single time-series metric data point."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    endpoint_id: int
    endpoint_name: str | None = None
    container_id: str
    container_name: str
    metric_type: MetricType
    value: float


class AnomalyDetection(BaseModel):
    """Anomaly detection result for a metric."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    endpoint_id: int
    endpoint_name: str | None = None
    container_id: str
    container_name: str
    metric_type: MetricType
    current_value: float
    expected_value: float
    zscore: float
    is_anomaly: bool
    direction: str = "normal"  # "high", "low", "normal"


class MetricsSummary(BaseModel):
    """Statistical summary for a container's metrics."""

    container_id: str
    container_name: str
    endpoint_id: int
    endpoint_name: str | None = None
    metric_type: MetricType
    count: int = 0
    min_value: float = 0.0
    max_value: float = 0.0
    avg_value: float = 0.0
    std_dev: float = 0.0
    latest_value: float = 0.0
    latest_timestamp: datetime | None = None


class MetricsDashboard(BaseModel):
    """Overview data for metrics dashboard."""

    total_metrics: int = 0
    containers_tracked: int = 0
    endpoints_tracked: int = 0
    anomalies_detected_24h: int = 0
    oldest_metric: datetime | None = None
    newest_metric: datetime | None = None
    storage_size_bytes: int = 0


__all__ = [
    "AnomalyDetection",
    "ContainerMetric",
    "MetricsDashboard",
    "MetricsSummary",
    "MetricType",
]
