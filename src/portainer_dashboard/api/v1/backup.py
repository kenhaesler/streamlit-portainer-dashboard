"""Backup API for Portainer environment backups."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.models.portainer import BackupRequest, BackupResponse
from portainer_dashboard.services.backup_service import BackupError, create_backup_service
from portainer_dashboard.services.portainer_client import (
    PortainerAPIError,
    create_portainer_client,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create", response_model=BackupResponse)
async def create_backup(
    user: CurrentUserDep,
    request: BackupRequest | None = None,
    environment: Annotated[str | None, Query(description="Environment name")] = None,
) -> BackupResponse:
    """Create a new Portainer backup."""
    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    if not environments:
        return BackupResponse(
            success=False,
            message="No Portainer environments configured",
        )

    if environment:
        environments = [e for e in environments if e.name == environment]
        if not environments:
            return BackupResponse(
                success=False,
                message=f"Environment '{environment}' not found",
            )

    # Use the first environment for backup
    env = environments[0]
    client = create_portainer_client(env)
    backup_service = create_backup_service()

    try:
        async with client:
            password = request.password if request else None
            backup_path, size = await backup_service.create_backup(
                client, password=password
            )
            return BackupResponse(
                success=True,
                filename=backup_path.name,
                size=size,
                message=f"Backup created successfully: {backup_path.name}",
            )
    except (PortainerAPIError, BackupError) as exc:
        LOGGER.error("Backup failed: %s", exc)
        return BackupResponse(
            success=False,
            message=str(exc),
        )


@router.get("/list")
async def list_backups(user: CurrentUserDep) -> list[dict]:
    """List all available backups."""
    backup_service = create_backup_service()
    return backup_service.list_backups()


@router.get("/download/{filename}")
async def download_backup(
    filename: str,
    user: CurrentUserDep,
) -> FileResponse:
    """Download a backup file."""
    backup_service = create_backup_service()
    backups = backup_service.list_backups()

    for backup in backups:
        if backup["filename"] == filename:
            return FileResponse(
                path=backup["path"],
                filename=filename,
                media_type="application/gzip",
            )

    raise HTTPException(status_code=404, detail="Backup not found")


@router.delete("/{filename}")
async def delete_backup(
    filename: str,
    user: CurrentUserDep,
) -> dict:
    """Delete a backup file."""
    backup_service = create_backup_service()

    if backup_service.delete_backup(filename):
        return {"success": True, "message": f"Backup '{filename}' deleted"}

    raise HTTPException(status_code=404, detail="Backup not found")


__all__ = ["router"]
