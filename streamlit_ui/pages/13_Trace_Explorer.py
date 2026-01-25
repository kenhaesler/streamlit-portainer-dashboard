"""Trace Explorer - Distributed tracing visualization."""

from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth


st.set_page_config(
    page_title="Trace Explorer - Portainer Dashboard",
    page_icon="🔍",
    layout="wide",
)


def format_duration(ms: float | None) -> str:
    """Format duration in human-readable form."""
    if ms is None:
        return "-"
    if ms < 1:
        return "<1ms"
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60000:
        return f"{ms/1000:.2f}s"
    return f"{ms/60000:.1f}min"


def status_color(status: str) -> str:
    """Get color for span status."""
    colors = {
        "ok": "#2ca02c",
        "error": "#ff4b4b",
        "unset": "#888888",
    }
    return colors.get(status.lower(), "#888888")


def render_sidebar() -> None:
    """Render sidebar with tracing info."""
    client = get_api_client()

    with st.sidebar:
        st.markdown(f"**Logged in as:** {st.session_state.get('username', 'User')}")

        session_info = client.get_session_status()
        if session_info:
            minutes_remaining = session_info.get("minutes_remaining", 0)
            seconds_remaining = session_info.get("seconds_remaining", 0)
            if minutes_remaining > 5:
                st.caption(f"Session expires in {minutes_remaining} min")
            elif minutes_remaining > 0:
                secs = seconds_remaining % 60
                st.warning(f"Session expires in {minutes_remaining}:{secs:02d}")
            else:
                st.error(f"Session expires in {seconds_remaining}s")

        if st.button("Logout", use_container_width=True):
            client.logout()
            st.rerun()

        st.markdown("---")

        # Tracing status
        status = client.get_tracing_status()
        if status:
            if status.get("enabled"):
                st.success("Tracing Active")
                st.caption(f"Service: {status.get('service_name', 'unknown')}")
                st.caption(f"Sample rate: {status.get('sample_rate', 1.0)*100:.0f}%")
                st.caption(f"Retention: {status.get('retention_hours', 24)}h")
            else:
                st.warning("Tracing Disabled")
        else:
            st.error("Service Unavailable")


def render_summary(client) -> None:
    """Render traces summary section."""
    summary = client.get_traces_summary()

    if not summary:
        return

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Total Traces", f"{summary.get('total_traces', 0):,}")

    with col2:
        st.metric("Last Hour", summary.get("traces_last_hour", 0))

    with col3:
        error_rate = summary.get("error_rate", 0)
        st.metric(
            "Error Rate",
            f"{error_rate:.1f}%",
            delta="errors" if error_rate > 5 else None,
            delta_color="inverse" if error_rate > 5 else "off",
        )

    with col4:
        avg_duration = summary.get("avg_duration_ms", 0)
        st.metric("Avg Duration", format_duration(avg_duration))

    with col5:
        p95 = summary.get("p95_duration_ms", 0)
        st.metric("P95 Duration", format_duration(p95))

    st.caption(
        f"P50: {format_duration(summary.get('p50_duration_ms', 0))} | "
        f"P99: {format_duration(summary.get('p99_duration_ms', 0))} | "
        f"Unique routes: {summary.get('unique_routes', 0)}"
    )


