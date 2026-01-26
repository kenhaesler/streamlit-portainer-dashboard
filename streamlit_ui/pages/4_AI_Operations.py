"""AI Operations - Unified AI monitoring, metrics, and self-healing."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth


st.set_page_config(
    page_title="AI Operations - Portainer Dashboard",
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


def status_icon(status: str) -> str:
    """Get icon for action status."""
    icons = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
        "executing": "🔄",
        "executed": "✔️",
        "failed": "❗",
    }
    return icons.get(status.lower(), "❓")


def action_type_icon(action_type: str) -> str:
    """Get icon for action type."""
    icons = {
        "restart_container": "🔄",
        "start_container": "▶️",
        "stop_container": "⏹️",
    }
    return icons.get(action_type.lower(), "⚙️")


def format_bytes(bytes_value: float) -> str:
    """Format bytes into human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def render_sidebar() -> None:
    """Render sidebar with AI operations controls."""
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

        # Quick Actions
        st.markdown("### Quick Actions")

        if st.button("🔄 Trigger Analysis", use_container_width=True):
            with st.spinner("Running analysis..."):
                result = client.post("/api/v1/monitoring/trigger")
                if result and result.get("success"):
                    st.success(f"Analysis complete: {result.get('insights_count', 0)} insights")
                    st.rerun()
                else:
                    st.error("Analysis failed")

        if st.button("🗑️ Clear Insights", use_container_width=True):
            client._request("DELETE", "/api/v1/monitoring/insights")
            st.rerun()

        st.markdown("---")

        # Service Status
        st.markdown("### Service Status")

        monitoring_status = client.get("/api/v1/monitoring/status")
        if monitoring_status:
            if monitoring_status.get("enabled"):
                st.success("🟢 AI Monitoring Active")
                st.caption(f"Interval: {monitoring_status.get('interval_minutes', 5)} min")
            else:
                st.warning("🟡 AI Monitoring Disabled")
        else:
            st.error("🔴 Monitoring Unavailable")

        remediation_status = client.get_remediation_status()
        if remediation_status:
            if remediation_status.get("enabled"):
                st.success("🟢 Self-Healing Active")
                pending = remediation_status.get("pending_actions", 0)
                if pending > 0:
                    st.warning(f"{pending} pending action(s)")
            else:
                st.warning("🟡 Self-Healing Disabled")

        metrics_status = client.get_metrics_status()
        if metrics_status:
            if metrics_status.get("enabled"):
                st.success("🟢 Metrics Collection Active")
            else:
                st.warning("🟡 Metrics Disabled")


def main() -> None:
    """AI Operations main page."""
    require_auth()
    render_sidebar()

    # Title with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("🤖 AI Operations")
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_ai_ops"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("AI-powered monitoring, insights, metrics, and self-healing")

    client = get_api_client()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Insights Dashboard",
        "🔧 Self-Healing",
        "📈 Metrics",
        "🔍 Anomalies"
    ])

    with tab1:
        render_insights_tab(client)

    with tab2:
        render_self_healing_tab(client)

    with tab3:
        render_metrics_tab(client)

    with tab4:
        render_anomalies_tab(client)


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


