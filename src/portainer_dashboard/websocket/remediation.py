"""WebSocket endpoint for real-time remediation action notifications."""

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
from portainer_dashboard.models.remediation import RemediationAction
from portainer_dashboard.services.actions_store import get_actions_store

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


async def broadcast_action(action: RemediationAction) -> None:
    """Broadcast a remediation action to all connected clients."""
    message = {
        "type": "action",
        "content": action.model_dump(mode="json"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await _broadcast_message(message)


async def broadcast_action_update(action_id: str, status: str, **kwargs: Any) -> None:
    """Broadcast an action status update to all connected clients."""
    message = {
        "type": "action_update",
        "content": {
            "action_id": action_id,
            "status": status,
            **kwargs,
        },
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
        LOGGER.info("Removed %d disconnected remediation clients", len(disconnected))


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

    elif msg_type == "get_pending":
        limit = data.get("limit", 50)
        if not isinstance(limit, int) or limit < 1:
            limit = 50
        limit = min(limit, 100)

        store = await get_actions_store()
        actions = store.get_pending_actions(limit=limit)

        await websocket.send_json({
            "type": "pending_actions",
            "content": [a.model_dump(mode="json") for a in actions],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    elif msg_type == "get_approved":
        limit = data.get("limit", 50)
        if not isinstance(limit, int) or limit < 1:
            limit = 50
        limit = min(limit, 100)

        store = await get_actions_store()
        actions = store.get_approved_actions(limit=limit)

        await websocket.send_json({
            "type": "approved_actions",
            "content": [a.model_dump(mode="json") for a in actions],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    elif msg_type == "get_summary":
        store = await get_actions_store()
        summary = store.get_history_summary()

        await websocket.send_json({
            "type": "summary",
            "content": summary.model_dump(mode="json"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    else:
        await websocket.send_json({
            "type": "error",
            "content": f"Unknown message type: {msg_type}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


@router.websocket("/ws/remediation")
async def remediation_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time remediation notifications.

    Clients can:
    - Receive real-time notifications when actions are created/updated
    - Request current pending and approved actions
    - Request action summary statistics
    """
    # Authenticate before accepting connection
    user = await _authenticate_websocket(websocket)
    if user is None:
        await websocket.close(code=4001, reason="Not authenticated")
        LOGGER.warning("Remediation WebSocket connection rejected: not authenticated")
        return

    await websocket.accept()
    LOGGER.info("Remediation WebSocket client connected for user: %s", user.username)

    async with _clients_lock:
        _connected_clients.add(websocket)
        client_count = len(_connected_clients)

    LOGGER.info("Active remediation WebSocket clients: %d", client_count)

    heartbeat_task = asyncio.create_task(_send_heartbeat(websocket))

    try:
        # Send current pending actions on connect
        store = await get_actions_store()
        pending = store.get_pending_actions(limit=50)
        if pending:
            await websocket.send_json({
                "type": "pending_actions",
                "content": [a.model_dump(mode="json") for a in pending],
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
        LOGGER.info("Remediation WebSocket client disconnected")
    except Exception as exc:
        LOGGER.warning("Remediation WebSocket error: %s", exc)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        async with _clients_lock:
            _connected_clients.discard(websocket)
            remaining = len(_connected_clients)

        LOGGER.info("Remaining remediation WebSocket clients: %d", remaining)


def get_connected_client_count() -> int:
    """Return the number of connected WebSocket clients."""
    return len(_connected_clients)


__all__ = [
    "broadcast_action",
    "broadcast_action_update",
    "get_connected_client_count",
    "router",
]
