"""OpenTelemetry setup with SQLite-backed trace storage.

This module configures distributed tracing for the application using
OpenTelemetry with a custom SQLite exporter for local trace storage.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from portainer_dashboard.config import TracingSettings, get_settings
from portainer_dashboard.models.tracing import Span, SpanKind, SpanStatus, Trace
from portainer_dashboard.services.trace_store import SQLiteTraceStore, get_trace_store

if TYPE_CHECKING:
    from fastapi import FastAPI

LOGGER = logging.getLogger(__name__)

# OpenTelemetry imports - optional, gracefully handle if not installed
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
    from opentelemetry.semconv.resource import ResourceAttributes
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    _OTEL_AVAILABLE = True
except ImportError:
    LOGGER.info("OpenTelemetry packages not installed, tracing disabled")


def _otel_span_kind_to_model(kind_value: int) -> SpanKind:
    """Convert OpenTelemetry SpanKind to our model."""
    if not _OTEL_AVAILABLE:
        return SpanKind.INTERNAL
    from opentelemetry.trace import SpanKind as OtelSpanKind

    mapping = {
        OtelSpanKind.INTERNAL: SpanKind.INTERNAL,
        OtelSpanKind.SERVER: SpanKind.SERVER,
        OtelSpanKind.CLIENT: SpanKind.CLIENT,
        OtelSpanKind.PRODUCER: SpanKind.PRODUCER,
        OtelSpanKind.CONSUMER: SpanKind.CONSUMER,
    }
    return mapping.get(kind_value, SpanKind.INTERNAL)


def _otel_status_to_model(status_code) -> SpanStatus:
    """Convert OpenTelemetry StatusCode to our model."""
    if not _OTEL_AVAILABLE:
        return SpanStatus.UNSET
    from opentelemetry.trace import StatusCode

    if status_code == StatusCode.OK:
        return SpanStatus.OK
    elif status_code == StatusCode.ERROR:
        return SpanStatus.ERROR
    return SpanStatus.UNSET


def _ns_to_datetime(ns: int) -> datetime:
    """Convert nanoseconds to datetime."""
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


class SQLiteSpanExporter(SpanExporter if _OTEL_AVAILABLE else object):
    """Custom OpenTelemetry exporter that stores spans in SQLite."""

    def __init__(self, trace_store: SQLiteTraceStore, service_name: str) -> None:
        self._trace_store = trace_store
        self._service_name = service_name
        self._pending_traces: dict[str, list[Span]] = {}

    def export(self, spans) -> "SpanExportResult":
        """Export spans to SQLite storage."""
        if not _OTEL_AVAILABLE:
            return SpanExportResult.SUCCESS

        try:
            model_spans: list[Span] = []

            for otel_span in spans:
                # Extract attributes
                attributes = {}
                for key, value in otel_span.attributes.items():
                    if isinstance(value, (str, int, float, bool)):
                        attributes[key] = value
                    else:
                        attributes[key] = str(value)

                # Calculate duration
                duration_ms = None
                if otel_span.end_time and otel_span.start_time:
                    duration_ms = int((otel_span.end_time - otel_span.start_time) / 1e6)

                # Create model span
                span = Span(
                    trace_id=format(otel_span.context.trace_id, "032x"),
                    span_id=format(otel_span.context.span_id, "016x"),
                    parent_span_id=(
                        format(otel_span.parent.span_id, "016x")
                        if otel_span.parent else None
                    ),
                    name=otel_span.name,
                    kind=_otel_span_kind_to_model(otel_span.kind),
                    status=_otel_status_to_model(otel_span.status.status_code),
                    status_message=otel_span.status.description,
                    start_time=_ns_to_datetime(otel_span.start_time),
                    end_time=_ns_to_datetime(otel_span.end_time) if otel_span.end_time else None,
                    duration_ms=duration_ms,
                    service_name=self._service_name,
                    attributes=attributes,
                )
                model_spans.append(span)

            # Store spans
            if model_spans:
                self._trace_store.store_spans_batch(model_spans)

                # Build trace summaries from root spans
                for span in model_spans:
                    if span.parent_span_id is None:
                        # This is a root span, create/update trace
                        self._create_trace_summary(span, model_spans)

            return SpanExportResult.SUCCESS

        except Exception as exc:
            LOGGER.warning("Failed to export spans: %s", exc)
            return SpanExportResult.FAILURE

    def _create_trace_summary(self, root_span: Span, all_spans: list[Span]) -> None:
        """Create a trace summary from the root span."""
        trace_spans = [s for s in all_spans if s.trace_id == root_span.trace_id]

        # Check for errors
        has_errors = any(s.status == SpanStatus.ERROR for s in trace_spans)

        # Extract HTTP metadata from attributes
        http_method = root_span.attributes.get("http.method")
        http_route = root_span.attributes.get("http.route")
        http_status = root_span.attributes.get("http.status_code")

        # Find end time (latest span end)
        end_times = [s.end_time for s in trace_spans if s.end_time]
        end_time = max(end_times) if end_times else None

        # Calculate total duration
        total_duration = None
        if end_time and root_span.start_time:
            delta = end_time - root_span.start_time
            total_duration = int(delta.total_seconds() * 1000)

        trace = Trace(
            trace_id=root_span.trace_id,
            root_span_name=root_span.name,
            service_name=self._service_name,
            start_time=root_span.start_time,
            end_time=end_time,
            total_duration_ms=total_duration,
            span_count=len(trace_spans),
            has_errors=has_errors,
            http_method=str(http_method) if http_method else None,
            http_route=str(http_route) if http_route else None,
            http_status_code=int(http_status) if http_status else None,
        )

        self._trace_store.store_trace(trace)

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any pending spans."""
        return True