def render_insights_tab(client) -> None:
    """Render the Insights Dashboard tab."""
    status = client.get("/api/v1/monitoring/status")

    if not status or not status.get("enabled"):
        st.warning(
            "AI Monitoring is currently disabled. "
            "Set `MONITORING_ENABLED=true` to enable."
        )
        return

    # Latest Report Summary
    report = None
    try:
        report = client.get("/api/v1/monitoring/reports/latest")
    except Exception:
        pass

    if report:
        st.subheader("Latest Analysis Report")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Endpoints Analyzed", report.get("endpoints_analyzed", 0))

        with col2:
            st.metric("Containers Analyzed", report.get("containers_analyzed", 0))

        with col3:
            security_issues = report.get("security_issues_found", 0)
            st.metric(
                "Security Issues",
                security_issues,
                delta="found" if security_issues > 0 else None,
                delta_color="inverse" if security_issues > 0 else "off",
            )

        with col4:
            st.metric("Outdated Images", report.get("outdated_images_found", 0))

        timestamp = report.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                st.caption(f"Last analysis: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except ValueError:
                st.caption(f"Last analysis: {timestamp}")

        if report.get("summary"):
            st.info(report["summary"])

        st.markdown("---")

        # Insights from latest report
        insights = report.get("insights", [])
        if insights:
            st.subheader(f"Insights ({len(insights)})")

            severity_filter = st.multiselect(
                "Filter by Severity",
                ["critical", "warning", "info", "optimization"],
                default=["critical", "warning"],
                key="insights_severity_filter",
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

    st.markdown("---")

    # All Insights History
    st.subheader("Insight History")

    col1, col2 = st.columns(2)
    with col1:
        limit = st.selectbox("Show", [25, 50, 100], index=1, key="history_limit")
    with col2:
        severity_filter_history = st.multiselect(
            "Severity",
            ["critical", "warning", "info", "optimization"],
            default=["critical", "warning", "info", "optimization"],
            key="history_severity_filter",
        )

    all_insights = client.get("/api/v1/monitoring/insights", params={"limit": str(limit)})
    all_insights = all_insights if isinstance(all_insights, list) else []

    if all_insights:
        filtered = [
            i for i in all_insights
            if i.get("severity", "").lower() in severity_filter_history
        ]

        st.caption(f"Showing {len(filtered)} of {len(all_insights)} insights")

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
            )

            for insight in filtered[:20]:  # Limit display
                render_insight_card(insight)
    else:
        st.info("No insights recorded yet")


def render_action_card(action: dict, client, username: str) -> None:
    """Render a single action card with approval/execute controls."""
    action_id = action.get("id", "")
    status = action.get("status", "pending")
    action_type = action.get("action_type", "")
    title = action.get("title", "Unknown Action")
    description = action.get("description", "")
    rationale = action.get("rationale", "")
    container_name = action.get("target_container_name", "")
    endpoint_name = action.get("target_endpoint_name", "")
    created_at = action.get("created_at", "")
    insight_title = action.get("insight_title", "")
    insight_severity = action.get("insight_severity", "")

    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            created_str = created_at
    else:
        created_str = "Unknown"

    with st.container():
        col1, col2 = st.columns([0.05, 0.95])

        with col1:
            st.markdown(f"### {status_icon(status)}")

        with col2:
            st.markdown(f"**{action_type_icon(action_type)} {title}**")
            st.caption(
                f"{status.upper()} | {action_type.replace('_', ' ').title()} | "
                f"Container: {container_name} | Endpoint: {endpoint_name}"
            )

            if insight_title:
                st.markdown(f"**Triggered by:** {insight_title} ({insight_severity})")

            if description:
                st.markdown(description)

            with st.expander("Rationale"):
                st.markdown(rationale)

            st.caption(f"Created: {created_str}")

            # Action buttons based on status
            if status == "pending":
                col_a, col_b, col_c = st.columns([1, 1, 2])

                with col_a:
                    if st.button("✅ Approve", key=f"approve_{action_id}", use_container_width=True):
                        result = client.approve_action(action_id, username)
                        if result and result.get("success"):
                            st.success("Action approved!")
                            st.rerun()
                        else:
                            st.error("Failed to approve action")

                with col_b:
                    if st.button("❌ Reject", key=f"reject_{action_id}", use_container_width=True):
                        result = client.reject_action(action_id, username)
                        if result and result.get("success"):
                            st.info("Action rejected")
                            st.rerun()
                        else:
                            st.error("Failed to reject action")

            elif status == "approved":
                col_a, col_b = st.columns([1, 3])

                with col_a:
                    if st.button("🚀 Execute Now", key=f"execute_{action_id}", type="primary", use_container_width=True):
                        with st.spinner("Executing..."):
                            result = client.execute_action(action_id)
                            if result:
                                if result.get("success"):
                                    st.success(f"Action executed: {result.get('message', '')}")
                                else:
                                    st.error(f"Execution failed: {result.get('error', 'Unknown error')}")
                                st.rerun()

            elif status == "executed":
                result = action.get("execution_result", "")
                if result:
                    st.success(f"Result: {result}")

            elif status == "failed":
                error = action.get("error_message", "")
                if error:
                    st.error(f"Error: {error}")

        st.markdown("---")


def render_self_healing_tab(client) -> None:
    """Render the Self-Healing tab."""
    username = st.session_state.get("username", "user")

    status = client.get_remediation_status()

    if not status or not status.get("enabled"):
        st.warning(
            "Self-healing is disabled. "
            "Set `REMEDIATION_ENABLED=true` to enable."
        )
        return

    # Summary
    summary = client.get_actions_summary()

    if summary:
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            pending = summary.get("pending_count", 0)
            st.metric("Pending", pending, delta="awaiting approval" if pending > 0 else None, delta_color="off")

        with col2:
            st.metric("Approved", summary.get("approved_count", 0))

        with col3:
            st.metric("Executed", summary.get("executed_count", 0))

        with col4:
            st.metric("Failed", summary.get("failed_count", 0))

        with col5:
            success_rate = summary.get("success_rate", 0)
            st.metric("Success Rate", f"{success_rate:.1f}%")

        st.caption(f"Total: {summary.get('total_actions', 0)} actions | Last 24h: {summary.get('actions_last_24h', 0)}")

    st.markdown("---")

    # Important notice
    st.info(
        "**Self-Healing Workflow:** Actions are NEVER auto-executed. "
        "You must: 1) Review pending actions, 2) Approve/Reject, 3) Execute when ready."
    )

    # Subtabs
    subtab1, subtab2, subtab3 = st.tabs(["⏳ Pending", "✅ Ready to Execute", "📜 History"])

    with subtab1:
        st.subheader("Pending Actions")
        actions = client.get_pending_actions()

        if not actions:
            st.success("No pending actions. The system is running smoothly!")
        else:
            for action in actions:
                render_action_card(action, client, username)

    with subtab2:
        st.subheader("Approved Actions")
        actions = client.get_approved_actions()

        if not actions:
            st.info("No actions are currently approved. Approve pending actions first.")
        else:
            for action in actions:
                render_action_card(action, client, username)

    with subtab3:
        st.subheader("Action History")

        col1, col2 = st.columns(2)
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                [None, "executed", "failed", "rejected", "pending", "approved"],
                format_func=lambda x: "All" if x is None else x.title(),
                key="action_history_status",
            )
        with col2:
            limit = st.selectbox("Show", [25, 50, 100], index=1, key="action_history_limit")

        actions = client.get_actions_history(status=status_filter, limit=limit)

        if not actions:
            st.info("No action history found.")
        else:
            df_data = []
            for action in actions:
                created_at = action.get("created_at", "")
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created_str = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    created_str = created_at

                df_data.append({
                    "Status": f"{status_icon(action.get('status', ''))} {action.get('status', '').title()}",
                    "Type": action.get("action_type", "").replace("_", " ").title(),
                    "Container": action.get("target_container_name", ""),
                    "Endpoint": action.get("target_endpoint_name", ""),
                    "Created": created_str,
                    "Insight": action.get("insight_title", ""),
                })

            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            if df_data:
                export_df = pd.DataFrame(actions)
                csv = export_df.to_csv(index=False)
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button("📥 Download History CSV", csv, f"remediation_history_{timestamp_str}.csv", "text/csv")


