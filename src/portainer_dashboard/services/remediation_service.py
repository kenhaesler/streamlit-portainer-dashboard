"""Self-healing remediation service with user approval requirement.

CRITICAL: This service NEVER auto-executes actions. It only:
1. Suggests actions based on monitoring insights
2. Stores pending actions for user review
3. Executes actions ONLY after explicit user approval + execute command
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from portainer_dashboard.config import PortainerEnvironmentSettings, get_settings
from portainer_dashboard.models.monitoring import MonitoringInsight
from portainer_dashboard.models.remediation import (
    ActionExecutionResult,
    ActionStatus,
    ActionType,
    RemediationAction,
)
from portainer_dashboard.services.actions_store import SQLiteActionsStore, get_actions_store
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    create_portainer_client,
)

LOGGER = logging.getLogger(__name__)


# Mapping of insight patterns to suggested actions
INSIGHT_ACTION_MAPPING: dict[str, dict] = {
    # Availability issues
    "unhealthy": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "Container is unhealthy according to health check. Restarting may resolve the issue.",
    },
    "exited with error": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "Container exited with an error code. Restarting may recover the service.",
    },
    "restarting": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "Container is in a restart loop. A clean restart may help break the cycle.",
    },
    # Log-based issues
    "out of memory": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "OOM errors detected. Restarting will free memory (consider increasing limits).",
    },
    "oom": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "OOM killer activity detected. Restart to recover.",
    },
    "memory issues": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "Memory exhaustion detected. Restart may temporarily resolve the issue.",
    },
    "connection errors": {
        "action_type": ActionType.RESTART_CONTAINER,
        "rationale": "Connection failures detected. Restart may re-establish connections.",
    },
}


class RemediationService:
    """Service for suggesting and executing remediation actions.

    IMPORTANT: Actions are NEVER auto-executed. The workflow is:
    1. Insights trigger action suggestions (status=PENDING)
    2. Users must explicitly APPROVE actions
    3. Users must explicitly EXECUTE approved actions
    """

    def __init__(self, actions_store: SQLiteActionsStore) -> None:
        self._actions_store = actions_store
        self._settings = get_settings()

    @property
    def is_enabled(self) -> bool:
        """Check if remediation is enabled."""
        return self._settings.remediation.enabled

    @property
    def auto_suggest(self) -> bool:
        """Check if auto-suggestion is enabled."""
        return self._settings.remediation.auto_suggest

    def suggest_action_from_insight(
        self,
        insight: MonitoringInsight,
        endpoint_id: int,
        endpoint_name: str | None,
        container_id: str,
        container_name: str,
    ) -> RemediationAction | None:
        """Suggest a remediation action based on a monitoring insight.

        Returns:
            A PENDING action if suggestion is appropriate, None otherwise.
        """
        if not self.is_enabled or not self.auto_suggest:
            return None

        # Check insight category - only suggest for actionable categories
        actionable_categories = {"availability", "logs", "resource"}
        if insight.category.lower() not in actionable_categories:
            LOGGER.debug(
                "Insight category %s not actionable for remediation",
                insight.category,
            )
            return None

        # Find matching action pattern
        title_lower = insight.title.lower()
        description_lower = insight.description.lower()
        combined = f"{title_lower} {description_lower}"

        action_config = None
        for pattern, config in INSIGHT_ACTION_MAPPING.items():
            if pattern in combined:
                action_config = config
                break

        if action_config is None:
            LOGGER.debug("No action pattern matched for insight: %s", insight.title)
            return None

        action_type: ActionType = action_config["action_type"]

        # Check if there's already a pending action for this container
        if self._actions_store.has_pending_action_for_container(container_id, action_type):
            LOGGER.debug(
                "Pending %s action already exists for %s",
                action_type.value,
                container_name,
            )
            return None

        # Create the action suggestion (status=PENDING)
        action = RemediationAction(
            insight_id=insight.id,
            insight_title=insight.title,
            insight_severity=insight.severity.value,
            action_type=action_type,
            target_endpoint_id=endpoint_id,
            target_endpoint_name=endpoint_name,
            target_container_id=container_id,
            target_container_name=container_name,
            status=ActionStatus.PENDING,
            title=f"{action_type.value.replace('_', ' ').title()}: {container_name}",
            description=f"Suggested action based on monitoring insight: {insight.title}",
            rationale=action_config["rationale"],
        )

        self._actions_store.create_action(action)
        LOGGER.info(
            "Created pending action suggestion: %s for %s",
            action_type.value,
            container_name,
        )

        return action

    def approve_action(self, action_id: str, approved_by: str) -> bool:
        """Approve an action for execution.

        This does NOT execute the action - the user must still call execute_action.
        """
        success = self._actions_store.approve_action(action_id, approved_by)
        if success:
            LOGGER.info("Action %s approved by %s (not yet executed)", action_id, approved_by)
        return success

    def reject_action(
        self, action_id: str, rejected_by: str, reason: str | None = None
    ) -> bool:
        """Reject an action."""
        return self._actions_store.reject_action(action_id, rejected_by, reason)

    async def execute_action(self, action_id: str) -> ActionExecutionResult:
        """Execute an APPROVED action.

        IMPORTANT: Only executes actions that have been explicitly approved.
        Returns an error if the action is not in APPROVED status.
        """
        action = self._actions_store.get_action(action_id)

        if action is None:
            return ActionExecutionResult(
                action_id=action_id,
                success=False,
                message="Action not found",
                error="Action with this ID does not exist",
            )

        if action.status != ActionStatus.APPROVED:
            return ActionExecutionResult(
                action_id=action_id,
                success=False,
                message=f"Action is not approved (status: {action.status.value})",
                error="Only approved actions can be executed. Approve the action first.",
            )

        # Mark as executing
        if not self._actions_store.mark_executing(action_id):
            return ActionExecutionResult(
                action_id=action_id,
                success=False,
                message="Failed to start execution",
                error="Could not transition action to executing state",
            )

        # Find the right Portainer environment
        environments = self._settings.portainer.get_configured_environments()
        client: AsyncPortainerClient | None = None
        env: PortainerEnvironmentSettings | None = None

        for e in environments:
            client = create_portainer_client(e)
            try:
                async with client:
                    endpoints = await client.list_all_endpoints()
                    for ep in endpoints:
                        ep_id = ep.get("Id") or ep.get("id")
                        if ep_id and int(ep_id) == action.target_endpoint_id:
                            env = e
                            break
                    if env:
                        break
            except PortainerAPIError:
                continue

        if env is None:
            error = f"Endpoint {action.target_endpoint_id} not found"
            self._actions_store.mark_executed(action_id, "Failed", error)
            return ActionExecutionResult(
                action_id=action_id,
                success=False,
                message="Endpoint not found",
                error=error,
            )

        # Execute the action
        try:
            client = create_portainer_client(env)
            async with client:
                if action.action_type == ActionType.RESTART_CONTAINER:
                    result = await client.restart_container(
                        action.target_endpoint_id,
                        action.target_container_id,
                    )
                elif action.action_type == ActionType.START_CONTAINER:
                    result = await client.start_container(
                        action.target_endpoint_id,
                        action.target_container_id,
                    )
                elif action.action_type == ActionType.STOP_CONTAINER:
                    result = await client.stop_container(
                        action.target_endpoint_id,
                        action.target_container_id,
                    )
                else:
                    raise ValueError(f"Unknown action type: {action.action_type}")

            message = f"Successfully executed {action.action_type.value}"
            self._actions_store.mark_executed(action_id, message)

            LOGGER.info(
                "Executed action %s: %s on %s",
                action_id,
                action.action_type.value,
                action.target_container_name,
            )

            return ActionExecutionResult(
                action_id=action_id,
                success=True,
                message=message,
            )

        except PortainerAPIError as exc:
            error = str(exc)
            self._actions_store.mark_executed(action_id, "Failed", error)

            LOGGER.error(
                "Failed to execute action %s: %s",
                action_id,
                error,
            )

            return ActionExecutionResult(
                action_id=action_id,
                success=False,
                message=f"Failed to execute {action.action_type.value}",
                error=error,
            )

    def get_pending_actions(self, limit: int = 100) -> list[RemediationAction]:
        """Get all pending actions awaiting approval."""
        return self._actions_store.get_pending_actions(limit)

    def get_approved_actions(self, limit: int = 100) -> list[RemediationAction]:
        """Get approved actions ready for execution."""
        return self._actions_store.get_approved_actions(limit)

    def get_action(self, action_id: str) -> RemediationAction | None:
        """Get a specific action by ID."""
        return self._actions_store.get_action(action_id)

    def get_history(
        self,
        status: ActionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RemediationAction]:
        """Get action history."""
        return self._actions_store.get_actions_history(
            status=status, limit=limit, offset=offset
        )


_remediation_service: RemediationService | None = None


async def get_remediation_service() -> RemediationService:
    """Get or create the remediation service singleton."""
    global _remediation_service
    if _remediation_service is None:
        store = await get_actions_store()
        _remediation_service = RemediationService(store)
    return _remediation_service


__all__ = [
    "RemediationService",
    "get_remediation_service",
]
