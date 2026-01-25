"""REST API endpoints for self-healing remediation actions.

IMPORTANT: Actions are NEVER auto-executed. Users must:
1. Review pending actions
2. Explicitly APPROVE
3. Explicitly EXECUTE
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.remediation import (
    ActionApprovalRequest,
    ActionExecutionResult,
    ActionHistory,
    ActionRejectionRequest,
    ActionStatus,
    RemediationAction,
)
from portainer_dashboard.services.actions_store import get_actions_store
from portainer_dashboard.services.remediation_service import get_remediation_service

router = APIRouter(prefix="/remediation", tags=["Remediation"])


@router.get("/status")
async def get_remediation_status() -> dict:
    """Get remediation service status and configuration."""
    settings = get_settings()
    store = await get_actions_store()
    summary = store.get_history_summary()

    return {
        "enabled": settings.remediation.enabled,
        "auto_suggest": settings.remediation.auto_suggest,
        "max_pending_actions": settings.remediation.max_pending_actions,
        "action_timeout_seconds": settings.remediation.action_timeout_seconds,
        "pending_actions": summary.pending_count,
        "approved_actions": summary.approved_count,
        "total_actions": summary.total_actions,
    }


@router.get("/actions/pending", response_model=list[RemediationAction])
async def get_pending_actions(
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RemediationAction]:
    """Get all pending actions awaiting user approval.

    These actions have been SUGGESTED by the monitoring system but
    have NOT been approved or executed.
    """
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    return service.get_pending_actions(limit)


@router.get("/actions/approved", response_model=list[RemediationAction])
async def get_approved_actions(
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RemediationAction]:
    """Get all approved actions ready for execution.

    These actions have been approved by a user but NOT yet executed.
    """
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    return service.get_approved_actions(limit)


@router.get("/actions/history", response_model=list[RemediationAction])
async def get_actions_history(
    status: ActionStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[RemediationAction]:
    """Get action history with optional filtering."""
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    return service.get_history(status=status, limit=limit, offset=offset)


@router.get("/actions/summary", response_model=ActionHistory)
async def get_actions_summary() -> ActionHistory:
    """Get summary statistics for actions."""
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    store = await get_actions_store()
    return store.get_history_summary()


@router.get("/actions/{action_id}", response_model=RemediationAction)
async def get_action(action_id: str) -> RemediationAction:
    """Get a specific action by ID."""
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    action = service.get_action(action_id)

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")

    return action


@router.post("/actions/{action_id}/approve", response_model=dict)
async def approve_action(
    action_id: str,
    request: ActionApprovalRequest,
) -> dict:
    """Approve a pending action.

    This marks the action as APPROVED but does NOT execute it.
    You must call the execute endpoint to actually perform the action.
    """
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    success = service.approve_action(action_id, request.approved_by)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to approve action. It may not exist or not be in pending status.",
        )

    return {
        "success": True,
        "message": f"Action {action_id} approved. Call /execute to perform the action.",
        "action_id": action_id,
        "approved_by": request.approved_by,
    }


@router.post("/actions/{action_id}/reject", response_model=dict)
async def reject_action(
    action_id: str,
    request: ActionRejectionRequest,
) -> dict:
    """Reject a pending action."""
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    success = service.reject_action(action_id, request.rejected_by, request.reason)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to reject action. It may not exist or not be in pending status.",
        )

    return {
        "success": True,
        "message": f"Action {action_id} rejected.",
        "action_id": action_id,
        "rejected_by": request.rejected_by,
    }


@router.post("/actions/{action_id}/execute", response_model=ActionExecutionResult)
async def execute_action(action_id: str) -> ActionExecutionResult:
    """Execute an APPROVED action.

    IMPORTANT: This endpoint only executes actions that have been
    explicitly approved. It will return an error if the action
    is not in APPROVED status.

    The action will:
    1. Verify the action is APPROVED
    2. Connect to the appropriate Portainer endpoint
    3. Execute the container action (restart/start/stop)
    4. Update the action status to EXECUTED or FAILED
    """
    settings = get_settings()

    if not settings.remediation.enabled:
        raise HTTPException(status_code=503, detail="Remediation is disabled")

    service = await get_remediation_service()
    result = await service.execute_action(action_id)

    return result


__all__ = ["router"]
