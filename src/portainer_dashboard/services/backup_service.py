"""Backup service for Portainer environment data."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from portainer_dashboard.config import PROJECT_ROOT, get_settings

if TYPE_CHECKING:
    from portainer_dashboard.services.portainer_client import AsyncPortainerClient

LOGGER = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Raised when backup creation fails."""


class BackupService:
    """Service for creating and managing Portainer backups."""

    def __init__(self, backup_dir: Path | None = None) -> None:
        if backup_dir is None:
            backup_dir = PROJECT_ROOT / ".data" / "backups"
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(
        self,
        client: "AsyncPortainerClient",
        *,
        password: str | None = None,
    ) -> tuple[Path, int]:
        """Create a backup using the Portainer client.

        Parameters
        ----------
        client
            The Portainer client to use for creating the backup.
        password
            Optional password to encrypt the backup.

        Returns
        -------
        tuple[Path, int]
            The path to the backup file and its size in bytes.
        """
        try:
            content, filename = await client.create_backup(password=password)
        except Exception as exc:
            LOGGER.error("Failed to create backup: %s", exc)
            raise BackupError(f"Failed to create backup: {exc}") from exc

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"portainer_backup_{timestamp}.tar.gz"

        backup_path = self.backup_dir / filename
        backup_path.write_bytes(content)

        LOGGER.info("Backup created: %s (%d bytes)", backup_path, len(content))
        return backup_path, len(content)

    def list_backups(self) -> list[dict]:
        """List all available backups.

        Returns
        -------
        list[dict]
            List of backup metadata dictionaries.
        """
        backups = []
        for path in self.backup_dir.glob("*.tar.gz"):
            stat = path.stat()
            backups.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    def delete_backup(self, filename: str) -> bool:
        """Delete a backup by filename.

        Parameters
        ----------
        filename
            The filename of the backup to delete.

        Returns
        -------
        bool
            True if the backup was deleted, False if not found.
        """
        backup_path = self.backup_dir / filename
        if not backup_path.exists():
            return False
        if not backup_path.is_relative_to(self.backup_dir):
            raise BackupError("Invalid backup path")
        backup_path.unlink()
        LOGGER.info("Backup deleted: %s", backup_path)
        return True

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """Remove old backups, keeping the most recent ones.

        Parameters
        ----------
        keep_count
            Number of most recent backups to keep.

        Returns
        -------
        int
            Number of backups deleted.
        """
        backups = self.list_backups()
        if len(backups) <= keep_count:
            return 0

        to_delete = backups[keep_count:]
        deleted = 0
        for backup in to_delete:
            if self.delete_backup(backup["filename"]):
                deleted += 1

        return deleted


def create_backup_service() -> BackupService:
    """Create a backup service instance."""
    return BackupService()


__all__ = [
    "BackupError",
    "BackupService",
    "create_backup_service",
]
