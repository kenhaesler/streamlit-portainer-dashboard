"""Logs API - Query logs from Kibana/Elasticsearch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from portainer_dashboard.auth.dependencies import CurrentUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.services.kibana_client import (
    AsyncKibanaClient,
    KibanaClientError,
    create_kibana_client,
)

router = APIRouter(tags=["Logs"])


def get_kibana_client() -> AsyncKibanaClient:
    """Get the Kibana client or raise 503 if not configured."""
    client = create_kibana_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Kibana integration is not configured. Set KIBANA_LOGS_ENDPOINT and KIBANA_API_KEY.",
        )
    return client


@router.get("/")
async def query_logs(
    user: CurrentUserDep,
    hostname: Annotated[str | None, Query(description="Edge agent hostname to filter by")] = None,
    container: Annotated[str | None, Query(description="Container name to filter by")] = None,
    query: Annotated[str | None, Query(description="Free text search in log messages")] = None,
    start_time: Annotated[str | None, Query(description="Start time in ISO format")] = None,
    end_time: Annotated[str | None, Query(description="End time in ISO format")] = None,
    size: Annotated[int, Query(ge=1, le=1000, description="Maximum number of log entries")] = 200,
    kibana: AsyncKibanaClient = Depends(get_kibana_client),
) -> list[dict]:
    """Query logs from Kibana/Elasticsearch.

    Requires Kibana integration to be configured via environment variables.
    """
    # Parse time range
    now = datetime.now(timezone.utc)

    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time format. Use ISO format.")
    else:
        # Default to last hour
        from datetime import timedelta
        start_dt = now - timedelta(hours=1)

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time format. Use ISO format.")
    else:
        end_dt = now

    # Hostname is required for Kibana queries
    if not hostname:
        raise HTTPException(
            status_code=400,
            detail="hostname parameter is required for log queries",
        )

    try:
        df = await kibana.fetch_logs(
            hostname=hostname,
            start_time=start_dt,
            end_time=end_dt,
            container_name=container,
            search_term=query,
            size=size,
        )

        # Convert DataFrame to list of dicts
        return df.to_dict(orient="records")

    except KibanaClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {e}")


@router.get("/status")
async def logs_status(user: CurrentUserDep) -> dict:
    """Check if Kibana integration is configured and available."""
    settings = get_settings()

    if not settings.kibana.is_configured:
        return {
            "configured": False,
            "message": "Kibana is not configured. Set KIBANA_LOGS_ENDPOINT and KIBANA_API_KEY.",
        }

    return {
        "configured": True,
        "endpoint": settings.kibana.logs_endpoint,
        "verify_ssl": settings.kibana.verify_ssl,
    }


__all__ = ["router"]
