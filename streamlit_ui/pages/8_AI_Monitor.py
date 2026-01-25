"""AI Monitor - Real-time infrastructure monitoring insights."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth


st.set_page_config(
    page_title="AI Monitor - Portainer Dashboard",
    page_icon="🤖",
    layout="wide",
)


def severity_color(severity: str) -> str:
    """Get the color for a severity level."""
    colors = {
        "critical": "#ff4b4b",
        "warning": "#ffa500",
        "info": "#1f77b4",
        "optimization": "#2ca02c",
    }
    return colors.get(severity.lower(), "#888888")


def severity_icon(severity: str) -> str:
    """Get the icon for a severity level."""
    icons = {
        "critical": "🔴",
        "warning": "🟡",
        "info": "🔵",
        "optimization": "🟢",
    }
    return icons.get(severity.lower(), "⚪")


def category_icon(category: str) -> str:
    """Get the icon for an insight category."""
    icons = {
        "resource": "📊",
        "security": "🔒",
        "availability": "🌐",
        "image": "📦",
        "optimization": "⚡",
    }
    return icons.get(category.lower(), "📋")


def render_sidebar() -> None:
    """Render sidebar with monitoring controls."""
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

        st.markdown("### Monitoring Controls")

        if st.button("🔄 Trigger Analysis", use_container_width=True):
            with st.spinner("Running analysis..."):
                result = client.post("/api/v1/monitoring/trigger")
                if result and result.get("success"):
                    st.success(f"Analysis complete: {result.get('insights_count', 0)} insights")
                    st.session_state["refresh_insights"] = True
                    st.rerun()
                else:
                    st.error("Analysis failed")

        if st.button("🗑️ Clear Insights", use_container_width=True):
            client._request("DELETE", "/api/v1/monitoring/insights")
            st.session_state["refresh_insights"] = True
            st.rerun()

        st.markdown("---")
        st.markdown("### Service Status")

        status = client.get("/api/v1/monitoring/status")
        if status:
            if status.get("enabled"):
                st.success("🟢 Monitoring Active")
                st.caption(f"Interval: {status.get('interval_minutes', 5)} min")
                if status.get("last_analysis"):
                    st.caption(f"Last run: {status.get('last_analysis', 'N/A')[:19]}")
            else:
                st.warning("🟡 Monitoring Disabled")
        else:
            st.error("🔴 Service Unavailable")


def render_insight_card(insight: dict[str, Any]) -> None:
    """Render a single insight as a card."""
    severity = insight.get("severity", "info")
    category = insight.get("category", "unknown")
    title = insight.get("title", "Unknown Issue")
    description = insight.get("description", "")
    affected = insight.get("affected_resources", [])
    action = insight.get("recommended_action")
    timestamp = insight.get("timestamp", "")

    if isinstance(timestamp, str) and timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp_str = timestamp
    else:
        timestamp_str = ""

    with st.container():
        col1, col2 = st.columns([0.05, 0.95])

        with col1:
            st.markdown(f"### {severity_icon(severity)}")

        with col2:
            st.markdown(f"**{category_icon(category)} {title}**")
            st.caption(f"{severity.upper()} | {category.upper()} | {timestamp_str}")

            if description:
                st.markdown(description)

            if affected:
                st.markdown(f"**Affected:** {', '.join(affected[:5])}")
                if len(affected) > 5:
                    st.caption(f"... and {len(affected) - 5} more")

            if action:
                with st.expander("Recommended Action"):
                    st.markdown(action)

        st.markdown("---")


def render_report_summary(report: dict[str, Any]) -> None:
    """Render the report summary section."""
    timestamp = report.get("timestamp", "")
    if isinstance(timestamp, str) and timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            timestamp_str = timestamp
    else:
        timestamp_str = "N/A"

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Endpoints Analyzed",
            report.get("endpoints_analyzed", 0),
        )

    with col2:
        st.metric(
            "Containers Analyzed",
            report.get("containers_analyzed", 0),
        )

    with col3:
        st.metric(
            "Security Issues",
            report.get("security_issues_found", 0),
            delta=None if report.get("security_issues_found", 0) == 0 else "found",
            delta_color="inverse" if report.get("security_issues_found", 0) > 0 else "off",
        )

    with col4:
        st.metric(
            "Outdated Images",
            report.get("outdated_images_found", 0),
        )

    st.caption(f"Last analysis: {timestamp_str}")

    if report.get("summary"):
        st.info(report["summary"])


def fetch_monitoring_status(client: Any) -> dict | None:
    """Fetch monitoring status from API."""
    return client.get("/api/v1/monitoring/status")


def fetch_latest_report(client: Any) -> dict | None:
    """Fetch latest report from API."""
    try:
        return client.get("/api/v1/monitoring/reports/latest")
    except Exception:
        return None


def fetch_insights(client: Any, limit: int = 50) -> list[dict]:
    """Fetch insights from API."""
    result = client.get("/api/v1/monitoring/insights", params={"limit": str(limit)})
    return result if isinstance(result, list) else []


def main() -> None:
    """AI Monitor main page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("🤖 AI Infrastructure Monitor")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_monitor"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("Real-time AI-powered monitoring insights for your infrastructure")

    client = get_api_client()

    status = fetch_monitoring_status(client)

    if status:
        if not status.get("enabled"):
            st.warning(
                "AI Monitoring is currently disabled. "
                "Set `MONITORING_ENABLED=true` to enable."
            )
            return

        tab1, tab2 = st.tabs(["📊 Dashboard", "📜 All Insights"])

        with tab1:
            report = fetch_latest_report(client)

            if report:
                st.subheader("Latest Analysis Report")
                render_report_summary(report)

                insights = report.get("insights", [])
                if insights:
                    st.subheader(f"Insights ({len(insights)})")

                    severity_filter = st.multiselect(
                        "Filter by Severity",
                        ["critical", "warning", "info", "optimization"],
                        default=["critical", "warning"],
                        key="severity_filter_dashboard",
                    )

                    filtered = [
                        i for i in insights
                        if i.get("severity", "").lower() in severity_filter
                    ]

                    if filtered:
                        for insight in filtered:
                            render_insight_card(insight)
                    else:
                        st.info("No insights match the selected filters")
                else:
                    st.success("No issues detected in the latest analysis")
            else:
                st.info(
                    "No monitoring reports yet. "
                    "The first analysis will run shortly after startup, "
                    "or click 'Trigger Analysis' in the sidebar."
                )

        with tab2:
            st.subheader("Insight History")

            col1, col2 = st.columns(2)
            with col1:
                limit = st.selectbox(
                    "Show",
                    [25, 50, 100],
                    index=1,
                    key="insight_limit",
                )
            with col2:
                severity_filter = st.multiselect(
                    "Severity",
                    ["critical", "warning", "info", "optimization"],
                    default=["critical", "warning", "info", "optimization"],
                    key="severity_filter_history",
                )

            all_insights = fetch_insights(client, limit=limit)

            if all_insights:
                filtered = [
                    i for i in all_insights
                    if i.get("severity", "").lower() in severity_filter
                ]

                st.caption(f"Showing {len(filtered)} of {len(all_insights)} insights")

                # CSV Export
                if filtered:
                    export_data = []
                    for insight in filtered:
                        export_data.append({
                            "Timestamp": insight.get("timestamp", ""),
                            "Severity": insight.get("severity", ""),
                            "Category": insight.get("category", ""),
                            "Title": insight.get("title", ""),
                            "Description": insight.get("description", ""),
                            "Affected Resources": ", ".join(insight.get("affected_resources", [])[:10]),
                            "Recommended Action": insight.get("recommended_action", ""),
                        })
                    export_df = pd.DataFrame(export_data)
                    csv = export_df.to_csv(index=False)
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        "📥 Download Insights CSV",
                        csv,
                        f"monitoring_insights_{timestamp_str}.csv",
                        "text/csv",
                        use_container_width=False,
                    )

                for insight in filtered:
                    render_insight_card(insight)
            else:
                st.info("No insights recorded yet")

    else:
        st.error("Failed to connect to monitoring service")

    st.markdown("---")
    st.caption(
        "Insights are automatically generated every few minutes. "
        "Use the 'Trigger Analysis' button in the sidebar for immediate results."
    )


if __name__ == "__main__":
    main()