def render_trace_list(client) -> None:
    """Render the trace list."""
    st.subheader("Recent Traces")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        hours = st.selectbox(
            "Time Range",
            [1, 2, 6, 12, 24],
            format_func=lambda x: f"{x}h",
            key="trace_hours",
        )

    with col2:
        http_method = st.selectbox(
            "HTTP Method",
            [None, "GET", "POST", "PUT", "DELETE", "PATCH"],
            format_func=lambda x: "All" if x is None else x,
            key="trace_method",
        )

    with col3:
        has_errors = st.selectbox(
            "Status",
            [None, True, False],
            format_func=lambda x: "All" if x is None else ("Errors Only" if x else "Success Only"),
            key="trace_errors",
        )

    with col4:
        limit = st.selectbox("Show", [25, 50, 100], index=1, key="trace_limit")

    traces = client.list_traces(
        hours=hours,
        limit=limit,
        http_method=http_method,
        has_errors=has_errors,
    )

    if not traces:
        st.info("No traces found for the selected filters.")
        return

    # Build dataframe
    df_data = []
    for trace in traces:
        start_time = trace.get("start_time", "")
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except ValueError:
            time_str = start_time

        df_data.append({
            "trace_id": trace.get("trace_id", ""),
            "Time": time_str,
            "Method": trace.get("http_method", "-"),
            "Route": trace.get("http_route", trace.get("root_span_name", "-")),
            "Status": trace.get("http_status_code", "-"),
            "Duration": format_duration(trace.get("total_duration_ms")),
            "Spans": trace.get("span_count", 0),
            "Error": "❌" if trace.get("has_errors") else "✓",
        })

    df = pd.DataFrame(df_data)

    # Display as interactive table
    selected = st.dataframe(
        df.drop(columns=["trace_id"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    # Show trace details if selected
    if selected and selected.selection and selected.selection.rows:
        selected_idx = selected.selection.rows[0]
        trace_id = df_data[selected_idx]["trace_id"]

        st.markdown("---")
        render_trace_details(client, trace_id)


def render_trace_details(client, trace_id: str) -> None:
    """Render detailed trace view with waterfall."""
    trace = client.get_trace(trace_id)

    if not trace:
        st.error("Failed to load trace details")
        return

    st.subheader(f"Trace: {trace.get('root_span_name', 'Unknown')}")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"**Trace ID:** `{trace_id[:16]}...`")

    with col2:
        st.markdown(f"**Duration:** {format_duration(trace.get('total_duration_ms'))}")

    with col3:
        st.markdown(f"**Spans:** {trace.get('span_count', 0)}")

    with col4:
        status = "❌ Error" if trace.get("has_errors") else "✓ Success"
        st.markdown(f"**Status:** {status}")

    # HTTP info
    http_info = []
    if trace.get("http_method"):
        http_info.append(f"**{trace.get('http_method')}** {trace.get('http_route', '')}")
    if trace.get("http_status_code"):
        http_info.append(f"Status: {trace.get('http_status_code')}")
    if http_info:
        st.markdown(" | ".join(http_info))

    # Waterfall chart
    spans = trace.get("spans", [])
    if spans:
        st.markdown("### Span Waterfall")

        # Find trace start time
        span_starts = []
        for span in spans:
            start_time = span.get("start_time", "")
            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                span_starts.append(dt)
            except ValueError:
                pass

        if span_starts:
            trace_start = min(span_starts)

            # Build waterfall data
            waterfall_data = []
            for span in spans:
                start_time = span.get("start_time", "")
                try:
                    span_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    offset_ms = (span_start - trace_start).total_seconds() * 1000
                except ValueError:
                    offset_ms = 0

                duration_ms = span.get("duration_ms", 0) or 0

                waterfall_data.append({
                    "name": span.get("name", "unknown"),
                    "offset": offset_ms,
                    "duration": duration_ms,
                    "status": span.get("status", "unset"),
                    "kind": span.get("kind", "internal"),
                })

            # Create Gantt-like chart
            fig = go.Figure()

            for i, item in enumerate(waterfall_data):
                color = status_color(item["status"])

                fig.add_trace(go.Bar(
                    y=[item["name"]],
                    x=[item["duration"]],
                    base=[item["offset"]],
                    orientation="h",
                    marker_color=color,
                    text=f"{item['duration']:.0f}ms",
                    textposition="inside",
                    hovertemplate=(
                        f"<b>{item['name']}</b><br>"
                        f"Duration: {item['duration']:.0f}ms<br>"
                        f"Offset: {item['offset']:.0f}ms<br>"
                        f"Status: {item['status']}<br>"
                        f"Kind: {item['kind']}<extra></extra>"
                    ),
                ))

            fig.update_layout(
                title="Span Timeline",
                xaxis_title="Time (ms)",
                yaxis_title="",
                showlegend=False,
                height=max(200, len(waterfall_data) * 30 + 100),
                barmode="overlay",
            )

            st.plotly_chart(fig, use_container_width=True)

        # Span table
        st.markdown("### Span Details")
        span_df_data = []
        for span in spans:
            span_df_data.append({
                "Name": span.get("name", ""),
                "Kind": span.get("kind", "internal"),
                "Status": span.get("status", "unset"),
                "Duration": format_duration(span.get("duration_ms")),
                "Parent": (span.get("parent_span_id") or "-")[:8],
            })

        st.dataframe(
            pd.DataFrame(span_df_data),
            use_container_width=True,
            hide_index=True,
        )


def render_route_stats(client) -> None:
    """Render route statistics."""
    st.subheader("Route Statistics")

    col1, col2 = st.columns(2)
    with col1:
        hours = st.selectbox("Time Range", [1, 6, 12, 24], key="route_hours")
    with col2:
        limit = st.selectbox("Top Routes", [10, 25, 50], key="route_limit")

    stats = client.get_route_stats(hours=hours, limit=limit)

    if not stats:
        st.info("No route statistics available.")
        return

    # Display table
    df_data = []
    for stat in stats:
        df_data.append({
            "Method": stat.get("method", "-"),
            "Route": stat.get("route", "-"),
            "Requests": stat.get("request_count", 0),
            "Errors": stat.get("error_count", 0),
            "Error Rate": f"{stat.get('error_rate', 0):.1f}%",
            "Avg": format_duration(stat.get("avg_duration_ms")),
            "P50": format_duration(stat.get("p50_duration_ms")),
            "P95": format_duration(stat.get("p95_duration_ms")),
        })

    st.dataframe(
        pd.DataFrame(df_data),
        use_container_width=True,
        hide_index=True,
    )

    # Chart: Request count by route
    if df_data:
        chart_df = pd.DataFrame(df_data)
        chart_df["Label"] = chart_df["Method"] + " " + chart_df["Route"]

        fig = px.bar(
            chart_df.head(10),
            x="Requests",
            y="Label",
            orientation="h",
            title="Top Routes by Request Count",
        )
        fig.update_layout(yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)


def render_service_map(client) -> None:
    """Render service dependency map."""
    st.subheader("Service Map")

    hours = st.selectbox("Time Range", [1, 6, 12, 24], key="map_hours")

    service_map = client.get_service_map(hours=hours)

    if not service_map:
        st.info("No service map data available.")
        return

    nodes = service_map.get("nodes", [])
    edges = service_map.get("edges", [])

    if not nodes:
        st.info("No services found in the selected time period.")
        return

    # Display as table for now (network visualization would require additional libraries)
    st.markdown("### Services")

    nodes_df_data = []
    for node in nodes:
        error_rate = (
            node.get("error_count", 0) / node.get("request_count", 1) * 100
            if node.get("request_count", 0) > 0 else 0
        )
        nodes_df_data.append({
            "Service": node.get("service_name", ""),
            "Requests": node.get("request_count", 0),
            "Errors": node.get("error_count", 0),
            "Error Rate": f"{error_rate:.1f}%",
            "Avg Duration": format_duration(node.get("avg_duration_ms")),
        })

    st.dataframe(
        pd.DataFrame(nodes_df_data),
        use_container_width=True,
        hide_index=True,
    )

    if edges:
        st.markdown("### Service Dependencies")

        edges_df_data = []
        for edge in edges:
            edges_df_data.append({
                "From": edge.get("source", ""),
                "To": edge.get("target", ""),
                "Requests": edge.get("request_count", 0),
                "Errors": edge.get("error_count", 0),
                "Avg Duration": format_duration(edge.get("avg_duration_ms")),
            })

        st.dataframe(
            pd.DataFrame(edges_df_data),
            use_container_width=True,
            hide_index=True,
        )


def main() -> None:
    """Trace Explorer main page."""
    require_auth()
    render_sidebar()

    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Trace Explorer")
    with col2:
        if st.button("Refresh", use_container_width=True, key="refresh_traces"):
            st.rerun()

    st.markdown("Distributed tracing visualization and analysis")

    client = get_api_client()

    status = client.get_tracing_status()

    if not status or not status.get("enabled"):
        st.warning(
            "Tracing is disabled. "
            "Set `TRACING_ENABLED=true` and install OpenTelemetry packages to enable."
        )
        return

    # Summary
    render_summary(client)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Traces", "Route Stats", "Service Map"])

    with tab1:
        render_trace_list(client)

    with tab2:
        render_route_stats(client)

    with tab3:
        render_service_map(client)


if __name__ == "__main__":
    main()