def render_metrics_tab(client) -> None:
    """Render the Metrics tab."""
    status = client.get_metrics_status()

    if not status or not status.get("enabled"):
        st.warning(
            "Metrics collection is disabled. "
            "Set `MONITORING_METRICS_ENABLED=true` to enable."
        )
        return

    # Dashboard overview
    dashboard = client.get_metrics_dashboard()

    if dashboard:
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Metrics", f"{dashboard.get('total_metrics', 0):,}")

        with col2:
            st.metric("Containers Tracked", dashboard.get("containers_tracked", 0))

        with col3:
            st.metric("Endpoints Tracked", dashboard.get("endpoints_tracked", 0))

        with col4:
            anomalies = dashboard.get("anomalies_detected_24h", 0)
            st.metric(
                "Anomalies (24h)",
                anomalies,
                delta="detected" if anomalies > 0 else None,
                delta_color="inverse" if anomalies > 0 else "off",
            )

        storage_bytes = dashboard.get("storage_size_bytes", 0)
        st.caption(f"Storage: {format_bytes(storage_bytes)}")
    else:
        st.info("No metrics data available yet. Metrics will be collected during the next monitoring cycle.")
        return

    st.markdown("---")

    # Container Metrics
    st.subheader("Container Metrics")

    containers = client.get_containers(include_stopped=False)

    if not containers:
        st.info("No running containers found.")
        return

    container_options = {}
    for c in containers:
        name = c.get("container_name", c.get("container_id", "unknown")[:12])
        container_id = c.get("container_id", "")
        endpoint_name = c.get("endpoint_name", "")
        label = f"{name} ({endpoint_name})"
        container_options[label] = container_id

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        selected_label = st.selectbox("Select Container", options=list(container_options.keys()), key="metrics_container")

    with col2:
        metric_type = st.selectbox(
            "Metric Type",
            ["cpu_percent", "memory_percent", "memory_usage"],
            format_func=lambda x: x.replace("_", " ").title(),
            key="metrics_type",
        )

    with col3:
        hours = st.selectbox(
            "Time Range",
            [1, 6, 12, 24, 48, 168],
            index=3,
            format_func=lambda x: f"{x}h" if x < 24 else f"{x//24}d",
            key="metrics_hours",
        )

    if selected_label and selected_label in container_options:
        container_id = container_options[selected_label]

        metrics = client.get_container_metrics(
            container_id,
            metric_type=metric_type,
            hours=hours,
            limit=2000,
        )

        if not metrics:
            st.info(f"No {metric_type.replace('_', ' ')} data available for this container.")
        else:
            df_data = []
            for m in metrics:
                timestamp = m.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    continue

                df_data.append({
                    "timestamp": dt,
                    "value": m.get("value", 0),
                })

            if df_data:
                df = pd.DataFrame(df_data)
                df = df.sort_values("timestamp")

                fig = px.line(
                    df,
                    x="timestamp",
                    y="value",
                    title=f"{metric_type.replace('_', ' ').title()} - {selected_label}",
                )

                if metric_type == "memory_usage":
                    fig.update_yaxes(title="Memory (bytes)")
                elif "percent" in metric_type:
                    fig.update_yaxes(title="Percentage (%)", range=[0, 100])

                fig.update_layout(xaxis_title="Time", hovermode="x unified", height=400)
                st.plotly_chart(fig, use_container_width=True)

                summary = client.get_container_metrics_summary(container_id, metric_type, hours)
                if summary:
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Current", f"{summary.get('latest_value', 0):.2f}")
                    with col2:
                        st.metric("Average", f"{summary.get('avg_value', 0):.2f}")
                    with col3:
                        st.metric("Min", f"{summary.get('min_value', 0):.2f}")
                    with col4:
                        st.metric("Max", f"{summary.get('max_value', 0):.2f}")
                    st.caption(f"Std Dev: {summary.get('std_dev', 0):.2f} | Samples: {summary.get('count', 0)}")


