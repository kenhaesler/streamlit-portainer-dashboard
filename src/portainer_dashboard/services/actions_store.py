"""SQLite-backed storage for remediation actions."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.remediation import (
    ActionHistory,
    ActionStatus,
    ActionType,
    RemediationAction,
)

LOGGER = logging.getLogger(__name__)


class SQLiteActionsStore:
    """SQLite-backed storage for remediation actions."""

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
                    CREATE TABLE IF NOT EXISTS actions (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        insight_id TEXT,
                        insight_title TEXT,
                        insight_severity TEXT,
                        action_type TEXT NOT NULL,
                        target_endpoint_id INTEGER NOT NULL,
                        target_endpoint_name TEXT,
                        target_container_id TEXT NOT NULL,
                        target_container_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        approved_by TEXT,
                        approved_at TEXT,
                        rejected_by TEXT,
                        rejected_at TEXT,
                        rejection_reason TEXT,
                        executed_at TEXT,
                        execution_result TEXT,
                        error_message TEXT,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        rationale TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_actions_status
                    ON actions (status)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_actions_created
                    ON actions (created_at DESC)
                    """
                )
                connection.commit()
            LOGGER.info("Actions store initialized at %s", self._database_path)

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

    def _row_to_action(self, row: sqlite3.Row) -> RemediationAction:
        """Convert a database row to a RemediationAction."""
        return RemediationAction(
            id=row["id"],
            created_at=self._decode_datetime(row["created_at"]) or datetime.now(timezone.utc),
            insight_id=row["insight_id"],
            insight_title=row["insight_title"],
            insight_severity=row["insight_severity"],
            action_type=ActionType(row["action_type"]),
            target_endpoint_id=row["target_endpoint_id"],
            target_endpoint_name=row["target_endpoint_name"],
            target_container_id=row["target_container_id"],
            target_container_name=row["target_container_name"],
            status=ActionStatus(row["status"]),
            approved_by=row["approved_by"],
            approved_at=self._decode_datetime(row["approved_at"]),
            rejected_by=row["rejected_by"],
            rejected_at=self._decode_datetime(row["rejected_at"]),
            rejection_reason=row["rejection_reason"],
            executed_at=self._decode_datetime(row["executed_at"]),
            execution_result=row["execution_result"],
            error_message=row["error_message"],
            title=row["title"],
            description=row["description"],
            rationale=row["rationale"],
        )

    def create_action(self, action: RemediationAction) -> None:
        """Create a new remediation action (status defaults to PENDING)."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO actions (
                    id, created_at, insight_id, insight_title, insight_severity,
                    action_type, target_endpoint_id, target_endpoint_name,
                    target_container_id, target_container_name, status,
                    approved_by, approved_at, rejected_by, rejected_at, rejection_reason,
                    executed_at, execution_result, error_message,
                    title, description, rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.id,
                    self._encode_datetime(action.created_at),
                    action.insight_id,
                    action.insight_title,
                    action.insight_severity,
                    action.action_type.value,
                    action.target_endpoint_id,
                    action.target_endpoint_name,
                    action.target_container_id,
                    action.target_container_name,
                    action.status.value,
                    action.approved_by,
                    self._encode_datetime(action.approved_at),
                    action.rejected_by,
                    self._encode_datetime(action.rejected_at),
                    action.rejection_reason,
                    self._encode_datetime(action.executed_at),
                    action.execution_result,
                    action.error_message,
                    action.title,
                    action.description,
                    action.rationale,
                ),
            )
            connection.commit()
            LOGGER.info("Created action %s: %s", action.id, action.title)

    def get_action(self, action_id: str) -> RemediationAction | None:
        """Get a specific action by ID."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM actions WHERE id = ?",
                (action_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_action(row)

    def get_pending_actions(self, limit: int = 100) -> list[RemediationAction]:
        """Get all pending actions awaiting user approval."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM actions
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (ActionStatus.PENDING.value, limit),
            )
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def get_approved_actions(self, limit: int = 100) -> list[RemediationAction]:
        """Get approved actions ready to execute."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM actions
                WHERE status = ?
                ORDER BY approved_at DESC
                LIMIT ?
                """,
                (ActionStatus.APPROVED.value, limit),
            )
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def get_actions_history(
        self,
        *,
        status: ActionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RemediationAction]:
        """Get action history with optional filtering."""
        query = "SELECT * FROM actions"
        params: list[str | int] = []

        if status:
            query += " WHERE status = ?"
            params.append(status.value)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock, self._connect() as connection:
            cursor = connection.execute(query, params)
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def approve_action(self, action_id: str, approved_by: str) -> bool:
        """Approve an action (does NOT execute it)."""
        now = datetime.now(timezone.utc)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE actions
                SET status = ?, approved_by = ?, approved_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    ActionStatus.APPROVED.value,
                    approved_by,
                    self._encode_datetime(now),
                    action_id,
                    ActionStatus.PENDING.value,
                ),
            )
            connection.commit()

            if cursor.rowcount > 0:
                LOGGER.info("Action %s approved by %s", action_id, approved_by)
                return True
            return False

    def reject_action(
        self, action_id: str, rejected_by: str, reason: str | None = None
    ) -> bool:
        """Reject an action."""
        now = datetime.now(timezone.utc)

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE actions
                SET status = ?, rejected_by = ?, rejected_at = ?, rejection_reason = ?
                WHERE id = ? AND status = ?
                """,
                (
                    ActionStatus.REJECTED.value,
                    rejected_by,
                    self._encode_datetime(now),
                    reason,
                    action_id,
                    ActionStatus.PENDING.value,
                ),
            )
            connection.commit()

            if cursor.rowcount > 0:
                LOGGER.info("Action %s rejected by %s", action_id, rejected_by)
                return True
            return False

    def mark_executing(self, action_id: str) -> bool:
        """Mark an approved action as executing."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE actions
                SET status = ?
                WHERE id = ? AND status = ?
                """,
                (
                    ActionStatus.EXECUTING.value,
                    action_id,
                    ActionStatus.APPROVED.value,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0

    def mark_executed(
        self, action_id: str, result: str, error: str | None = None
    ) -> bool:
        """Mark an action as executed."""
        now = datetime.now(timezone.utc)
        status = ActionStatus.FAILED if error else ActionStatus.EXECUTED

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE actions
                SET status = ?, executed_at = ?, execution_result = ?, error_message = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    self._encode_datetime(now),
                    result,
                    error,
                    action_id,
                    ActionStatus.EXECUTING.value,
                ),
            )
            connection.commit()

            if cursor.rowcount > 0:
                LOGGER.info("Action %s marked as %s", action_id, status.value)
                return True
            return False

    def get_history_summary(self) -> ActionHistory:
        """Get summary statistics for actions."""
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)

        with self._lock, self._connect() as connection:
            cursor = connection.execute("SELECT COUNT(*) FROM actions")
            total = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE status = ?",
                (ActionStatus.PENDING.value,),
            )
            pending = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE status = ?",
                (ActionStatus.APPROVED.value,),
            )
            approved = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE status = ?",
                (ActionStatus.REJECTED.value,),
            )
            rejected = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE status = ?",
                (ActionStatus.EXECUTED.value,),
            )
            executed = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE status = ?",
                (ActionStatus.FAILED.value,),
            )
            failed = cursor.fetchone()[0]

            cursor = connection.execute(
                "SELECT COUNT(*) FROM actions WHERE created_at >= ?",
                (self._encode_datetime(cutoff_24h),),
            )
            last_24h = cursor.fetchone()[0]

        # Calculate success rate (executed / (executed + failed))
        total_completed = executed + failed
        success_rate = (executed / total_completed * 100) if total_completed > 0 else 0.0

        return ActionHistory(
            total_actions=total,
            pending_count=pending,
            approved_count=approved,
            rejected_count=rejected,
            executed_count=executed,
            failed_count=failed,
            actions_last_24h=last_24h,
            success_rate=success_rate,
        )

    def has_pending_action_for_container(
        self,
        container_id: str,
        action_type: ActionType,
    ) -> bool:
        """Check if a pending action already exists for this container and type."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT COUNT(*) FROM actions
                WHERE target_container_id = ?
                AND action_type = ?
                AND status IN (?, ?)
                """,
                (
                    container_id,
                    action_type.value,
                    ActionStatus.PENDING.value,
                    ActionStatus.APPROVED.value,
                ),
            )
            return cursor.fetchone()[0] > 0

    def purge_old_actions(self, days: int = 30) -> int:
        """Remove actions older than the specified days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with self._lock, self._connect() as connection:
            # Only delete completed actions (executed, failed, rejected)
            cursor = connection.execute(
                """
                DELETE FROM actions
                WHERE created_at < ?
                AND status IN (?, ?, ?)
                """,
                (
                    self._encode_datetime(cutoff),
                    ActionStatus.EXECUTED.value,
                    ActionStatus.FAILED.value,
                    ActionStatus.REJECTED.value,
                ),
            )
            deleted = cursor.rowcount
            connection.commit()

        if deleted > 0:
            LOGGER.info("Purged %d old actions", deleted)

        return deleted


_actions_store: SQLiteActionsStore | None = None


async def get_actions_store() -> SQLiteActionsStore:
    """Get or create the actions store singleton."""
    global _actions_store
    if _actions_store is None:
        settings = get_settings()
        _actions_store = SQLiteActionsStore(settings.remediation.sqlite_path)
    return _actions_store


__all__ = [
    "SQLiteActionsStore",
    "get_actions_store",
]
