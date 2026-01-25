"""Self-Healing - Remediation action management with user approval.

IMPORTANT: Actions are NEVER auto-executed. Users must:
1. Review pending actions
2. Explicitly APPROVE
3. Explicitly EXECUTE
"""

from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client
from shared import require_auth


st.set_page_config(
    page_title="Self-Healing - Portainer Dashboard",
    page_icon="🔧",
    layout="wide",
)


def status_color(status: str) -> str:
    """Get color for action status."""
    colors = {
        "pending": "#ffa500",
        "approved": "#1f77b4",
        "rejected": "#888888",
        "executing": "#9467bd",
        "executed": "#2ca02c",
        "failed": "#ff4b4b",
    }
    return colors.get(status.lower(), "#888888")


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


def render_sidebar() -> None:
    """Render sidebar with status info."""
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

        # Remediation status
        status = client.get_remediation_status()
        if status:
            if status.get("enabled"):
                st.success("Self-Healing Active")
                pending = status.get("pending_actions", 0)
                approved = status.get("approved_actions", 0)
                if pending > 0:
                    st.warning(f"{pending} pending action(s)")
                if approved > 0:
                    st.info(f"{approved} ready to execute")
            else:
                st.warning("Self-Healing Disabled")
        else:
            st.error("Service Unavailable")

        st.markdown("---")
        st.markdown("### About Self-Healing")
        st.markdown("""
        Actions are **NEVER** auto-executed.

        **Workflow:**
        1. Monitor suggests actions
        2. You **review** and **approve**
        3. You **execute** when ready
        """)


def render_summary(client) -> None:
    """Render summary statistics."""
    summary = client.get_actions_summary()

    if not summary:
        return

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        pending = summary.get("pending_count", 0)
        st.metric(
            "Pending",
            pending,
            delta="awaiting approval" if pending > 0 else None,
            delta_color="off",
        )

    with col2:
        st.metric("Approved", summary.get("approved_count", 0))

    with col3:
        st.metric("Executed", summary.get("executed_count", 0))

    with col4:
        st.metric("Failed", summary.get("failed_count", 0))

    with col5:
        success_rate = summary.get("success_rate", 0)
        st.metric("Success Rate", f"{success_rate:.1f}%")

    st.caption(
        f"Total: {summary.get('total_actions', 0)} actions | "
        f"Last 24h: {summary.get('actions_last_24h', 0)}"
    )


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

    # Format timestamp
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
                    if st.button(
                        "✅ Approve",
                        key=f"approve_{action_id}",
                        use_container_width=True,
                    ):
                        result = client.approve_action(action_id, username)
                        if result and result.get("success"):
                            st.success("Action approved!")
                            st.rerun()
                        else:
                            st.error("Failed to approve action")

                with col_b:
                    if st.button(
                        "❌ Reject",
                        key=f"reject_{action_id}",
                        use_container_width=True,
                    ):
                        result = client.reject_action(action_id, username)
                        if result and result.get("success"):
                            st.info("Action rejected")
                            st.rerun()
                        else:
                            st.error("Failed to reject action")

            elif status == "approved":
                col_a, col_b = st.columns([1, 3])

                with col_a:
                    if st.button(
                        "🚀 Execute Now",
                        key=f"execute_{action_id}",
                        type="primary",
                        use_container_width=True,
                    ):
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


def render_pending_actions(client, username: str) -> None:
    """Render pending actions tab."""
    st.subheader("Pending Actions")
    st.markdown("These actions have been suggested by the monitoring system and require your approval.")

    actions = client.get_pending_actions()

    if not actions:
        st.success("No pending actions. The system is running smoothly!")
        return

    for action in actions:
        render_action_card(action, client, username)


def render_approved_actions(client, username: str) -> None:
    """Render approved actions tab."""
    st.subheader("Approved Actions")
    st.markdown("These actions have been approved and are ready to execute.")

    actions = client.get_approved_actions()

    if not actions:
        st.info("No actions are currently approved. Approve pending actions first.")
        return

    for action in actions:
        render_action_card(action, client, username)


def render_history(client, username: str) -> None:
    """Render action history tab."""
    st.subheader("Action History")

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            [None, "executed", "failed", "rejected", "pending", "approved"],
            format_func=lambda x: "All" if x is None else x.title(),
            key="history_status",
        )
    with col2:
        limit = st.selectbox("Show", [25, 50, 100], index=1, key="history_limit")

    actions = client.get_actions_history(status=status_filter, limit=limit)

    if not actions:
        st.info("No action history found.")
        return

    # Build dataframe
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

    # Export
    if df_data:
        export_df = pd.DataFrame(actions)
        csv = export_df.to_csv(index=False)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "Download History CSV",
            csv,
            f"remediation_history_{timestamp_str}.csv",
            "text/csv",
        )


def main() -> None:
    """Self-Healing main page."""
    require_auth()
    render_sidebar()

    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Self-Healing")
    with col2:
        if st.button("Refresh", use_container_width=True, key="refresh_healing"):
            st.rerun()

    st.markdown("Remediation actions with user approval workflow")

    client = get_api_client()
    username = st.session_state.get("username", "user")

    status = client.get_remediation_status()

    if not status or not status.get("enabled"):
        st.warning(
            "Self-healing is disabled. "
            "Set `REMEDIATION_ENABLED=true` to enable."
        )
        return

    # Summary
    render_summary(client)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["⏳ Pending", "✅ Ready to Execute", "📜 History"])

    with tab1:
        render_pending_actions(client, username)

    with tab2:
        render_approved_actions(client, username)

    with tab3:
        render_history(client, username)


if __name__ == "__main__":
    main()
