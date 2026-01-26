"""Self-healing remediation action models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class ActionStatus(str, Enum):
    """Status of a remediation action."""

    PENDING = "pending"  # Awaiting user approval
    APPROVED = "approved"  # User approved, ready to execute
    REJECTED = "rejected"  # User rejected
    EXECUTING = "executing"  # Currently executing
    EXECUTED = "executed"  # Successfully completed
    FAILED = "failed"  # Execution failed


class ActionType(str, Enum):
    """Types of remediation actions."""

    RESTART_CONTAINER = "restart_container"
    START_CONTAINER = "start_container"
    STOP_CONTAINER = "stop_container"


class RemediationAction(BaseModel):
    """Remediation action suggested by the monitoring system.

    IMPORTANT: Actions are NEVER auto-executed. Users must:
    1. Review the pending action
    2. Explicitly APPROVE it
    3. Explicitly click EXECUTE
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=_utc_now)

    # Source insight (if triggered by monitoring)
    insight_id: str | None = None
    insight_title: str | None = None
    insight_severity: str | None = None

    # Action details
    action_type: ActionType
    target_endpoint_id: int
    target_endpoint_name: str | None = None
    target_container_id: str
    target_container_name: str

    # Status (starts as PENDING, requires explicit user action)
    status: ActionStatus = ActionStatus.PENDING

    # Approval tracking
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    # Execution tracking
    executed_at: datetime | None = None
    execution_result: str | None = None
    error_message: str | None = None

    # Human-readable descriptions
    title: str
    description: str
    rationale: str  # Why this action is suggested


class ActionHistory(BaseModel):
    """Summary of action history."""

    total_actions: int = 0
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    executed_count: int = 0
    failed_count: int = 0
    actions_last_24h: int = 0
    success_rate: float = 0.0


class ActionApprovalRequest(BaseModel):
    """Request to approve a remediation action."""

    approved_by: str


class ActionRejectionRequest(BaseModel):
    """Request to reject a remediation action."""

    rejected_by: str
    reason: str | None = None


class ActionExecutionResult(BaseModel):
    """Result of executing a remediation action."""

    action_id: str
    success: bool
    message: str
    executed_at: datetime = Field(default_factory=_utc_now)
    error: str | None = None


__all__ = [
    "ActionApprovalRequest",
    "ActionExecutionResult",
    "ActionHistory",
    "ActionRejectionRequest",
    "ActionStatus",
    "ActionType",
    "RemediationAction",
]