class SamplingSQLiteExporter(SQLiteSpanExporter):
    """SQLite exporter with sampling support."""

    def __init__(
        self,
        trace_store: SQLiteTraceStore,
        service_name: str,
        sample_rate: float = 1.0,
    ) -> None:
        super().__init__(trace_store, service_name)
        self._sample_rate = max(0.0, min(1.0, sample_rate))

    def export(self, spans) -> "SpanExportResult":
        """Export spans with sampling."""
        if self._sample_rate < 1.0:
            # Sample at trace level - only export if trace is sampled
            sampled_spans = []
            sampled_traces: set[str] = set()

            for span in spans:
                trace_id = format(span.context.trace_id, "032x")

                # Decide sampling based on trace_id if not already decided
                if trace_id not in sampled_traces:
                    if random.random() < self._sample_rate:
                        sampled_traces.add(trace_id)

                if trace_id in sampled_traces:
                    sampled_spans.append(span)

            if not sampled_spans:
                return SpanExportResult.SUCCESS

            return super().export(sampled_spans)

        return super().export(spans)


_tracer_provider: "TracerProvider | None" = None


async def setup_telemetry(app: "FastAPI", settings: TracingSettings | None = None) -> None:
    """Set up OpenTelemetry tracing for the FastAPI application.

    Args:
        app: The FastAPI application to instrument.
        settings: Tracing settings. If None, uses global settings.
    """
    global _tracer_provider

    if not _OTEL_AVAILABLE:
        LOGGER.info("OpenTelemetry not available, skipping telemetry setup")
        return

    if settings is None:
        settings = get_settings().tracing

    if not settings.enabled:
        LOGGER.info("Tracing is disabled")
        return

    # Get trace store
    trace_store = await get_trace_store()

    # Create resource
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: settings.service_name,
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
    })

    # Create exporter
    exporter = SamplingSQLiteExporter(
        trace_store=trace_store,
        service_name=settings.service_name,
        sample_rate=settings.sample_rate,
    )

    # Create and set tracer provider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(_tracer_provider)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Instrument httpx
    HTTPXClientInstrumentor().instrument()

    LOGGER.info(
        "Telemetry enabled: service=%s, sample_rate=%.2f",
        settings.service_name,
        settings.sample_rate,
    )


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush pending spans."""
    global _tracer_provider

    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None
        LOGGER.info("Telemetry shutdown complete")


def get_tracer(name: str = "portainer-dashboard"):
    """Get a tracer for manual instrumentation."""
    if not _OTEL_AVAILABLE:
        return None
    return otel_trace.get_tracer(name)


__all__ = [
    "SamplingSQLiteExporter",
    "SQLiteSpanExporter",
    "get_tracer",
    "setup_telemetry",
    "shutdown_telemetry",
]
