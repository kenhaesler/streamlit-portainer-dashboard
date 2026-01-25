"""SQLite-backed time-series metrics storage."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.metrics import (
    AnomalyDetection,
    ContainerMetric,
    MetricsDashboard,
    MetricsSummary,
    MetricType,
)

LOGGER = logging.getLogger(__name__)


class SQLiteMetricsStore:
    """SQLite-backed storage for time-series container metrics."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = RLock()
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._lock:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metrics (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        endpoint_id INTEGER NOT NULL,
                        endpoint_name TEXT,
                        container_id TEXT NOT NULL,
                        container_name TEXT NOT NULL,
                        metric_type TEXT NOT NULL,
                        value REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_container_time
                    ON metrics (container_id, timestamp DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
                    ON metrics (timestamp DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS anomalies (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        endpoint_id INTEGER NOT NULL,
                        endpoint_name TEXT,
                        container_id TEXT NOT NULL,
                        container_name TEXT NOT NULL,
                        metric_type TEXT NOT NULL,
                        current_value REAL NOT NULL,
                        expected_value REAL NOT NULL,
                        zscore REAL NOT NULL,
                        is_anomaly INTEGER NOT NULL,
                        direction TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_anomalies_timestamp
                    ON anomalies (timestamp DESC)
                    """
                )
                connection.commit()
            LOGGER.info("Metrics store initialized at %s", self._database_path)

    @staticmethod
    def _encode_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    def store_metric(self, metric: ContainerMetric) -> None:
        """Store a single metric data point."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO metrics (
                    id, timestamp, endpoint_id, endpoint_name,
                    container_id, container_name, metric_type, value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric.id,
                    self._encode_datetime(metric.timestamp),
                    metric.endpoint_id,
                    metric.endpoint_name,
                    metric.container_id,
                    metric.container_name,
                    metric.metric_type.value,
                    metric.value,
                ),
            )
            connection.commit()

    def store_metrics_batch(self, metrics: list[ContainerMetric]) -> None:
        """Store multiple metrics efficiently."""
        if not metrics:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO metrics (
                    id, timestamp, endpoint_id, endpoint_name,
                    container_id, container_name, metric_type, value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        m.id,
                        self._encode_datetime(m.timestamp),
                        m.endpoint_id,
                        m.endpoint_name,
                        m.container_id,
                        m.container_name,
                        m.metric_type.value,
                        m.value,
                    )
                    for m in metrics
                ],
            )
            connection.commit()
            LOGGER.debug("Stored %d metrics", len(metrics))

    def get_metrics(
        self,
        container_id: str,
        metric_type: MetricType | None = None,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
    ) -> list[ContainerMetric]:
        """Retrieve metrics for a container."""
        query = "SELECT * FROM metrics WHERE container_id = ?"
        params: list[str | int] = [container_id]

        if metric_type:
            query += " AND metric_type = ?"
            params.append(metric_type.value)

        if start_time:
            query += " AND timestamp >= ?"
            params.append(self._encode_datetime(start_time))

        if end_time:
            query += " AND timestamp <= ?"
            params.append(self._encode_datetime(end_time))

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()

        return [
            ContainerMetric(
                id=row["id"],
                timestamp=self._decode_datetime(row["timestamp"]),
                endpoint_id=row["endpoint_id"],
                endpoint_name=row["endpoint_name"],
                container_id=row["container_id"],
                container_name=row["container_name"],
                metric_type=MetricType(row["metric_type"]),
                value=row["value"],
            )
            for row in rows
        ]

    def get_metrics_summary(
        self,
        container_id: str,
        metric_type: MetricType,
        *,
        hours: int = 24,
    ) -> MetricsSummary | None:
        """Get statistical summary for a container's metrics."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT
                    container_id,
                    container_name,
                    endpoint_id,
                    endpoint_name,
                    COUNT(*) as count,
                    MIN(value) as min_value,
                    MAX(value) as max_value,
                    AVG(value) as avg_value,
                    MAX(timestamp) as latest_timestamp
                FROM metrics
                WHERE container_id = ? AND metric_type = ? AND timestamp >= ?
                GROUP BY container_id
                """,
                (container_id, metric_type.value, self._encode_datetime(cutoff)),
            )
            row = cursor.fetchone()

            if not row or row["count"] == 0:
                return None

            # Calculate std dev separately
            cursor = connection.execute(
                """
                SELECT value FROM metrics
                WHERE container_id = ? AND metric_type = ? AND timestamp >= ?
                """,
                (container_id, metric_type.value, self._encode_datetime(cutoff)),
            )
            values = [r["value"] for r in cursor.fetchall()]

            avg = row["avg_value"]
            variance = sum((v - avg) ** 2 for v in values) / len(values) if values else 0
            std_dev = variance**0.5

            # Get latest value
            cursor = connection.execute(
                """
                SELECT value FROM metrics
                WHERE container_id = ? AND metric_type = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (container_id, metric_type.value),
            )
            latest_row = cursor.fetchone()
            latest_value = latest_row["value"] if latest_row else 0.0

            return MetricsSummary(
                container_id=row["container_id"],
                container_name=row["container_name"],
                endpoint_id=row["endpoint_id"],
                endpoint_name=row["endpoint_name"],
                metric_type=metric_type,
                count=row["count"],
                min_value=row["min_value"],
                max_value=row["max_value"],
                avg_value=row["avg_value"],
                std_dev=std_dev,
                latest_value=latest_value,
                latest_timestamp=self._decode_datetime(row["latest_timestamp"]),
            )

    def get_recent_values(
        self,
        container_id: str,
        metric_type: MetricType,
        *,
        count: int = 30,
    ) -> list[float]:
        """Get recent values for anomaly detection."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT value FROM metrics
                WHERE container_id = ? AND metric_type = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (container_id, metric_type.value, count),
            )
            return [row["value"] for row in cursor.fetchall()]

    def store_anomaly(self, anomaly: AnomalyDetection) -> None:
        """Store an anomaly detection result."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO anomalies (
                    id, timestamp, endpoint_id, endpoint_name,
                    container_id, container_name, metric_type,
                    current_value, expected_value, zscore, is_anomaly, direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anomaly.id,
                    self._encode_datetime(anomaly.timestamp),
                    anomaly.endpoint_id,
                    anomaly.endpoint_name,
                    anomaly.container_id,
                    anomaly.container_name,
                    anomaly.metric_type.value,
                    anomaly.current_value,
                    anomaly.expected_value,
                    anomaly.zscore,
                    1 if anomaly.is_anomaly else 0,
                    anomaly.direction,
                ),
            )
            connection.commit()

    def get_anomalies(
        self,
        *,
        hours: int = 24,
        limit: int = 100,
        only_anomalies: bool = True,
    ) -> list[AnomalyDetection]:
        """Get recent anomaly detections."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = "SELECT * FROM anomalies WHERE timestamp >= ?"
        params: list[str | int] = [self._encode_datetime(cutoff)]

        if only_anomalies:
            query += " AND is_anomaly = 1"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()

        return [
            AnomalyDetection(
                id=row["id"],
                timestamp=self._decode_datetime(row["timestamp"]),
                endpoint_id=row["endpoint_id"],
                endpoint_name=row["endpoint_name"],
                container_id=row["container_id"],
                container_name=row["container_name"],
                metric_type=MetricType(row["metric_type"]),
                current_value=row["current_value"],
                expected_value=row["expected_value"],
                zscore=row["zscore"],
                is_anomaly=bool(row["is_anomaly"]),
                direction=row["direction"],
            )
            for row in rows
        ]

    def get_dashboard_data(self) -> MetricsDashboard:
        """Get overview data for the metrics dashboard."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)

        with self._lock, self._connect() as connection:
            cursor = connection.execute("SELECT COUNT(*) FROM metrics")
            total_metrics = cursor.fetchone()[0]

            cursor = connection.execute("SELECT COUNT(DISTINCT container_id) FROM metrics")
            containers_tracked = cursor.fetchone()[0]

            cursor = connection.execute("SELECT COUNT(DISTINCT endpoint_id) FROM metrics")
            endpoints_tracked = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM anomalies WHERE timestamp >= ? AND is_anomaly = 1",
                (self._encode_datetime(cutoff_24h),),
            )
            anomalies_24h = cursor.fetchone()[0]

            cursor = connection.execute("SELECT MIN(timestamp), MAX(timestamp) FROM metrics")
            row = cursor.fetchone()
            oldest = self._decode_datetime(row[0]) if row[0] else None
            newest = self._decode_datetime(row[1]) if row[1] else None

        # Get storage size
        try:
            storage_size = self._database_path.stat().st_size
        except OSError:
            storage_size = 0

        return MetricsDashboard(
            total_metrics=total_metrics,
            containers_tracked=containers_tracked,
            endpoints_tracked=endpoints_tracked,
            anomalies_detected_24h=anomalies_24h,
            oldest_metric=oldest,
            newest_metric=newest,
            storage_size_bytes=storage_size,
        )

    def purge_old_metrics(self, retention_hours: int) -> int:
        """Remove metrics older than retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM metrics WHERE timestamp < ?",
                (self._encode_datetime(cutoff),),
            )
            metrics_deleted = cursor.rowcount

            cursor = connection.execute(
                "DELETE FROM anomalies WHERE timestamp < ?",
                (self._encode_datetime(cutoff),),
            )
            anomalies_deleted = cursor.rowcount

            connection.commit()

        if metrics_deleted > 0 or anomalies_deleted > 0:
            LOGGER.info(
                "Purged %d metrics and %d anomalies older than %d hours",
                metrics_deleted,
                anomalies_deleted,
                retention_hours,
            )

        return metrics_deleted


_metrics_store: SQLiteMetricsStore | None = None


async def get_metrics_store() -> SQLiteMetricsStore:
    """Get or create the metrics store singleton."""
    global _metrics_store
    if _metrics_store is None:
        settings = get_settings()
        _metrics_store = SQLiteMetricsStore(settings.metrics.sqlite_path)
    return _metrics_store


__all__ = [
    "SQLiteMetricsStore",
    "get_metrics_store",
]
