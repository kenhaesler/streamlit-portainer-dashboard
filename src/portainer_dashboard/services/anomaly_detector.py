"""Z-score based anomaly detection for container metrics."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.metrics import AnomalyDetection, ContainerMetric, MetricType
from portainer_dashboard.services.metrics_store import SQLiteMetricsStore, get_metrics_store

LOGGER = logging.getLogger(__name__)


def _calculate_zscore(value: float, mean: float, std_dev: float) -> float:
    """Calculate the z-score for a value.

    Z-score = (value - mean) / std_dev

    Returns 0.0 if std_dev is 0 (no variance).
    """
    if std_dev == 0:
        return 0.0
    return (value - mean) / std_dev


def _calculate_statistics(values: list[float]) -> tuple[float, float]:
    """Calculate mean and standard deviation from a list of values.

    Returns:
        Tuple of (mean, std_dev)
    """
    if not values:
        return 0.0, 0.0

    n = len(values)
    mean = sum(values) / n

    if n < 2:
        return mean, 0.0

    variance = sum((v - mean) ** 2 for v in values) / n
    std_dev = variance**0.5

    return mean, std_dev


class AnomalyDetector:
    """Z-score based anomaly detector for container metrics."""

    def __init__(self, metrics_store: SQLiteMetricsStore) -> None:
        self._metrics_store = metrics_store
        self._settings = get_settings()

    @property
    def zscore_threshold(self) -> float:
        """Get the configured z-score threshold for anomaly detection."""
        return self._settings.metrics.zscore_threshold

    @property
    def moving_average_window(self) -> int:
        """Get the number of samples for the moving average."""
        return self._settings.metrics.moving_average_window

    @property
    def min_samples(self) -> int:
        """Get the minimum number of samples required for detection."""
        return self._settings.metrics.min_samples_for_detection

    def detect_anomaly(
        self,
        metric: ContainerMetric,
    ) -> AnomalyDetection | None:
        """Detect if a metric value is anomalous based on historical data.

        Uses z-score: if the current value deviates more than threshold
        standard deviations from the historical mean, it's flagged as anomalous.

        Returns:
            AnomalyDetection if analysis was performed, None if insufficient data.
        """
        if not self._settings.metrics.anomaly_detection_enabled:
            return None

        # Get historical values for this container/metric
        historical_values = self._metrics_store.get_recent_values(
            metric.container_id,
            metric.metric_type,
            count=self.moving_average_window,
        )

        # Need minimum samples for meaningful detection
        if len(historical_values) < self.min_samples:
            LOGGER.debug(
                "Insufficient samples for %s/%s: %d < %d",
                metric.container_name,
                metric.metric_type.value,
                len(historical_values),
                self.min_samples,
            )
            return None

        mean, std_dev = _calculate_statistics(historical_values)
        zscore = _calculate_zscore(metric.value, mean, std_dev)
        is_anomaly = abs(zscore) > self.zscore_threshold

        # Determine direction
        if zscore > self.zscore_threshold:
            direction = "high"
        elif zscore < -self.zscore_threshold:
            direction = "low"
        else:
            direction = "normal"

        anomaly = AnomalyDetection(
            timestamp=metric.timestamp,
            endpoint_id=metric.endpoint_id,
            endpoint_name=metric.endpoint_name,
            container_id=metric.container_id,
            container_name=metric.container_name,
            metric_type=metric.metric_type,
            current_value=metric.value,
            expected_value=mean,
            zscore=zscore,
            is_anomaly=is_anomaly,
            direction=direction,
        )

        if is_anomaly:
            LOGGER.info(
                "Anomaly detected: %s/%s value=%.2f expected=%.2f zscore=%.2f",
                metric.container_name,
                metric.metric_type.value,
                metric.value,
                mean,
                zscore,
            )
            self._metrics_store.store_anomaly(anomaly)

        return anomaly

    def analyze_metrics_batch(
        self,
        metrics: list[ContainerMetric],
    ) -> list[AnomalyDetection]:
        """Analyze a batch of metrics for anomalies.

        Returns:
            List of anomaly detections (including non-anomalous results).
        """
        results: list[AnomalyDetection] = []

        for metric in metrics:
            # Only analyze certain metric types for anomalies
            if metric.metric_type in (
                MetricType.CPU_PERCENT,
                MetricType.MEMORY_PERCENT,
            ):
                result = self.detect_anomaly(metric)
                if result:
                    results.append(result)

        return results

    def get_anomaly_summary(
        self,
        container_id: str,
        hours: int = 24,
    ) -> dict:
        """Get anomaly summary for a container over a time period.

        Returns a dict with counts and statistics about anomalies.
        """
        anomalies = self._metrics_store.get_anomalies(
            hours=hours,
            limit=1000,
            only_anomalies=True,
        )

        container_anomalies = [
            a for a in anomalies if a.container_id == container_id
        ]

        cpu_anomalies = [
            a for a in container_anomalies
            if a.metric_type == MetricType.CPU_PERCENT
        ]
        memory_anomalies = [
            a for a in container_anomalies
            if a.metric_type == MetricType.MEMORY_PERCENT
        ]

        return {
            "total_anomalies": len(container_anomalies),
            "cpu_anomalies": len(cpu_anomalies),
            "memory_anomalies": len(memory_anomalies),
            "high_anomalies": sum(1 for a in container_anomalies if a.direction == "high"),
            "low_anomalies": sum(1 for a in container_anomalies if a.direction == "low"),
            "max_zscore": max((a.zscore for a in container_anomalies), default=0.0),
            "avg_zscore": (
                sum(a.zscore for a in container_anomalies) / len(container_anomalies)
                if container_anomalies else 0.0
            ),
        }


async def create_anomaly_detector() -> AnomalyDetector:
    """Create an anomaly detector with the configured store."""
    store = await get_metrics_store()
    return AnomalyDetector(store)


__all__ = [
    "AnomalyDetector",
    "create_anomaly_detector",
]