def render_anomalies_tab(client) -> None:
    """Render the Anomalies tab."""
    status = client.get_metrics_status()

    if not status or not status.get("enabled"):
        st.warning("Metrics collection is disabled. Anomaly detection requires metrics.")
        return

    st.subheader("Anomaly Detection")

    col1, col2 = st.columns([3, 1])
    with col1:
        hours = st.slider("Time range (hours)", 1, 168, 24, key="anomaly_hours")
    with col2:
        limit = st.selectbox("Max results", [25, 50, 100], index=1, key="anomaly_limit")

    anomalies = client.get_anomalies(hours=hours, limit=limit)

    if not anomalies:
        st.success("No anomalies detected in the selected time range.")
        return

    df_data = []
    for a in anomalies:
        timestamp = a.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp_str = timestamp

        df_data.append({
            "Time": timestamp_str,
            "Container": a.get("container_name", ""),
            "Metric": a.get("metric_type", "").replace("_", " ").title(),
            "Value": f"{a.get('current_value', 0):.2f}",
            "Expected": f"{a.get('expected_value', 0):.2f}",
            "Z-Score": f"{a.get('zscore', 0):.2f}",
            "Direction": a.get("direction", "").upper(),
            "Endpoint": a.get("endpoint_name", ""),
        })

    df = pd.DataFrame(df_data)

    def highlight_direction(row):
        if row["Direction"] == "HIGH":
            return ["background-color: rgba(255, 75, 75, 0.3)"] * len(row)
        elif row["Direction"] == "LOW":
            return ["background-color: rgba(75, 75, 255, 0.3)"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(highlight_direction, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    if df_data:
        csv = df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button("📥 Download Anomalies CSV", csv, f"anomalies_{timestamp_str}.csv", "text/csv")


if __name__ == "__main__":
    main()
