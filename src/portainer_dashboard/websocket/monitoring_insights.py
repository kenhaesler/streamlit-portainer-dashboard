"""WebSocket endpoint for real-time monitoring insights."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from portainer_dashboard.auth.dependencies import SESSION_COOKIE_NAME
from portainer_dashboard.config import get_settings
from portainer_dashboard.core.session import SessionStorage
from portainer_dashboard.dependencies import get_session_storage
from portainer_dashboard.models.auth import SessionData
from portainer_dashboard.models.monitoring import MonitoringInsight, MonitoringReport
from portainer_dashboard.services.insights_store import get_insights_store

LOGGER = logging.getLogger(__name__)


async def _authenticate_websocket(websocket: WebSocket) -> SessionData | None:
    """Authenticate a WebSocket connection using session cookie.

    Args:
        websocket: The WebSocket connection to authenticate.

    Returns:
        SessionData if authenticated, None otherwise.
    """
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    storage: SessionStorage = get_session_storage()
    record = storage.retrieve(token)
    if record is None:
        return None

    now = datetime.now(timezone.utc)
    settings = get_settings()

    session_data = SessionData(
        token=record.token,
        username=record.username,
        auth_method=record.auth_method,
        authenticated_at=record.authenticated_at,
        last_active=record.last_active,
        session_timeout=record.session_timeout or settings.auth.session_timeout,
    )

    if session_data.is_expired(now):
        storage.delete(token)
        return None

    # Update last active time
    storage.touch(
        token,
        last_active=now,
        session_timeout=session_data.session_timeout,
    )

    return session_data

router = APIRouter()

_connected_clients: set[WebSocket] = set()
_clients_lock = asyncio.Lock()


async def broadcast_insight(insight: MonitoringInsight) -> None:
    """Broadcast a single insight to all connected clients."""
    message = {
        "type": "insight",
        "content": insight.model_dump(mode="json"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await _broadcast_message(message)


async def broadcast_report(report: MonitoringReport) -> None:
    """Broadcast a complete report to all connected clients."""
    message = {
        "type": "report",
        "content": report.model_dump(mode="json"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await _broadcast_message(message)


async def _broadcast_message(message: dict[str, Any]) -> None:
    """Broadcast a message to all connected WebSocket clients."""
    async with _clients_lock:
        if not _connected_clients:
            return

        disconnected: list[WebSocket] = []
        message_json = json.dumps(message)

        for client in _connected_clients:
            try:
                await client.send_text(message_json)
            except Exception as exc:
                LOGGER.debug("Failed to send to client: %s", exc)
                disconnected.append(client)

        for client in disconnected:
            _connected_clients.discard(client)

    if disconnected:
        LOGGER.info("Removed %d disconnected clients", len(disconnected))


async def _send_heartbeat(websocket: WebSocket) -> None:
    """Send periodic heartbeat to keep connection alive."""
    while True:
        try:
            await asyncio.sleep(30)
            message = {
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await websocket.send_json(message)
        except Exception:
            break


async def _handle_client_message(
    websocket: WebSocket, data: dict[str, Any]
) -> None:
    """Handle incoming message from client."""
    msg_type = data.get("type")

    if msg_type == "ping":
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    elif msg_type == "get_history":
        limit = data.get("limit", 50)
        if not isinstance(limit, int) or limit < 1:
            limit = 50
        limit = min(limit, 100)

        store = await get_insights_store()
        insights = await store.get_insights(limit=limit)

        await websocket.send_json({
            "type": "history",
            "content": [i.model_dump(mode="json") for i in insights],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    elif msg_type == "get_latest_report":
        store = await get_insights_store()
        report = await store.get_latest_report()

        if report:
            await websocket.send_json({
                "type": "report",
                "content": report.model_dump(mode="json"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            await websocket.send_json({
                "type": "no_report",
                "content": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    else:
        await websocket.send_json({
            "type": "error",
            "content": f"Unknown message type: {msg_type}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


@router.websocket("/ws/monitoring/insights")
async def monitoring_insights_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time monitoring insights."""
    # Authenticate before accepting connection
    user = await _authenticate_websocket(websocket)
    if user is None:
        await websocket.close(code=4001, reason="Not authenticated")
        LOGGER.warning("Monitoring WebSocket connection rejected: not authenticated")
        return

    await websocket.accept()
    LOGGER.info("Monitoring WebSocket client connected for user: %s", user.username)

    async with _clients_lock:
        _connected_clients.add(websocket)
        client_count = len(_connected_clients)

    LOGGER.info("Active monitoring WebSocket clients: %d", client_count)

    heartbeat_task = asyncio.create_task(_send_heartbeat(websocket))

    try:
        store = await get_insights_store()
        latest_report = await store.get_latest_report()
        if latest_report:
            await websocket.send_json({
                "type": "report",
                "content": latest_report.model_dump(mode="json"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        while True:
            try:
                text = await websocket.receive_text()
                data = json.loads(text)
                await _handle_client_message(websocket, data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "Invalid JSON",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    except WebSocketDisconnect:
        LOGGER.info("Monitoring WebSocket client disconnected")
    except Exception as exc:
        LOGGER.warning("Monitoring WebSocket error: %s", exc)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        async with _clients_lock:
            _connected_clients.discard(websocket)
            remaining = len(_connected_clients)

        LOGGER.info("Remaining monitoring WebSocket clients: %d", remaining)


def get_connected_client_count() -> int:
    """Return the number of connected WebSocket clients."""
    return len(_connected_clients)


__all__ = [
    "broadcast_insight",
    "broadcast_report",
    "get_connected_client_count",
    "router",
]
