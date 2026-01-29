"""Structured audit logging for security-sensitive operations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class AuditLogger:
    """Emit structured JSON audit log entries for security events."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("audit")

    def _emit(self, event_type: str, **details: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **details,
        }
        self._logger.info(json.dumps(entry, default=str))

    # --- Authentication events ---

    def log_login_success(self, username: str, ip: str, auth_method: str) -> None:
        self._emit(
            "login_success",
            username=username,
            ip_address=ip,
            auth_method=auth_method,
        )

    def log_login_failure(self, username: str, ip: str, reason: str) -> None:
        self._emit(
            "login_failure",
            username=username,
            ip_address=ip,
            reason=reason,
        )

    def log_logout(self, username: str, ip: str) -> None:
        self._emit("logout", username=username, ip_address=ip)

    def log_session_expired(self, username: str) -> None:
        self._emit("session_expired", username=username)

    def log_oidc_callback(
        self, username: str, *, success: bool, error: str | None = None
    ) -> None:
        self._emit(
            "oidc_callback",
            username=username,
            success=success,
            error=error,
        )

    # --- Remediation events ---

    def log_remediation_approved(
        self, action_id: str, approved_by: str, target: str
    ) -> None:
        self._emit(
            "remediation_approved",
            action_id=action_id,
            approved_by=approved_by,
            target=target,
        )

    def log_remediation_executed(
        self, action_id: str, executor: str, target: str, result: str
    ) -> None:
        self._emit(
            "remediation_executed",
            action_id=action_id,
            executor=executor,
            target=target,
            result=result,
        )

    # --- WebSocket events ---

    def log_websocket_connect(self, username: str, endpoint: str) -> None:
        self._emit(
            "websocket_connect",
            username=username,
            endpoint=endpoint,
        )

    def log_websocket_rejected(self, ip: str, endpoint: str, reason: str) -> None:
        self._emit(
            "websocket_rejected",
            ip_address=ip,
            endpoint=endpoint,
            reason=reason,
        )


_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger singleton."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def reset_audit_logger() -> None:
    """Reset the audit logger (for testing)."""
    global _audit_logger
    _audit_logger = None


__all__ = [
    "AuditLogger",
    "get_audit_logger",
    "reset_audit_logger",
]
