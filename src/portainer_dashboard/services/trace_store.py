"""SQLite-backed storage for distributed traces."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.tracing import (
    ServiceEdge,
    ServiceMap,
    ServiceNode,
    Span,
    SpanKind,
    SpanStatus,
    Trace,
    TraceFilter,
    TracesSummary,
)

LOGGER = logging.getLogger(__name__)


class SQLiteTraceStore:
    """SQLite-backed storage for distributed traces."""

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
                    CREATE TABLE IF NOT EXISTS spans (
                        trace_id TEXT NOT NULL,
                        span_id TEXT NOT NULL,
                        parent_span_id TEXT,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        status TEXT NOT NULL,
                        status_message TEXT,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        duration_ms INTEGER,
                        service_name TEXT NOT NULL,
                        attributes TEXT,
                        PRIMARY KEY (trace_id, span_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_spans_trace_id
                    ON spans (trace_id)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_spans_start_time
                    ON spans (start_time DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS traces (
                        trace_id TEXT PRIMARY KEY,
                        root_span_name TEXT NOT NULL,
                        service_name TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        total_duration_ms INTEGER,
                        span_count INTEGER NOT NULL,
                        has_errors INTEGER NOT NULL,
                        endpoint_id INTEGER,
                        container_id TEXT,
                        http_method TEXT,
                        http_route TEXT,
                        http_status_code INTEGER,
                        user_id TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_traces_start_time
                    ON traces (start_time DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_traces_route
                    ON traces (http_route)
                    """
                )
                connection.commit()
            LOGGER.info("Trace store initialized at %s", self._database_path)

    @staticmethod
    def _encode_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    def store_span(self, span: Span) -> None:
        """Store a single span."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO spans (
                    trace_id, span_id, parent_span_id, name, kind, status,
                    status_message, start_time, end_time, duration_ms,
                    service_name, attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    span.trace_id,
                    span.span_id,
                    span.parent_span_id,
                    span.name,
                    span.kind.value,
                    span.status.value,
                    span.status_message,
                    self._encode_datetime(span.start_time),
                    self._encode_datetime(span.end_time),
                    span.duration_ms,
                    span.service_name,
                    json.dumps(span.attributes) if span.attributes else None,
                ),
            )
            connection.commit()

    def store_spans_batch(self, spans: list[Span]) -> None:
        """Store multiple spans efficiently."""
        if not spans:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO spans (
                    trace_id, span_id, parent_span_id, name, kind, status,
                    status_message, start_time, end_time, duration_ms,
                    service_name, attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.trace_id,
                        s.span_id,
                        s.parent_span_id,
                        s.name,
                        s.kind.value,
                        s.status.value,
                        s.status_message,
                        self._encode_datetime(s.start_time),
                        self._encode_datetime(s.end_time),
                        s.duration_ms,
                        s.service_name,
                        json.dumps(s.attributes) if s.attributes else None,
                    )
                    for s in spans
                ],
            )
            connection.commit()
            LOGGER.debug("Stored %d spans", len(spans))

    def store_trace(self, trace: Trace) -> None:
        """Store or update a trace summary."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO traces (
                    trace_id, root_span_name, service_name, start_time, end_time,
                    total_duration_ms, span_count, has_errors, endpoint_id,
                    container_id, http_method, http_route, http_status_code, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.root_span_name,
                    trace.service_name,
                    self._encode_datetime(trace.start_time),
                    self._encode_datetime(trace.end_time),
                    trace.total_duration_ms,
                    trace.span_count,
                    1 if trace.has_errors else 0,
                    trace.endpoint_id,
                    trace.container_id,
                    trace.http_method,
                    trace.http_route,
                    trace.http_status_code,
                    trace.user_id,
                ),
            )
            connection.commit()

    def get_trace(self, trace_id: str) -> Trace | None:
        """Get a trace with all its spans."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM traces WHERE trace_id = ?",
                (trace_id,),
            )
            trace_row = cursor.fetchone()
            if trace_row is None:
                return None

            cursor = connection.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
                (trace_id,),
            )
            span_rows = cursor.fetchall()

        spans = [
            Span(
                trace_id=row["trace_id"],
                span_id=row["span_id"],
                parent_span_id=row["parent_span_id"],
                name=row["name"],
                kind=SpanKind(row["kind"]),
                status=SpanStatus(row["status"]),
                status_message=row["status_message"],
                start_time=self._decode_datetime(row["start_time"]) or datetime.now(timezone.utc),
                end_time=self._decode_datetime(row["end_time"]),
                duration_ms=row["duration_ms"],
                service_name=row["service_name"],
                attributes=json.loads(row["attributes"]) if row["attributes"] else {},
            )
            for row in span_rows
        ]

        return Trace(
            trace_id=trace_row["trace_id"],
            root_span_name=trace_row["root_span_name"],
            service_name=trace_row["service_name"],
            start_time=self._decode_datetime(trace_row["start_time"]) or datetime.now(timezone.utc),
            end_time=self._decode_datetime(trace_row["end_time"]),
            total_duration_ms=trace_row["total_duration_ms"],
            span_count=trace_row["span_count"],
            has_errors=bool(trace_row["has_errors"]),
            spans=spans,
            endpoint_id=trace_row["endpoint_id"],
            container_id=trace_row["container_id"],
            http_method=trace_row["http_method"],
            http_route=trace_row["http_route"],
            http_status_code=trace_row["http_status_code"],
            user_id=trace_row["user_id"],
        )

    def list_traces(self, filter: TraceFilter | None = None) -> list[Trace]:
        """List traces with optional filtering."""
        if filter is None:
            filter = TraceFilter()

        query = "SELECT * FROM traces WHERE 1=1"
        params: list[str | int] = []

        if filter.trace_id:
            query += " AND trace_id = ?"
            params.append(filter.trace_id)

        if filter.service_name:
            query += " AND service_name = ?"
            params.append(filter.service_name)

        if filter.http_method:
            query += " AND http_method = ?"
            params.append(filter.http_method)

        if filter.http_route:
            query += " AND http_route LIKE ?"
            params.append(f"%{filter.http_route}%")

        if filter.min_duration_ms is not None:
            query += " AND total_duration_ms >= ?"
            params.append(filter.min_duration_ms)

        if filter.max_duration_ms is not None:
            query += " AND total_duration_ms <= ?"
            params.append(filter.max_duration_ms)

        if filter.has_errors is not None:
            query += " AND has_errors = ?"
            params.append(1 if filter.has_errors else 0)

        if filter.start_time:
            query += " AND start_time >= ?"
            params.append(self._encode_datetime(filter.start_time) or "")

        if filter.end_time:
            query += " AND start_time <= ?"
            params.append(self._encode_datetime(filter.end_time) or "")

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([filter.limit, filter.offset])

        with self._lock, self._connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()

        return [
            Trace(
                trace_id=row["trace_id"],
                root_span_name=row["root_span_name"],
                service_name=row["service_name"],
                start_time=self._decode_datetime(row["start_time"]) or datetime.now(timezone.utc),
                end_time=self._decode_datetime(row["end_time"]),
                total_duration_ms=row["total_duration_ms"],
                span_count=row["span_count"],
                has_errors=bool(row["has_errors"]),
                endpoint_id=row["endpoint_id"],
                container_id=row["container_id"],
                http_method=row["http_method"],
                http_route=row["http_route"],
                http_status_code=row["http_status_code"],
                user_id=row["user_id"],
            )
            for row in rows
        ]

    def get_summary(self) -> TracesSummary:
        """Get summary statistics for traces."""
        now = datetime.now(timezone.utc)
        cutoff_hour = now - timedelta(hours=1)

        with self._lock, self._connect() as connection:
            cursor = connection.execute("SELECT COUNT(*) FROM traces")
            total = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM traces WHERE start_time >= ?",
                (self._encode_datetime(cutoff_hour),),
            )
            last_hour = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM traces WHERE has_errors = 1"
            )
            with_errors = cursor.fetchone()[0]

            cursor = connection.execute("SELECT AVG(total_duration_ms) FROM traces")
            avg_duration = cursor.fetchone()[0] or 0.0

            # Calculate percentiles
            cursor = connection.execute(
                "SELECT total_duration_ms FROM traces ORDER BY total_duration_ms"
            )
            durations = [row[0] for row in cursor.fetchall() if row[0] is not None]

            p50 = p95 = p99 = 0.0
            if durations:
                n = len(durations)
                p50 = durations[int(n * 0.5)] if n > 0 else 0
                p95 = durations[int(n * 0.95)] if n > 0 else 0
                p99 = durations[int(n * 0.99)] if n > 0 else 0

            cursor = connection.execute(
                "SELECT COUNT(DISTINCT http_route) FROM traces WHERE http_route IS NOT NULL"
            )
            unique_routes = cursor.fetchone()[0]

        error_rate = (with_errors / total * 100) if total > 0 else 0.0

        try:
            storage_size = self._database_path.stat().st_size
        except OSError:
            storage_size = 0

        return TracesSummary(
            total_traces=total,
            traces_last_hour=last_hour,
            traces_with_errors=with_errors,
            error_rate=error_rate,
            avg_duration_ms=avg_duration,
            p50_duration_ms=p50,
            p95_duration_ms=p95,
            p99_duration_ms=p99,
            unique_routes=unique_routes,
            storage_size_bytes=storage_size,
        )

    def get_service_map(self, hours: int = 1) -> ServiceMap:
        """Build a service dependency map from recent traces."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        with self._lock, self._connect() as connection:
            # Get service stats
            cursor = connection.execute(
                """
                SELECT
                    service_name,
                    COUNT(*) as request_count,
                    SUM(CASE WHEN has_errors = 1 THEN 1 ELSE 0 END) as error_count,
                    AVG(total_duration_ms) as avg_duration
                FROM traces
                WHERE start_time >= ?
                GROUP BY service_name
                """,
                (self._encode_datetime(cutoff),),
            )
            nodes = [
                ServiceNode(
                    service_name=row["service_name"],
                    request_count=row["request_count"],
                    error_count=row["error_count"],
                    avg_duration_ms=row["avg_duration"] or 0.0,
                )
                for row in cursor.fetchall()
            ]

            # Get edges from spans with different service names
            cursor = connection.execute(
                """
                SELECT
                    s1.service_name as source,
                    s2.service_name as target,
                    COUNT(*) as request_count,
                    SUM(CASE WHEN s2.status = 'error' THEN 1 ELSE 0 END) as error_count,
                    AVG(s2.duration_ms) as avg_duration
                FROM spans s1
                JOIN spans s2 ON s1.trace_id = s2.trace_id AND s1.span_id = s2.parent_span_id
                WHERE s1.service_name != s2.service_name
                AND s1.start_time >= ?
                GROUP BY s1.service_name, s2.service_name
                """,
                (self._encode_datetime(cutoff),),
            )
            edges = [
                ServiceEdge(
                    source=row["source"],
                    target=row["target"],
                    request_count=row["request_count"],
                    error_count=row["error_count"],
                    avg_duration_ms=row["avg_duration"] or 0.0,
                )
                for row in cursor.fetchall()
            ]

        return ServiceMap(nodes=nodes, edges=edges)

    def purge_old_traces(self, retention_hours: int) -> int:
        """Remove traces older than retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

        with self._lock, self._connect() as connection:
            # Get trace IDs to delete
            cursor = connection.execute(
                "SELECT trace_id FROM traces WHERE start_time < ?",
                (self._encode_datetime(cutoff),),
            )
            trace_ids = [row[0] for row in cursor.fetchall()]

            if not trace_ids:
                return 0

            # Delete spans
            placeholders = ",".join("?" * len(trace_ids))
            connection.execute(
                f"DELETE FROM spans WHERE trace_id IN ({placeholders})",
                trace_ids,
            )

            # Delete traces
            cursor = connection.execute(
                f"DELETE FROM traces WHERE trace_id IN ({placeholders})",
                trace_ids,
            )
            deleted = cursor.rowcount
            connection.commit()

        if deleted > 0:
            LOGGER.info("Purged %d traces older than %d hours", deleted, retention_hours)

        return deleted


_trace_store: SQLiteTraceStore | None = None


async def get_trace_store() -> SQLiteTraceStore:
    """Get or create the trace store singleton."""
    global _trace_store
    if _trace_store is None:
        settings = get_settings()
        _trace_store = SQLiteTraceStore(settings.tracing.sqlite_path)
    return _trace_store


__all__ = [
    "SQLiteTraceStore",
    "get_trace_store",
]
